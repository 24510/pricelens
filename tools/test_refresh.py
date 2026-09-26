# -*- coding: utf-8 -*-
"""自动刷新自测：临时目录 + 假采集器，不访问网络、不影响真实数据。

覆盖：
  · 参与范围（只认增强模式平台的商品；淘宝 / 未配置密钥的平台不参与）
  · 首次入库 / 未变化跳过 / 变化入库 / 新低统计
  · 采集失败记录（last_check_error），不拖垮其他商品
  · refresh_runs 运行日志汇总
  · 节奏选择（夜间 / 热 / 冷 / 常规）
  · 总开关（refresh_enabled）与模拟采集器开关
"""
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import collectors                                   # noqa: E402
import config as cfg_mod                            # noqa: E402
from app_context import AppContext                  # noqa: E402
from refresh import RefreshEngine, choose_phase, phase_minutes  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  → " + str(extra)) if extra else ""))


class FakePdd(collectors.BaseCollector):
    """按 item_id 出牌的假采集器：数字 = 价格；Exception = 抛错。"""

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


def main():
    print("=== PriceLens 自动刷新自测（临时数据，不访问网络） ===")
    root = Path(tempfile.mkdtemp(prefix="pricelens_refresh_test_"))
    ctx = None
    engine = None
    try:
        ctx = AppContext()
        ctx.init_at(root, start_api=False, start_refresh=False)
        check("临时环境初始化", ctx.db is not None)

        db = ctx.db
        a = db.add_item("pdd", "872234708625", title="拼多多商品A")["item"]
        b = db.add_item("pdd", "999900001111", title="拼多多商品B")["item"]
        c = db.add_item("jd", "100012043978", title="京东商品C")["item"]
        d = db.add_item("tb", "654321000", title="淘宝商品D")["item"]

        fake = FakePdd(ctx)
        fake_jd = FakePdd(ctx)
        factory = lambda pf: {"pdd": fake, "jd": fake_jd}.get(pf)
        engine = RefreshEngine(ctx, collector_factory=factory)
        check("引擎创建", engine is not None)

        # 1) 未配置密钥 → 无可刷新商品
        res = engine.run_once("test")
        check("未配置密钥时不刷新任何商品", res.get("total") == 0 and res.get("ok"))

        # 2) 填入 pdd 密钥 → 参与刷新的只有两个 pdd 商品
        cfg = cfg_mod.load(root / "config")
        cfg_mod.set_value(cfg, "pdd", "client_id", "test-client")
        cfg_mod.set_value(cfg, "pdd", "client_secret", "test-secret")
        cfg_mod.save(cfg, root / "config")
        ctx.cfg = cfg_mod.load(root / "config")

        eligible = engine._eligible()
        ids = sorted(int(x[0]["id"]) for x in eligible)
        check("增强模式平台商品参与刷新", len(eligible) == 2, len(eligible))
        check("京东（未填密钥）与淘宝不参与",
              int(c["id"]) not in ids and int(d["id"]) not in ids, ids)

        # 3) 首次运行：两条入库、均记新低
        fake.feed("872234708625", 10.0, 10.0, 8.0)
        fake.feed("999900001111", 20.0, 25.0)
        r1 = engine.run_once("test")
        check("首次运行：写入 2 条、新低 2",
              r1.get("changed") == 2 and r1.get("new_low") == 2
              and r1.get("failed") == 0, r1)

        rows_a = db.list_prices(int(a["id"]))
        check("记录来源=api、备注=自测",
              len(rows_a) == 1 and rows_a[0]["source"] == "api"
              and rows_a[0]["note"] == "自测", rows_a[:1])

        # 4) 第二次运行：A 未变化（跳过）、B 变化（入库）
        r2 = engine.run_once("test")
        check("未变化跳过、变化入库",
              r2.get("changed") == 1 and r2.get("unchanged") == 1
              and r2.get("failed") == 0, r2)
        check("未变化不产生新行", len(db.list_prices(int(a["id"]))) == 1)
        check("最后检查时间已更新",
              bool(db.get_item(int(a["id"])).get("last_check_at")))

        # 5) 第三次运行：A 创新低；B 采集失败
        fake.feed("999900001111", RuntimeError("测试：接口超时"))
        r3 = engine.run_once("test")
        check("新低计数", r3.get("new_low") == 1 and r3.get("changed") == 1, r3)
        check("失败被记录且不影响其他商品", r3.get("failed") == 1, r3)
        item_b = db.get_item(int(b["id"]))
        check("失败原因写入商品状态",
              "接口超时" in str(item_b.get("last_check_error") or ""))
        st = db.item_stats(int(a["id"]))
        check("最低价已更新为 8.0", abs(float(st["min"]) - 8.0) < 1e-6, st)

        # 6) 运行日志
        runs = db.recent_refresh_runs(10)
        check("refresh_runs 已记录 3 轮", len(runs) == 3, len(runs))
        last = runs[0]
        check("最近一轮汇总正确",
              int(last["total"]) == 2 and int(last["changed"]) == 1
              and int(last["failed"]) == 1, dict(last))
        check("时间段与批次信息完整",
              bool(last["started_at"]) and bool(last["finished_at"])
              and str(last["trigger"]) == "test")

        # 7) 节奏选择（纯函数）
        noon = datetime(2026, 9, 26, 22, 0, 0)
        check("热：24 小时内有变化 → hot",
              choose_phase(noon, noon - timedelta(hours=2)) == "hot")
        check("常规：无最近变化 → normal", choose_phase(noon, None) == "normal")
        check("冷：7 天以上无变化 → cold",
              choose_phase(noon, noon - timedelta(days=10)) == "cold")
        check("夜间优先 → night",
              choose_phase(datetime(2026, 9, 26, 1, 0),
                           noon - timedelta(hours=1)) == "night")
        m_hot = phase_minutes(ctx.cfg, "hot")
        check("间隔读取配置（hot=30 分钟）", m_hot == 30, m_hot)

        # 8) 总开关与模拟采集器
        db.set_setting("refresh_enabled", "0")
        check("总开关可关闭", engine._enabled() is False)
        db.set_setting("refresh_enabled", "1")
        check("总开关可恢复", engine._enabled() is True)

        os.environ["PRICELENS_MOCK"] = "1"
        m1 = collectors.get_collector("pdd", ctx)
        check("模拟开关：pdd 返回模拟采集器",
              m1 is not None and m1.__class__.__name__ == "MockCollector")
        m2 = collectors.get_collector("tb", ctx)
        check("模拟模式不影响淘宝（恒不参与）", m2 is None)
        del os.environ["PRICELENS_MOCK"]
        m3 = collectors.get_collector("pdd", ctx)
        check("关闭模拟后不再返回模拟采集器",
              m3 is None or m3.__class__.__name__ != "MockCollector")

        # 9) 补填京东密钥 → 即刻纳入（无需重启）
        cfg2 = cfg_mod.load(root / "config")
        cfg_mod.set_value(cfg2, "jd", "app_key", "k")
        cfg_mod.set_value(cfg2, "jd", "app_secret", "s")
        cfg_mod.save(cfg2, root / "config")
        ctx.cfg = cfg_mod.load(root / "config")
        eligible2 = engine._eligible()
        check("补填京东密钥后商品被纳入", len(eligible2) == 3, len(eligible2))
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