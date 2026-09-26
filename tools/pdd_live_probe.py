# -*- coding: utf-8 -*-
"""拼多多线上连通性探测（P3.4 验收第一步）。

直接读取 PriceLensData 里的配置，对多多进宝线上接口发 2~4 次真实请求，
一步一步打印结果：哪一层出问题，一眼就能看到。

步骤：
  1) 读取并检查密钥（client_id / client_secret / pid）；
  2) 搜索接口：keyword=商品数字ID → 尝试换算 goods_sign；
  3) 详情接口：用 goods_sign 取价格（分 → 元）；
  4) 结论（必要时用关键词搜索兜底，区分「商品未参团」与「密钥/权限问题」）。

用法：
  .venv\\Scripts\\python.exe tools\\pdd_live_probe.py
  .venv\\Scripts\\python.exe tools\\pdd_live_probe.py 123456789012

说明：只读配置、不写任何数据；会访问拼多多线上接口（2~4 次请求）。
     数据目录默认 PriceLensData，可用环境变量 PRICELENS_DATA_DIR 指定。
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config as cfg_mod                                    # noqa: E402
from collectors.adapters import pdd as pdd_mod              # noqa: E402
from collectors.adapters.pdd import PddCollector            # noqa: E402

DEFAULT_GOODS = "872234708625"
FALLBACK_KEYWORDS = ("抽纸", "手机壳")


def mask(value, head: int = 6, tail: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return "（空）"
    if len(text) <= head + tail:
        return text[:2] + "***"
    return text[:head] + "…" + text[-tail:]


class MiniCtx:
    """探针用最小上下文：只带配置，不带数据库（不写任何数据）。"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.db = None
        self.log = None


