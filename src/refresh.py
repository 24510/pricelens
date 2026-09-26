# -*- coding: utf-8 -*-
"""自动刷新调度器（P3）：定时调用平台采集器查价，变化才入库。

每轮流程：
  1. 挑出「增强模式平台」的商品（拼多多 / 京东；淘宝恒不参与）；
  2. 逐个调用采集器 fetch(item)；
  3. 与最近一条价格比对：
       变化 → 以 source='api' 写入一条记录（创下新低时另行计数）；
       未变 → 跳过（不产生垃圾行），只更新「最后检查时间」；
  4. 汇总写入 refresh_runs 表（界面显示 / 排错用）。

节奏（分钟，可在 config.ini 的 [app] 段调整）：
  · night  23:00–08:00         → refresh_interval_night（默认 240）
  · hot    24 小时内有价格变化  → refresh_interval_hot（默认 30）
  · cold   7 天以上无变化       → refresh_interval_cold（默认 720）
  · 其它                       → refresh_interval_normal（默认 120）
  （focus 档预留给「窗口聚焦加急」，P3.2 界面接入后启用。）

安全：只在程序内部运行；PRICELENS_MOCK=1 时使用模拟采集器，不访问网络。
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import collectors
import config as cfg_mod
from db.dao import now_str

API_SOURCE = "api"           # prices.source 取值：自动刷新写入
CHANGE_EPS = 0.005           # 价格变化判定阈值（分）
STARTUP_DELAY = 20           # 启动后首次检查延迟（秒）
MIN_INTERVAL_MIN = 1         # 间隔下限（分钟）
MAX_INTERVAL_MIN = 1440      # 间隔上限（分钟）
NIGHT_START_HOUR = 23        # 夜间时段：23:00 ~ 08:00
NIGHT_END_HOUR = 8

DEFAULT_PHASE_MINUTES = {"hot": 30, "focus": 60, "normal": 120,
                         "night": 240, "cold": 720}


def _parse_dt(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return None
    try:
        return datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def choose_phase(now: datetime, last_change: Optional[datetime]) -> str:
    """选择当前节奏档位（纯函数，便于自测）。夜间优先。"""
    if now.hour >= NIGHT_START_HOUR or now.hour < NIGHT_END_HOUR:
        return "night"
    if last_change is not None:
        age = now - last_change
        if age <= timedelta(hours=24):
            return "hot"
        if age >= timedelta(days=7):
            return "cold"
    return "normal"


def phase_minutes(cfg, phase: str) -> int:
    """读取某档位的间隔（分钟）；任何异常都回退默认值并夹取范围。"""
    phase = str(phase or "normal")
    default = int(DEFAULT_PHASE_MINUTES.get(phase, DEFAULT_PHASE_MINUTES["normal"]))
    raw = ""
    try:
        raw = str(cfg_mod.get(cfg, "app", "refresh_interval_" + phase, "")).strip()
    except Exception:
        raw = ""
    value = default
    if raw:
        try:
            value = int(float(raw))
        except Exception:
            value = default
    try:
        value = int(value)
    except Exception:
        value = default
    return max(MIN_INTERVAL_MIN, min(MAX_INTERVAL_MIN, value))


class RefreshEngine:
    """自动刷新调度器：后台线程定时执行 + 手动触发。"""

    def __init__(self, ctx: Any,
                 collector_factory: Optional[Callable[
                     [str], Optional[collectors.BaseCollector]]] = None) -> None:
        self._ctx = ctx
        self._factory = collector_factory or (
            lambda pf: collectors.get_collector(pf, ctx))
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._force = False
        self._run_lock = threading.Lock()
        self._last: Optional[Dict[str, Any]] = None
        self._phase = "normal"
        self._next_at: Optional[datetime] = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        if self.running():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="pricelens-refresh")
        self._thread.start()
        minutes, phase = self._interval()
        if collectors.mock_enabled():
            self._log("info", "自动刷新调度器已启动（模拟模式，PRICELENS_MOCK=1，不访问网络）")
        else:
            self._log("info", "自动刷新调度器已启动（当前节奏：%s，每 %s 分钟）",
                      str(phase), str(minutes))

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=3)
        self._thread = None

    def running(self) -> bool:
        return bool(self._thread is not None and self._thread.is_alive())

    # ---------- 节奏 ----------

    def _enabled(self) -> bool:
        """总开关（settings.refresh_enabled，默认开）。手动刷新不受影响。"""
        db = self._ctx.db
        if db is None:
            return False
        try:
            return str(db.get_setting("refresh_enabled", "1")).strip() != "0"
        except Exception:
            return True

    def _startup_enabled(self) -> bool:
        raw = str(cfg_mod.get(self._ctx.cfg, "app", "refresh_startup", "true"))
        return raw.strip().lower() not in ("0", "false", "no", "off", "")

    def compute_interval(self, now: datetime,
                         last_change: Optional[datetime]) -> Tuple[int, str]:
        phase = str(choose_phase(now, last_change))
        try:
            minutes = int(phase_minutes(self._ctx.cfg, phase))
        except Exception:
            minutes = int(DEFAULT_PHASE_MINUTES.get(
                phase, DEFAULT_PHASE_MINUTES["normal"]))
        return minutes, phase

    def _interval(self) -> Tuple[int, str]:
        last = None
        db = self._ctx.db
        if db is not None:
            try:
                last = _parse_dt(db.latest_change_at())
            except Exception:
                last = None
        minutes, phase = self.compute_interval(datetime.now(), last)
        try:
            minutes = int(minutes)
        except Exception:
            minutes = int(DEFAULT_PHASE_MINUTES.get(
                phase, DEFAULT_PHASE_MINUTES["normal"]))
        self._phase = str(phase)
        return minutes, str(phase)

    # ---------- 调度循环 ----------

    def _loop(self) -> None:
        delay = float(STARTUP_DELAY) if self._startup_enabled() \
            else float(self._interval()[0] * 60)
        while not self._stop.is_set():
            self._next_at = datetime.now() + timedelta(seconds=max(1.0, delay))
            self._wake.wait(timeout=max(1.0, delay))
            self._wake.clear()
            if self._stop.is_set():
                break
            force, self._force = self._force, False
            if force or self._enabled():
                try:
                    self.run_once("manual" if force else "schedule")
                except Exception as exc:
                    self._log("warning", "自动刷新运行异常：%s", exc)
            delay = float(self._interval()[0] * 60)

    def run_now(self) -> Dict[str, Any]:
        """请求立即刷新：调度器未启动时直接同步执行一次。"""
        if not self.running():
            return self.run_once("manual")
        self._force = True
        self._wake.set()
        return {"ok": True, "queued": True, "message": "已请求立即刷新"}

    # ---------- 挑商品 ----------

    def _eligible(self) -> List[Tuple[Dict[str, Any], collectors.BaseCollector]]:
        """可自动刷新的商品：在监控中 + 平台有可用采集器（增强模式 / 模拟）。"""
        db = self._ctx.db
        if db is None:
            return []
        try:
            items = db.list_items()
        except Exception:
            return []
        try:
            modes = cfg_mod.all_modes(self._ctx.cfg)
        except Exception:
            modes = {}
        mock = collectors.mock_enabled()
        out: List[Tuple[Dict[str, Any], collectors.BaseCollector]] = []
        for it in items:
            platform = str(it.get("platform") or "")
            if platform not in collectors.API_PLATFORMS:
                continue
            if not mock and modes.get(platform) != "enhanced":
                continue
            col = self._factory(platform)
            if col is None:
                continue
            out.append((it, col))
        return out

    # ---------- 执行一轮 ----------

    def run_once(self, trigger: str = "schedule") -> Dict[str, Any]:
        db = self._ctx.db
        if db is None:
            return {"ok": False, "total": 0, "message": "数据库尚未初始化"}
        if not self._run_lock.acquire(blocking=False):
            return {"ok": False, "busy": True, "total": 0,
                    "message": "已有一次刷新在进行中"}

        try:
            started_at = now_str()
            pairs = self._eligible()

            if not pairs:
                if collectors.mock_enabled():
                    hint = "没有可自动刷新的商品（模拟模式：仅监控中的拼多多 / 京东商品参与）"
                elif not collectors.adapters_ready():
                    hint = ("暂无可用采集器：真实接口将在 P3.3 接入；"
                            "想先体验可设置环境变量 PRICELENS_MOCK=1")
                else:
                    hint = "没有可自动刷新的商品（需：已填写密钥的平台商品）"
                finished_at = now_str()
                self._last = {"trigger": trigger, "started_at": started_at,
                              "finished_at": finished_at, "total": 0,
                              "checked": 0, "changed": 0, "new_low": 0,
                              "failed": 0, "unchanged": 0, "message": hint}
                self._log("info", "自动刷新：%s", hint)
                return {"ok": True, "total": 0, "changed": 0, "failed": 0,
                        "unchanged": 0, "new_low": 0, "checked": 0,
                        "started_at": started_at, "finished_at": finished_at,
                        "message": hint}

            checked = changed = failed = unchanged = new_low = 0
            for item, col in pairs:
                pk = int(item["id"])
                iid = str(item.get("item_id") or "")
                pname = str(item.get("platform") or "")

                try:
                    quote = col.fetch(item)
                    price = getattr(quote, "price", None)
                    if price is None or float(price) <= 0:
                        raise ValueError("采集器未返回有效价格")
                    price = round(float(price), 2)
                except Exception as exc:
                    failed += 1
                    msg = str(exc)[:200] or "未知错误"
                    db.touch_check(pk, now_str(), msg)
                    self._log("warning", "自动刷新失败[%s/%s]: %s", pname, iid, msg)
                    continue

                try:
                    last_row = db.latest_price(pk)
                    same = False
                    if last_row:
                        try:
                            same = abs(float(last_row["price"]) - price) < CHANGE_EPS
                        except Exception:
                            same = False
                    prev_min = db.item_stats(pk).get("min")
                    is_low = (prev_min is None) or (price < float(prev_min) - CHANGE_EPS)

                    if same:
                        unchanged += 1
                        line = "价格未变化（¥%.2f）" % price
                    else:
                        db.add_price(pk, price, captured_at=now_str(),
                                     source=API_SOURCE,
                                     note=getattr(quote, "note", "") or "",
                                     list_price=getattr(quote, "list_price", None),
                                     coupon=getattr(quote, "coupon", None))
                        changed += 1
                        if is_low:
                            new_low += 1
                        line = ("已记录 ¥%.2f" % price) + ("（新低）" if is_low else "")
                    db.touch_check(pk, now_str(), "")
                    checked += 1
                    self._log("info", "自动刷新[%s/%s]: %s", pname, iid, line)
                except Exception as exc:
                    failed += 1
                    db.touch_check(pk, now_str(), str(exc)[:200])
                    self._log("warning", "自动刷新入库失败[%s/%s]: %s", pname, iid, exc)

            finished_at = now_str()
            total = len(pairs)
            message = (f"共 {total} 个：检查成功 {checked}，价格变化 {changed}，"
                       f"新低 {new_low}，失败 {failed}")
            try:
                db.log_refresh_run(trigger=trigger, started_at=started_at,
                                   finished_at=finished_at, total=total,
                                   ok=checked, changed=changed, new_low=new_low,
                                   failed=failed, message=message)
            except Exception as exc:
                self._log("warning", "刷新日志写入失败：%s", exc)

            self._last = {"trigger": trigger, "started_at": started_at,
                          "finished_at": finished_at, "total": total,
                          "checked": checked, "changed": changed,
                          "new_low": new_low, "failed": failed,
                          "unchanged": unchanged, "message": message}
            self._log("info", "自动刷新完成（%s）：%s", trigger, message)
            return {"ok": True, "busy": False, "trigger": trigger, "total": total,
                    "checked": checked, "changed": changed, "unchanged": unchanged,
                    "new_low": new_low, "failed": failed,
                    "started_at": started_at, "finished_at": finished_at,
                    "message": message}
        finally:
            self._run_lock.release()

    # ---------- 状态 / 日志 ----------

    def status(self) -> Dict[str, Any]:
        try:
            minutes, phase = self._interval()
        except Exception:
            minutes, phase = 0, self._phase
        return {
            "enabled": self._enabled(),
            "running": self.running(),
            "busy": self._run_lock.locked(),
            "mock": collectors.mock_enabled(),
            "phase": phase,
            "interval_minutes": int(minutes),
            "next_at": self._next_at.strftime("%H:%M:%S") if self._next_at else "",
            "last": dict(self._last) if self._last else None,
        }

    def _log(self, level: str, fmt: str, *args) -> None:
        lg = getattr(self._ctx, "log", None)
        if lg is None:
            return
        try:
            getattr(lg, level)(fmt, *args)
        except Exception:
            pass