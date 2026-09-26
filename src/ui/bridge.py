# -*- coding: utf-8 -*-
"""前端与 Python 的桥接层（JS 通过 window.pywebview.api 调用）。

规则（pywebview 6）：
  · 公开方法暴露给 JS；公开属性会被递归序列化 →
    内部引用必须用下划线私有属性（self._ctx）。
"""
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict

import links
import paths
import platform_keys as pk
from app_context import AppContext
from const import APP_VERSION, DATA_ROOT_NAME, DIR_CONFIG, DIR_USERSCRIPT
from ui.dialogs import pick_folder


def _compose_ts(date_str: str) -> str:
    """把界面输入的日期补全成时间戳。

    当天 → 当前时刻；其它日期 → 当天 00:00:00。
    """
    raw = (date_str or "").strip().replace("/", "-").replace(".", "-")
    now = datetime.now()
    if not raw:
        return now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        d = datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        raise ValueError("日期格式应为 2026-09-25")
    if d.date() == now.date():
        return d.strftime("%Y-%m-%d") + " " + now.strftime("%H:%M:%S")
    return d.strftime("%Y-%m-%d") + " 00:00:00"


class Bridge:
    """暴露给 JS 的接口：公开方法 + 私有属性。"""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx            # ★ 必须私有

    # ---------------- 基础 ----------------

    def ping(self) -> Dict:
        return {"ok": True, "version": APP_VERSION}

    def get_state(self) -> Dict:
        return self._ctx.state()

    # ---------------- 数据目录 ----------------

    def choose_data_dir(self) -> Dict:
        import webview
        win = webview.windows[0] if getattr(webview, "windows", None) else None
        start_dir = str(self._ctx.data_root) if self._ctx.data_root else str(paths.app_root())

        chosen = pick_folder(win, start_dir)
        if not chosen:
            return {"ok": False, "message": "已取消选择"}

        target = Path(chosen)
        note = ""
        if target == Path(target.anchor):
            target = target / DATA_ROOT_NAME
            note = f"已自动使用子文件夹：{target}"

        if paths.is_protected(target):
            return {"ok": False,
                    "message": r"该目录受系统保护（如 C:\Program Files），请换一个，例如 D:\PriceLensData"}
        if not paths.is_writable(target):
            return {"ok": False, "message": "该目录不可写入，请换一个"}

        try:
            paths.write_location(target)
            self._ctx.init_at(target, escape=True)
        except Exception as exc:
            return {"ok": False, "message": f"初始化失败：{exc}"}

        return {"ok": True, "state": self._ctx.state(), "message": note}

    def reset_data_dir(self) -> Dict:
        root = paths.default_data_root()
        if not paths.is_writable(root):
            return {"ok": False, "message": "程序目录不可写，无法恢复默认"}
        try:
            paths.clear_location()
            self._ctx.init_at(root, escape=False)
        except Exception as exc:
            return {"ok": False, "message": f"初始化失败：{exc}"}
        return {"ok": True, "state": self._ctx.state()}

    def open_path(self, kind: str = "data_root") -> Dict:
        if not self._ctx.data_root:
            return {"ok": False, "message": "尚未初始化数据目录"}
        mapping = {
            "data_root": self._ctx.data_root,
            "data": self._ctx.data_root / "data",
            "logs": self._ctx.data_root / "logs",
            "config": self._ctx.data_root / "config",
            "exports": self._ctx.data_root / "exports",
            "userscript": self._ctx.data_root / DIR_USERSCRIPT,
        }
        target = mapping.get(kind, self._ctx.data_root)
        if kind in ("userscript", "exports"):
            try:
                target = Path(target)
                target.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
        try:
            subprocess.Popen(["explorer", str(target)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def open_url(self, url: str) -> Dict:
        u = (url or "").strip()
        if not u.lower().startswith(("http://", "https://")):
            return {"ok": False, "message": "链接无效"}
        try:
            import webbrowser
            webbrowser.open(u)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def reveal_script(self) -> Dict:
        target = paths.app_root() / "tools"
        try:
            subprocess.Popen(["explorer", str(target)])
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    # ---------------- 平台密钥（可选 · 增强模式） ----------------

    def _ini_path(self) -> Path:
        return self._ctx.data_root / DIR_CONFIG / "config.ini"

    def _reload_config(self):
        try:
            import config
            self._ctx.cfg = config.load(self._ctx.data_root / DIR_CONFIG)
            return True, ""
        except Exception:
            return False, "已保存，重启程序后生效"

    def get_platform_settings(self) -> Dict:
        if not self._ctx.data_root:
            return {"ok": False, "message": "尚未初始化数据目录"}
        ini = self._ini_path()
        if not ini.is_file():
            return {"ok": False, "message": f"配置文件不存在：{ini}"}

        items = []
        for pf in pk.PLATFORMS:
            values = pk.read_values(ini, pf["id"])
            items.append({
                "id": pf["id"],
                "name": pf["name"],
                "fields": [
                    {
                        "key": key,
                        "label": label,
                        "hint": hint,
                        "filled": bool(values.get(key)),
                        "masked": pk.mask_value(values.get(key, "")),
                    }
                    for key, label, hint in pf["fields"]
                ],
            })
        return {"ok": True, "platforms": items, "ini": str(ini)}

    def save_platform_settings(self, platform: str, values: Dict) -> Dict:
        if not self._ctx.data_root:
            return {"ok": False, "message": "尚未初始化数据目录"}
        if not pk.get_platform(platform):
            return {"ok": False, "message": f"未知平台：{platform}"}
        ini = self._ini_path()
        if not ini.is_file():
            return {"ok": False, "message": f"配置文件不存在：{ini}"}

        allowed = {key for key, _, _ in pk.fields_of(platform)}
        data: Dict[str, str] = {}
        for key, value in (values or {}).items():
            text = str(value).strip()
            if key in allowed and text:
                data[key] = text
        if not data:
            return {"ok": False, "message": "没有需要保存的新内容"}

        try:
            count = pk.update_values(ini, platform, data)
        except Exception as exc:
            return {"ok": False, "message": f"写入失败：{exc}"}

        reloaded, note = self._reload_config()
        return {"ok": True, "count": count, "reloaded": reloaded, "message": note,
                "state": self._ctx.state() if reloaded else None}

    def clear_platform_settings(self, platform: str) -> Dict:
        if not self._ctx.data_root:
            return {"ok": False, "message": "尚未初始化数据目录"}
        if not pk.get_platform(platform):
            return {"ok": False, "message": f"未知平台：{platform}"}
        ini = self._ini_path()
        if not ini.is_file():
            return {"ok": False, "message": f"配置文件不存在：{ini}"}

        keys = [key for key, _, _ in pk.fields_of(platform)]
        try:
            pk.update_values(ini, platform, {}, blank=keys)
        except Exception as exc:
            return {"ok": False, "message": f"写入失败：{exc}"}

        reloaded, note = self._reload_config()
        return {"ok": True, "reloaded": reloaded, "message": note,
                "state": self._ctx.state() if reloaded else None}

    # ---------------- 采集通道（一键记价） ----------------

    def _script_path(self) -> Path:
        return self._ctx.data_root / DIR_USERSCRIPT / "pricelens.user.js"

    def get_capture_info(self) -> Dict:
        if not self._ctx.data_root:
            return {"ok": False, "message": "尚未初始化数据目录"}
        info = self._ctx.api_info()
        path = self._script_path()
        running = bool(info.get("running"))
        port = info.get("port") or self._ctx.api_port()
        return {
            "ok": True,
            "running": running,
            "port": port,
            "url": f"http://127.0.0.1:{port}" if running else "",
            "token_masked": info.get("token_masked") or "",
            "error": info.get("error") or "",
            "script_path": str(path),
            "script_exists": path.is_file(),
            "version": APP_VERSION,
        }

    def generate_userscript(self) -> Dict:
        if not self._ctx.data_root:
            return {"ok": False, "message": "尚未初始化数据目录"}
        try:
            import userscript
            path = userscript.write_script(self._ctx.data_root,
                                           self._ctx.local_token(),
                                           self._ctx.api_port(), APP_VERSION)
        except Exception as exc:
            return {"ok": False, "message": f"生成失败：{exc}"}
        size = path.stat().st_size if path.is_file() else 0
        return {"ok": True, "path": str(path), "size": size,
                "message": "已生成脚本（内嵌本机令牌）"}

    def test_capture_api(self) -> Dict:
        """后端自查：向本机接口发一条试运行请求（不写数据）。"""
        if not self._ctx.api_running():
            return {"ok": False,
                    "message": self._ctx.api_error or "采集接口未运行"}
        url = f"http://127.0.0.1:{self._ctx.api.port}/api/report"
        payload = {"platform": "jd", "item_id": "999999999999",
                   "price": 1.0, "title": "接口自检（不会写入）", "dry": True}
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-PL-Token": self._ctx.local_token()},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            return {"ok": False, "message": f"自检失败：{exc}"}
        if data.get("ok"):
            return {"ok": True, "message": data.get("message") or "接口连通正常"}
        return {"ok": False, "message": data.get("message") or "自检未通过"}

    def rotate_local_token(self) -> Dict:
        """重置本机令牌：旧脚本立即失效；自动重启接口并重写脚本。"""
        if not self._ctx.data_root:
            return {"ok": False, "message": "尚未初始化数据目录"}
        ini = self._ini_path()
        if not ini.is_file():
            return {"ok": False, "message": f"配置文件不存在：{ini}"}
        try:
            import config as cfg_mod
            from utils.security import new_token
            token = new_token()
            pk.update_values(ini, "app", {"local_token": token})
            self._ctx.cfg = cfg_mod.load(self._ctx.data_root / DIR_CONFIG)
            self._ctx.start_api()
            import userscript
            userscript.write_script(self._ctx.data_root, token,
                                    self._ctx.api_port(), APP_VERSION)
        except Exception as exc:
            return {"ok": False, "message": f"重置失败：{exc}"}
        return {"ok": True,
                "message": "已生成新令牌并重启接口；请重新安装脚本（旧脚本已失效）",
                "info": self.get_capture_info()}

    # ---------------- 商品与价格 ----------------

    def _db(self):
        return getattr(self._ctx, "db", None)

    def parse_link(self, url: str) -> Dict:
        try:
            return links.parse(url or "")
        except Exception as exc:
            return {"ok": False, "platform": None, "item_id": None,
                    "message": f"解析失败：{exc}"}

    def list_items(self) -> Dict:
        db = self._db()
        if db is None:
            return {"ok": True, "items": [], "stats": {"items": 0, "prices": 0}}
        try:
            return {"ok": True, "items": db.list_items(), "stats": db.stats()}
        except Exception as exc:
            return {"ok": False, "message": f"读取失败：{exc}"}

    def add_item(self, payload: Dict = None) -> Dict:
        db = self._db()
        if db is None:
            return {"ok": False, "message": "数据库尚未初始化"}
        payload = payload or {}

        platform = str(payload.get("platform") or "").strip().lower()
        if platform not in links.PLATFORM_NAMES:
            return {"ok": False, "message": "请选择平台（拼多多 / 京东 / 淘宝）"}

        item_id = re.sub(r"\D", "", str(payload.get("item_id") or ""))
        if len(item_id) < 5:
            return {"ok": False, "message": "商品 ID 不正确（应为 5 位以上的数字）"}

        title = str(payload.get("title") or "").strip()[:200] or "未命名商品"
        shop = str(payload.get("shop") or "").strip()[:100]
        url = str(payload.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            url = links.canonical_url(platform, item_id)

        try:
            res = db.add_item(platform=platform, item_id=item_id,
                              title=title, shop=shop, url=url)
        except Exception as exc:
            return {"ok": False, "message": f"保存失败：{exc}"}

        created = bool(res.get("created"))
        return {"ok": True, "created": created, "pk": res["item"]["id"],
                "message": "已添加" if created else "该商品已在监控列表中",
                "stats": db.stats()}

    def update_item(self, item_pk, payload: Dict = None) -> Dict:
        db = self._db()
        if db is None:
            return {"ok": False, "message": "数据库尚未初始化"}
        try:
            pk_int = int(item_pk)
        except Exception:
            return {"ok": False, "message": "参数错误"}
        if not db.get_item(pk_int):
            return {"ok": False, "message": "商品不存在或已删除"}

        payload = payload or {}
        title = str(payload.get("title") or "").strip()
        if not title:
            return {"ok": False, "message": "商品名称不能为空"}

        try:
            db.update_item(pk_int,
                           title=title[:200],
                           shop=str(payload.get("shop") or "").strip()[:100],
                           note=str(payload.get("note") or "").strip()[:200])
        except Exception as exc:
            return {"ok": False, "message": f"保存失败：{exc}"}

        return {"ok": True, "message": "已保存",
                "detail": self.get_item_detail(pk_int)}

    def delete_item(self, item_pk) -> Dict:
        db = self._db()
        if db is None:
            return {"ok": False, "message": "数据库尚未初始化"}
        try:
            pk_int = int(item_pk)
        except Exception:
            return {"ok": False, "message": "参数错误"}
        try:
            res = db.delete_item(pk_int)
        except Exception as exc:
            return {"ok": False, "message": f"删除失败：{exc}"}
        return {"ok": True, "deleted_prices": res.get("deleted_prices", 0),
                "stats": db.stats()}

    def get_item_detail(self, item_pk) -> Dict:
        db = self._db()
        if db is None:
            return {"ok": False, "message": "数据库尚未初始化"}
        try:
            pk_int = int(item_pk)
        except Exception:
            return {"ok": False, "message": "参数错误"}
        item = db.get_item(pk_int)
        if not item:
            return {"ok": False, "message": "商品不存在或已删除"}
        return {"ok": True, "item": item,
                "stats": db.item_stats(pk_int),
                "prices": db.list_prices(pk_int)}

    def add_price(self, item_pk, price, date_str: str = "", note: str = "") -> Dict:
        db = self._db()
        if db is None:
            return {"ok": False, "message": "数据库尚未初始化"}
        try:
            pk_int = int(item_pk)
        except Exception:
            return {"ok": False, "message": "参数错误"}
        if not db.get_item(pk_int):
            return {"ok": False, "message": "商品不存在或已删除"}

        try:
            value = float(str(price).replace("¥", "").replace(",", "").strip())
        except Exception:
            return {"ok": False, "message": "价格应为数字，如 129.00"}
        if value <= 0 or value > 10_000_000:
            return {"ok": False, "message": "价格超出合理范围"}

        try:
            captured = _compose_ts(date_str)
        except ValueError as exc:
            return {"ok": False, "message": str(exc)}

        try:
            db.add_price(pk_int, round(value, 2), captured_at=captured,
                         source="manual", note=str(note or "").strip()[:60])
        except Exception as exc:
            return {"ok": False, "message": f"保存失败：{exc}"}

        return {"ok": True, "message": "已记录",
                "detail": self.get_item_detail(pk_int),
                "stats": db.stats()}

    def delete_price(self, price_id) -> Dict:
        db = self._db()
        if db is None:
            return {"ok": False, "message": "数据库尚未初始化"}
        try:
            pid = int(price_id)
        except Exception:
            return {"ok": False, "message": "参数错误"}
        try:
            info = db.delete_price(pid)
        except Exception as exc:
            return {"ok": False, "message": f"删除失败：{exc}"}
        if not info:
            return {"ok": False, "message": "记录不存在"}
        return {"ok": True, "message": "已删除",
                "detail": self.get_item_detail(info["item_fk"]),
                "stats": db.stats()}

    # ---------------- 导出 CSV ----------------

    def _ask_save_path(self, default_name: str):
        """弹保存对话框；返回 (status, path)。

        status：picked / cancelled / unavailable（改存 exports 文件夹）
        """
        try:
            import webview
        except Exception:
            return "unavailable", None

        wins = getattr(webview, "windows", None) or []
        if not wins:
            return "unavailable", None
        win = wins[0]

        dialog_type = None
        fd = getattr(webview, "FileDialog", None)
        if fd is not None:
            dialog_type = getattr(fd, "SAVE", None)
        if dialog_type is None:
            dialog_type = getattr(webview, "SAVE_DIALOG", None)
        if dialog_type is None:
            return "unavailable", None

        res = None
        try:
            res = win.create_file_dialog(dialog_type, save_filename=default_name)
        except TypeError:
            try:
                res = win.create_file_dialog(dialog_type, "", False, default_name)
            except Exception:
                return "unavailable", None
        except Exception:
            return "unavailable", None

        if isinstance(res, (list, tuple)):
            res = res[0] if res else None
        if not res:
            return "cancelled", None
        path = str(res)
        if not path.lower().endswith(".csv"):
            path += ".csv"
        return "picked", path

    def export_csv(self) -> Dict:
        """导出全部价格记录为 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
        db = self._db()
        if db is None:
            return {"ok": False, "message": "数据库尚未初始化"}
        try:
            rows = db.export_rows()
        except Exception as exc:
            return {"ok": False, "message": f"读取失败：{exc}"}
        if not rows:
            return {"ok": False, "message": "还没有价格记录可以导出"}

        plat_names = {"pdd": "拼多多", "jd": "京东", "tb": "淘宝"}
        src_names = {"manual": "手动", "script": "脚本", "api": "自动"}

        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\r\n")
        writer.writerow(["平台", "商品名称", "商品ID", "店铺",
                         "日期时间", "价格", "来源", "备注", "链接"])
        for r in rows:
            price = r.get("price")
            price_text = "" if price is None else f"{float(price):.2f}"
            writer.writerow([
                plat_names.get(r.get("platform"), r.get("platform") or ""),
                r.get("title") or "",
                r.get("item_id") or "",
                r.get("shop") or "",
                r.get("captured_at") or "",
                price_text,
                src_names.get(r.get("source"), r.get("source") or ""),
                r.get("note") or "",
                r.get("url") or "",
            ])
        data = buf.getvalue().encode("utf-8-sig")

        default_name = ("PriceLens_价格导出_"
                        + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")

        status, target = "unavailable", None
        try:
            status, target = self._ask_save_path(default_name)
        except Exception:
            status, target = "unavailable", None

        if status == "cancelled":
            return {"ok": False, "message": "已取消导出"}

        fallback = False
        if status != "picked" or not target:
            exports_dir = self._ctx.data_root / "exports"
            try:
                exports_dir.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                return {"ok": False, "message": f"创建导出目录失败：{exc}"}
            target = exports_dir / default_name
            fallback = True

        try:
            Path(target).write_bytes(data)
        except Exception as exc:
            return {"ok": False, "message": f"写入失败：{exc}"}

        return {"ok": True, "count": len(rows), "path": str(target),
                "fallback": fallback,
                "message": "已放入 exports 文件夹" if fallback else "导出完成"}