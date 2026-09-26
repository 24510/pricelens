# -*- coding: utf-8 -*-
"""自动刷新界面桥接自测（P3.2）：临时目录 + 假采集器，不访问网络。

覆盖：
  · get_refresh_info：未启动调度器 / 运行中 / 节奏与间隔 / 最近轮次 / last 汇总
  · set_refresh_enabled：开关写入、字符串兼容、暂停状态显示
  · refresh_now：排队触发、手动执行完成、暂停时仍可手动跑
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import collectors                                   # noqa: E402
import config as cfg_mod                            # noqa: E402
from app_context import AppContext                  # noqa: E402
from refresh import RefreshEngine                   # noqa: E402
from ui.bridge import Bridge                        # noqa: E402

PASS = []
FAIL = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  → " + str(extra)) if extra else ""))


class FakePdd(collectors.BaseCollector):
    platform = "pdd"
    name = "假采集器"

    def __init__(self, ctx=None):
        super().__init__(ctx)
        self.queues = {}

    def feed(self, item_id, *values):
        self.queues.setdefault(str(item_id), []).extend(values)

    def fetch(self, item):
        q = self.queues.get(str(item.get("item_id") or ""))
        if not q:
            raise RuntimeError("假采集器：没有新数据")
        v = q.pop(0)
        if isinstance(v, Exception):
            raise v
        return collectors.Quote(price=float(v), note="自测")


def wait_run_count(db, n, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        runs = db.recent_refresh_runs(20)
        if len(runs) >= n:
            return runs
        time.sleep(0.2)
    return db.recent_refresh_runs(20)


def main():
    print("=== PriceLens 自动刷新（界面桥接）自测：临时数据，不访问网络 ===")
    root = Path(tempfile.mkdtemp(prefix="pricelens_refresh_ui_"))
    ctx = None
    engine = None
    try:
        ctx = AppContext()
        ctx.init_at(root, start_api=False, start_refresh=False)
        bridge = Bridge(ctx)
        db = ctx.db
        check("临时环境初始化", db is not None)

        a = db.add_item("pdd", "872234708625", title="商品A")["item"]
        b = db.add_item("pdd", "999900001111", title="商品B")["item"]

        cfg = cfg_mod.load(root / "config")
        cfg_mod.set_value(cfg, "pdd", "client_id", "t")
        cfg_mod.set_value(cfg, "pdd", "client_secret", "t")
        cfg_mod.save(cfg, root / "config")
        ctx.cfg = cfg_mod.load(root / "config")

        info = bridge.get_refresh_info()
        check("get_refresh_info 可用（未启动调度器）",
              info.get("ok") and info["status"]["running"] is False,
              info.get("status"))
        check("返回采集器状态字段",
              ("collectors_ready" in info) and ("mock" in info))

        # 挂载假采集器引擎（先建对象，避免把默认引擎拉起来）
        fake = FakePdd(ctx)
        fake.feed("872234708625", 10.0)
        fake.feed("999900001111", 20.0)
        engine = RefreshEngine(ctx, collector_factory=lambda pf: fake if pf == "pdd" else None)
        ctx.refresh = engine

        res = bridge.set_refresh_enabled(False)
        check("set_refresh_enabled(False) 写入成功",
              res.get("ok") and db.get_setting("refresh_enabled") == "0", res)
        res = bridge.set_refresh_enabled(True)
        check("set_refresh_enabled(True) 写入成功",
              res.get("ok") and db.get_setting("refresh_enabled") == "1")

        engine.start()
        check("调度器（假采集器）已启动", engine.running())

        info = bridge.get_refresh_info()
        check("状态显示运行中", info["status"]["running"] is True)
        check("节奏与间隔已返回",
              bool(info["status"]["phase"]) and int(info["status"]["interval_minutes"]) >= 1,
              info["status"])

        res = bridge.refresh_now()
        check("refresh_now 返回已排队", res.get("ok") and res.get("queued"), res)
        runs = wait_run_count(db, 1)
        check("手动触发完成一轮（写入 refresh_runs）", len(runs) >= 1, len(runs))
        if runs:
            r = runs[0]
            check("首轮结果：2 个商品 / 2 条变化 / 2 个新低",
                  int(r["total"]) == 2 and int(r["changed"]) == 2
                  and int(r["new_low"]) == 2 and int(r["failed"]) == 0, dict(r))
            check("触发标记为 manual", str(r["trigger"]) == "manual", r["trigger"])

        time.sleep(0.5)
        info = bridge.get_refresh_info()
        check("界面数据包含最近轮次",
              bool(info.get("runs")) and len(info["runs"]) >= 1)
        check("status.last 与轮次一致", bool(info["status"].get("last")))

        # 暂停状态下：手动刷新仍可执行
        bridge.set_refresh_enabled(False)
        fake.feed("999900001111", 5.0)
        res = bridge.refresh_now()
        check("暂停时仍可手动触发", res.get("ok") and res.get("queued"), res)
        runs = wait_run_count(db, 2)
        check("第二轮：1 条变化",
              len(runs) >= 2 and int(runs[0]["changed"]) == 1,
              dict(runs[0]) if runs else "")
        info = bridge.get_refresh_info()
        check("状态显示已暂停", info["status"]["enabled"] is False,
              info["status"].get("enabled"))
        check("暂停不影响结果记录", str(runs[0]["trigger"]) == "manual")

        res = bridge.set_refresh_enabled("1")
        check("字符串开关值兼容",
              res.get("ok") and db.get_setting("refresh_enabled") == "1")
    finally:
        if engine is not None:
            engine.stop()
        if ctx is not None:
            ctx.stop_refresh()
            ctx.stop_api()
            ctx.close()
        shutil.rmtree(root, ignore_errors=True)

    print()
    total = len(PASS) + len(FAIL)
    if FAIL:
        print(f"未通过 {len(FAIL)}/{total}：")
        for name in FAIL:
            print("  - " + name)
        return 1
    print(f"全部通过：{total}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())