def find_data_root() -> Path:
    env = str(os.environ.get("PRICELENS_DATA_DIR") or "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(Path.cwd() / "PriceLensData")
    candidates.append(ROOT / "PriceLensData")
    for base in candidates:
        if (base / "config" / "config.ini").is_file():
            return base
    return candidates[0]


def main() -> int:
    goods = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOODS).strip()
    print("=== PriceLens · 拼多多线上探测 ===")
    print("时间:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    data_root = find_data_root()
    cfg_dir = data_root / "config"
    print("数据目录:", data_root)
    print()

    # ---------- 1) 配置 ----------
    print("[1/4] 读取配置 …")
    try:
        cfg = cfg_mod.load(cfg_dir)
    except Exception as exc:
        print("  ❌ 读取配置失败：%s" % exc)
        print("  → 确认程序至少启动过一次；或先打开程序保存一次密钥。")
        return 1

    client_id = str(cfg_mod.get(cfg, "pdd", "client_id") or "").strip()
    client_secret = str(cfg_mod.get(cfg, "pdd", "client_secret") or "").strip()
    pid = str(cfg_mod.get(cfg, "pdd", "pid") or "").strip()

    print("  client_id    :", mask(client_id))
    print("  client_secret:", ("已填（长度 %d）" % len(client_secret)) if client_secret else "（空）")
    print("  pid          :", pid if pid else "（空，可选）")
    if not client_id or not client_secret:
        print("  ❌ 缺少 client_id 或 client_secret。")
        print("  → 打开程序 →「🔑 密钥设置」→ 拼多多区块填好后保存，再跑本探测。")
        return 1
    print("  ✅ 关键密钥已就位")
    print()

    ctx = MiniCtx(cfg)
    collector = PddCollector(ctx)

    def call(api: str, params: dict):
        """统一调用：返回 (数据, 毫秒, 错误文本)。"""
        started = time.time()
        try:
            data = collector._call(api, params, client_id, client_secret)
            return data, int((time.time() - started) * 1000), ""
        except Exception as exc:
            return None, int((time.time() - started) * 1000), str(exc)

    sign = ""
    search_error = ""
    search_count = 0

    # ---------- 2) 按数字ID搜索 ----------
    print("[2/4] 搜索接口：把数字ID换成 goods_sign …")
    print("      keyword =", goods)
    data, ms, err = call(pdd_mod.API_SEARCH, {"keyword": goods, "pid": pid or None})
    if err:
        search_error = err
        print("  ❌ 失败（%dms）：%s" % (ms, err))
    else:
        resp = data.get("goods_search_response") or {}
        goods_list = resp.get("goods_list") or []
        search_count = len(goods_list)
        print("  ✅ 成功（%dms），返回 %d 条" % (ms, search_count))
        hit = None
        for entry in goods_list:
            if str(entry.get("goods_id") or "") == goods:
                hit = entry
                break
        if hit is None and len(goods_list) == 1:
            hit = goods_list[0]
        if hit is not None:
            sign = str(hit.get("goods_sign") or "").strip()
            print("  命中商品：")
            print("    名称      :", str(hit.get("goods_name") or "（未返回）")[:48])
            print("    goods_sign:", mask(sign, 10, 6))
            price = pdd_mod.fen_to_yuan(hit.get("min_group_price"))
            if price is not None:
                print("    团购价    : ¥%.2f（搜索结果附带）" % price)
        else:
            print("  ⚠️ 结果里没有该商品（可能未参加多多进宝推广）")
    print()
    time.sleep(0.4)

    # ---------- 3) 详情 ----------
    detail_ok = False
    detail_error = ""
    if sign:
        print("[3/4] 详情接口：用 goods_sign 取价 …")
        data, ms, err = call(pdd_mod.API_DETAIL,
                             {"goods_sign": sign, "pid": pid or None})
        if err:
            detail_error = err
            print("  ❌ 失败（%dms）：%s" % (ms, err))
        else:
            resp = data.get("goods_detail_response") or {}
            details = resp.get("goods_details") or []
            target = None
            for entry in details:
                if str(entry.get("goods_sign") or "") == sign:
                    target = entry
                    break
            if target is None and len(details) == 1:
                target = details[0]
            if target is None:
                detail_error = "详情返回里没有匹配商品"
                print("  ⚠️ 返回 %d 条，但没有匹配的商品" % len(details))
            else:
                group = pdd_mod.fen_to_yuan(target.get("min_group_price"))
                normal = pdd_mod.fen_to_yuan(target.get("min_normal_price"))
                coupon = pdd_mod.fen_to_yuan(target.get("coupon_discount"))
                print("  ✅ 成功（%dms）：" % ms)
                print("    名称      :", str(target.get("goods_name") or "（未返回）")[:48])
                if group is not None:
                    print("    团购价    : ¥%.2f" % group)
                if normal is not None:
                    print("    单买价    : ¥%.2f" % normal)
                if coupon is not None:
                    print("    优惠券    : ¥%.2f" % coupon)
                detail_ok = (group is not None) or (normal is not None)
                if not detail_ok:
                    detail_error = "接口未返回有效价格字段"
        print()
        time.sleep(0.4)

    # ---------- 4) 结论 ----------
    print("[4/4] 结论")

    if detail_ok:
        print("===== 结论 =====")
        print("✅ 链路全通：配置 → 签名 → 搜索换算 → 详情取价 全部正常。")
        print("→ 现在回到程序，点「立即刷新全部」就能自动刷新了。")
        print("================")
        return 0

    if sign and detail_error:
        print("===== 结论 =====")
        print("搜索与换算正常，但详情接口这一步没通过：")
        print("  ", detail_error[:200])
        print("→ 可能：goods_sign 刚好过期（程序会自动重取一次）；或详情接口权限未生效。")
        print("→ 建议：回程序点「立即刷新全部」再试一次；仍失败就把本页输出发我。")
        print("================")
        return 1

    # 没拿到 goods_sign：用关键词兜底，区分两类问题
    print("      兜底验证：换关键词搜索，判断是「商品未参团」还是「密钥/权限问题」…")
    fallback_ok = False
    fallback_error = ""
    for keyword in FALLBACK_KEYWORDS:
        print("      keyword =", keyword)
        data, ms, err = call(pdd_mod.API_SEARCH,
                             {"keyword": keyword, "pid": pid or None, "page_size": "10"})
        if err:
            fallback_error = err
            print("  ❌ 失败（%dms）：%s" % (ms, err))
            break
        goods_list = (data.get("goods_search_response") or {}).get("goods_list") or []
        print("  ✅ 成功（%dms），返回 %d 条" % (ms, len(goods_list)))
        if goods_list:
            first = goods_list[0]
            print("    样例商品  :", str(first.get("goods_name") or "")[:40])
            print("    goods_sign:", mask(str(first.get("goods_sign") or ""), 10, 6))
            fallback_ok = True
            break
        time.sleep(0.4)
    print()

    print("===== 结论 =====")
    if fallback_ok and search_error:
        print("搜索接口本身可用（关键词能搜到商品），但按商品ID搜索失败：")
        print("  ", search_error[:160])
        print("→ 该商品可能未参加多多进宝，或 ID 不是商品链接里的数字 ID。")
        print("→ 建议：换一款参加推广的商品再试（或继续用浏览器脚本采集它）。")
    elif fallback_ok and not search_error:
        print("网络、密钥、签名均正常 ✅")
        print("→ 但商品「%s」不在多多进宝推广计划内（官方接口查不到，属正常现象）。" % goods)
        print("→ 换一款参加了推广的商品即可自动刷新；这款继续用浏览器脚本采集。")
    elif fallback_error:
        print("搜索接口也被拒绝，问题更可能在密钥或应用权限：")
        print("  ", fallback_error[:200])
        print("→ 检查「密钥设置」里的 client_secret 是否完整（注意首尾不要有空格）。")
        print("→ 到开放平台确认：应用类型是多多客/多多进宝，且应用已通过审核。")
    else:
        print("关键词搜索没有返回商品，暂时无法进一步判断。")
        print("→ 把本页完整输出发我即可。")
    print("================")
    return 1 if not (fallback_ok and not search_error) else 0


if __name__ == "__main__":
    sys.exit(main())