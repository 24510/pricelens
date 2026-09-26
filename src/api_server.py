# -*- coding: utf-8 -*-
"""本地采集接口（仅监听 127.0.0.1）：供浏览器脚本上报价格。

安全约定：
  · 只绑定回环地址，外部网络无法访问；
  · 写操作（/api/report）必须携带本机令牌（X-PL-Token 请求头）；
  · 在线安装（/pricelens.user.js）不携带 CORS 头，防止其它网站窃取令牌；
  · 请求体大小受限；所有响应均为 UTF-8 JSON；
  · 令牌不写入日志。

上报模式（请求体 mode 字段）：
  · manual（默认）：点「记录」按钮上报；与最近一条同价且 90 秒内视为重复点击；
  · auto：页面加载后自动上报；仅对已在监控列表的商品生效，价格未变化时跳过。
"""
from __future__ import annotations

import hmac
import json
import re
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

import links
import userscript
from const import APP_NAME, APP_VERSION

MAX_BODY = 64 * 1024          # 单次请求体上限
DUP_SECONDS = 90              # 防重复：同价且在此秒数内视为重复点击
_TOKEN_HEADER = "X-PL-Token"


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_price(raw) -> Optional[float]:
    try:
        text = str(raw).replace("¥", "").replace(",", "").strip()
        value = float(text)
    except Exception:
        return None
    if value <= 0 or value > 10_000_000:
        return None
    return round(value, 2)


def _is_fresh(captured_at: str, seconds: int = DUP_SECONDS) -> bool:
    try:
        dt = datetime.strptime(str(captured_at), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return False
    return (datetime.now() - dt).total_seconds() <= seconds


def _last_same_price(db, item_pk: int, price: float) -> Tuple[bool, Any]:
    """最近一条价格是否与本次相同；返回 (是否相同, 最近一条记录)。"""
    last = db.list_prices(item_pk, 1)
    if not last:
        return False, None
    row = last[0]
    try:
        same = abs(float(row["price"]) - float(price)) < 0.005
    except Exception:
        same = False
    return same, row


def process_report(ctx, data: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """处理一次上报；返回 (HTTP 状态码, 响应对象)。"""
    db = getattr(ctx, "db", None)
    if db is None:
        return 503, {"ok": False, "message": "数据库尚未就绪，请重启程序"}

    dry = bool(data.get("dry"))
    mode = str(data.get("mode") or "manual").strip().lower()
    auto = (mode == "auto")

    platform = str(data.get("platform") or "").strip().lower()
    if platform not in links.PLATFORM_NAMES:
        return 400, {"ok": False, "message": "平台无效（应为 pdd / jd / tb）"}

    item_id = re.sub(r"\D", "", str(data.get("item_id") or ""))
    if len(item_id) < 5:
        return 400, {"ok": False, "message": "商品 ID 无效"}

    title = str(data.get("title") or "").strip()[:200]
    shop = str(data.get("shop") or "").strip()[:100]
    note = str(data.get("note") or "").strip()[:60]
    url = str(data.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        url = links.canonical_url(platform, item_id)

    raw_price = data.get("price", None)
    has_price = raw_price not in (None, "", "null")
    price = _parse_price(raw_price) if has_price else None
    if has_price and price is None:
        return 400, {"ok": False, "message": "价格无效"}

    existing = db.find_item(platform, item_id)
    item_created = existing is None

    if dry:
        act = ("新增商品并" if item_created else "") + \
              ("记录价格" if has_price else "收藏商品")
        return 200, {"ok": True, "dry": True, "item_created": item_created,
                     "duplicate": False, "skipped": False,
                     "message": f"试运行通过：将{act}，未写入数据"}

    # 自动模式：只处理“已在监控列表”的商品（新商品仍由手动「记录」加入）
    if auto and existing is None:
        return 200, {"ok": True, "skipped": True, "reason": "unknown",
                     "item_created": False, "duplicate": False,
                     "message": "该商品尚未在监控列表（点「记录」可加入监控）"}

    if existing is None:
        res = db.add_item(platform=platform, item_id=item_id,
                          title=title or "未命名商品", shop=shop, url=url)
        item = res["item"]
    else:
        item = existing

    pk = int(item["id"])
    item_title = item.get("title") or title or "未命名商品"

    if has_price:
        same, last_row = _last_same_price(db, pk, price)

        if auto:
            if same:
                return 200, {
                    "ok": True, "skipped": True, "reason": "unchanged",
                    "item_created": item_created, "duplicate": False,
                    "item": {"id": pk, "platform": platform, "item_id": item_id,
                             "title": item_title},
                    "stats": db.item_stats(pk),
                    "message": f"价格未变化（¥{price:.2f}），未记录",
                }
            db.add_price(pk, price, captured_at=_now_str(),
                         source="script", note="")
            message = f"价格有变化，已自动记录（¥{price:.2f}）"
        else:
            if same and _is_fresh(str((last_row or {}).get("captured_at") or "")):
                return 200, {
                    "ok": True, "item_created": item_created, "duplicate": True,
                    "skipped": True, "reason": "duplicate",
                    "item": {"id": pk, "platform": platform, "item_id": item_id,
                             "title": item_title},
                    "stats": db.item_stats(pk),
                    "message": "价格与最近一次相同，已跳过（防重复点击）",
                }
            db.add_price(pk, price, captured_at=_now_str(),
                         source="script", note=note)
            message = "已新增商品并记录价格" if item_created else "已记录价格"
    else:
        message = ("已收藏商品（未记录价格）" if item_created
                   else "商品已存在（未记录价格）")

    return 200, {
        "ok": True, "item_created": item_created, "duplicate": False,
        "skipped": False, "auto": auto,
        "item": {"id": pk, "platform": platform, "item_id": item_id,
                 "title": item_title},
        "stats": db.item_stats(pk),
        "message": message,
    }


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    ctx = None
    token = ""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PriceLens"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    # ---------- 基础 ----------

    def _send_cors(self) -> None:
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-PL-Token")
        self.send_header("Access-Control-Max-Age", "600")
        if str(self.headers.get("Access-Control-Request-Private-Network", "")).lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, code: int, obj: Dict[str, Any]) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self._send_cors()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "请求长度无效"
        if length <= 0:
            return {}, ""
        if length > MAX_BODY:
            return None, "请求体过大"
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:
            return None, "请求体不是合法 JSON"
        if not isinstance(data, dict):
            return None, "请求体应为 JSON 对象"
        return data, ""

    def _authorized(self, data) -> bool:
        expected = getattr(self.server, "token", "") or ""
        if not expected:
            return False
        token = str(self.headers.get(_TOKEN_HEADER) or "").strip()
        if not token and isinstance(data, dict):
            token = str(data.get("token") or "").strip()
        return bool(token) and hmac.compare_digest(token, expected)

    def _ctx_log(self):
        ctx = getattr(self.server, "ctx", None)
        return getattr(ctx, "log", None)

    def _log_result(self, data: Dict[str, Any], obj: Dict[str, Any]) -> None:
        lg = self._ctx_log()
        if not lg:
            return
        try:
            price = data.get("price")
            price_text = price if price not in (None, "") else "（无）"
            mode = data.get("mode") or "manual"
            if obj.get("ok"):
                lg.info("采集上报: %s/%s 价格=%s 模式=%s 结果=%s",
                        data.get("platform"), data.get("item_id"),
                        price_text, mode, obj.get("message"))
            else:
                lg.warning("采集上报失败: %s/%s 模式=%s 原因=%s",
                           data.get("platform"), data.get("item_id"),
                           mode, obj.get("message"))
        except Exception:
            pass

    # ---------- 在线安装 ----------

    def _serve_userscript(self) -> None:
        """在浏览器打开本地址即弹出脚本安装页（地址以 .user.js 结尾）。

        注意：此响应刻意不携带 CORS 头，防止其它网站跨站读取内嵌令牌。
        """
        token = getattr(self.server, "token", "") or ""
        try:
            port = int(self.server.server_address[1])
            body = userscript.build_script(token, port, APP_VERSION).encode("utf-8")
        except Exception as exc:
            self._send_json(500, {"ok": False, "message": f"脚本生成失败：{exc}"})
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- 路由 ----------

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors()
        self.end_headers()

    def do_GET(self):
        route = self.path.split("?")[0].rstrip("/")
        if route == "/api/ping":
            self._send_json(200, {"ok": True, "app": APP_NAME, "auth_required": True})
        elif route == "/pricelens.user.js":
            self._serve_userscript()
        elif route in ("", "/api"):
            self._send_json(200, {"ok": True, "app": APP_NAME,
                                  "message": "PriceLens 采集接口运行中（仅供浏览器脚本上报，非网页界面）"})
        else:
            self._send_json(404, {"ok": False, "message": "接口不存在"})

    def do_POST(self):
        route = self.path.split("?")[0].rstrip("/")
        if route != "/api/report":
            self._send_json(404, {"ok": False, "message": "接口不存在"})
            return

        data, err = self._read_json()
        if err:
            self._send_json(400, {"ok": False, "message": err})
            return
        if not self._authorized(data):
            lg = self._ctx_log()
            if lg:
                try:
                    lg.warning("采集接口拒绝：令牌不匹配（来自本机 %s）",
                               self.client_address[0])
                except Exception:
                    pass
            self._send_json(401, {"ok": False,
                                  "message": "令牌不匹配：请在 PriceLens 里重置令牌并重新安装脚本"})
            return

        try:
            code, obj = process_report(getattr(self.server, "ctx", None), data)
        except Exception as exc:
            code, obj = 500, {"ok": False, "message": f"服务器内部错误：{exc}"}
        self._log_result(data, obj)
        self._send_json(code, obj)


class ApiServer:
    """采集接口服务包装：start / stop。"""

    def __init__(self, ctx) -> None:
        self._ctx = ctx
        self._httpd: Optional[_Server] = None
        self.port = 0

    def running(self) -> bool:
        return self._httpd is not None and self.port > 0

    def start(self, port: int, token: str) -> Tuple[bool, str]:
        self.stop()
        if not token:
            return False, "本机令牌缺失（请重启程序）"
        try:
            httpd = _Server(("127.0.0.1", int(port)), _Handler)
        except OSError as exc:
            return False, f"端口 {port} 无法绑定（可能被占用）：{exc}"

        httpd.ctx = self._ctx
        httpd.token = token
        threading.Thread(target=httpd.serve_forever, daemon=True,
                         name="pricelens-api").start()
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        return True, ""

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        self.port = 0
        if httpd is None:
            return
        try:
            httpd.shutdown()
            httpd.server_close()
        except Exception:
            pass