# -*- coding: utf-8 -*-
"""拼多多采集器自测（P3.3a）：本机假网关，不访问外网、不需要真实密钥。

覆盖：
  · 数字 ID → goods_sign 换算（搜索接口）与缓存复用
  · 字符型 ID（goods_sign）直查
  · 价格 / 划线价 / 优惠券解析（分 → 元）
  · 错误路径：未配置密钥 / 搜索无果 / 接口报错 / HTTP 500 / 非 JSON / 超时
  · 缓存自愈：goods_sign 失效后自动重取再试
  · 与调度器集成：RefreshEngine 跑一轮，写入 source=api 记录
"""
import hashlib
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import collectors                                    # noqa: E402
import config as cfg_mod                             # noqa: E402
from app_context import AppContext                   # noqa: E402
from collectors.adapters.pdd import PddCollector     # noqa: E402
from refresh import RefreshEngine                    # noqa: E402

SECRET = "test-secret-0001"
CID = "cid_test_0001"
PID = "1234567_89101112"

PASS = []
FAIL = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  → " + str(extra)) if extra else ""))


# ---------------- 本机假网关 ----------------

def make_fake_gateway(secret=SECRET):
    store = {"requests": [], "responder": None}

    def _recompute(params):
        joined = "".join(str(k) + str(params[k]) for k in sorted(params))
        return hashlib.md5((secret + joined + secret).encode("utf-8")).hexdigest().upper()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            params = {k: v[0] for k, v in
                      urllib.parse.parse_qs(raw, keep_blank_values=True).items()}
            received = params.pop("sign", "")
            store["requests"].append(
                {"type": params.get("type", ""), "params": dict(params),
                 "sign_ok": received == _recompute(params)})

            responder = store["responder"]
            payload = responder(store["requests"][-1]["type"], params) \
                if responder else None
            if payload is None:
                payload = {"error_response": {"error_code": 9, "error_msg": "no responder"}}

            status = 200
            if isinstance(payload, tuple) and payload and payload[0] == "http":
                status = int(payload[1])
                data = str(payload[2]).encode("utf-8")
            elif isinstance(payload, tuple) and payload and payload[0] == "raw":
                data = str(payload[1]).encode("utf-8")
            else:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    store["url"] = f"http://127.0.0.1:{port}/api/router"
    return server, store


def search_payload(goods_id="872234708625", sign="ESIGN_FROM_SEARCH", name="测试商品"):
    try:
        gid = int(goods_id)
    except Exception:
        gid = goods_id
    return {"goods_search_response": {"goods_list": [
        {"goods_id": gid, "goods_sign": sign, "goods_name": name}]}}


def detail_payload(sign, group=990, normal=1290, coupon=100, name="测试商品"):
    goods = {"goods_sign": sign, "goods_name": name,
             "min_group_price": group, "min_normal_price": normal}
    if coupon:
        goods["coupon_discount"] = coupon
    return {"goods_detail_response": {"goods_details": [goods]}}


def main():
    print("=== PriceLens 拼多多采集器自测（假网关，不访问外网） ===")
    root = Path(tempfile.mkdtemp(prefix="pricelens_pdd_test_"))
    ctx = None
    server = None
    engine = None
    try:
        ctx = AppContext()
        ctx.init_at(root, start_api=False, start_refresh=False)
        db = ctx.db
        check("临时环境初始化", db is not None)

        item_a = db.add_item("pdd", "872234708625", title="拼多多商品A")["item"]

        cfg = cfg_mod.load(root / "config")
        cfg_mod.set_value(cfg, "pdd", "client_id", CID)
        cfg_mod.set_value(cfg, "pdd", "client_secret", SECRET)
        cfg_mod.set_value(cfg, "pdd", "pid", PID)
        cfg_mod.save(cfg, root / "config")
        ctx.cfg = cfg_mod.load(root / "config")

        server, store = make_fake_gateway()
        adapter = PddCollector(ctx, endpoint=store["url"], timeout=3.0)
        check("采集器构造（测试网关可覆盖）",
              getattr(adapter, "_endpoint", "") == store["url"])

        os.environ["PRICELENS_PDD_ENDPOINT"] = store["url"]
        try:
            env_adapter = PddCollector(ctx)
            check("环境变量可覆盖网关",
                  getattr(env_adapter, "_endpoint", "") == store["url"])
        finally:
            os.environ.pop("PRICELENS_PDD_ENDPOINT", None)

        # ---- 未配置密钥提示 ----
        cfg_blank = cfg_mod.load(root / "config")
        cfg_mod.set_value(cfg_blank, "pdd", "client_id", "")
        cfg_mod.save(cfg_blank, root / "config")
        ctx.cfg = cfg_mod.load(root / "config")
        message = ""
        try:
            adapter.fetch(item_a)
        except Exception as exc:
            message = str(exc)
        check("未配置密钥时给出明确提示", "未配置" in message, message)
        cfg_back = cfg_mod.load(root / "config")
        cfg_mod.set_value(cfg_back, "pdd", "client_id", CID)
        cfg_mod.save(cfg_back, root / "config")
        ctx.cfg = cfg_mod.load(root / "config")

        def standard_responder(api_type, params):
            if api_type == "pdd.ddk.goods.search":
                return search_payload(goods_id=str(params.get("keyword") or ""),
                                      sign="ESIGN_FROM_SEARCH")
            if api_type == "pdd.ddk.goods.detail":
                return detail_payload(sign=str(params.get("goods_sign") or ""))
            return {"error_response": {"error_code": 1, "error_msg": "未知接口"}}

        store["responder"] = standard_responder

        # ---- 数字 ID：换算 + 详情 ----
        store["requests"].clear()
        quote = adapter.fetch(item_a)
        check("数字 ID 采集成功：价格 9.90", abs(quote.price - 9.90) < 1e-9, quote.price)
        check("划线价（min_normal_price）→ 12.90",
              quote.list_price is not None and abs(quote.list_price - 12.90) < 1e-9)
        check("优惠券（coupon_discount）→ 1.00",
              quote.coupon is not None and abs(quote.coupon - 1.00) < 1e-9)
        check("备注标记「多多进宝」", quote.note == "多多进宝", quote.note)

        types = [r["type"] for r in store["requests"]]
        check("先经搜索接口换算 goods_sign",
              types[:1] == ["pdd.ddk.goods.search"], types)
        check("随后调用详情接口取价",
              types == ["pdd.ddk.goods.search", "pdd.ddk.goods.detail"], types)

        req_search = store["requests"][0]["params"]
        req_detail = store["requests"][1]["params"]
        check("搜索请求 keyword=数字ID",
              req_search.get("keyword") == "872234708625")
        check("详情请求携带换算后的 goods_sign",
              req_detail.get("goods_sign") == "ESIGN_FROM_SEARCH")
        check("两次请求均携带配置的 pid",
              req_search.get("pid") == PID and req_detail.get("pid") == PID)
        check("client_id 正确",
              req_search.get("client_id") == CID and req_detail.get("client_id") == CID)
        ts = str(req_detail.get("timestamp") or "")
        check("timestamp 为合理时间戳",
              ts.isdigit() and abs(int(ts) - int(time.time())) < 120, ts)
        check("两次请求签名校验通过",
              all(r["sign_ok"] for r in store["requests"]))
        check("goods_sign 已写入缓存",
              db.get_setting("pdd_sign:872234708625") == "ESIGN_FROM_SEARCH")

        # ---- 缓存复用 ----
        store["requests"].clear()
        quote2 = adapter.fetch(item_a)
        types2 = [r["type"] for r in store["requests"]]
        check("二次采集复用缓存（不再搜索）",
              types2 == ["pdd.ddk.goods.detail"], types2)
        check("复用路径价格一致", abs(quote2.price - 9.90) < 1e-9)

        # ---- 字符型 ID 直查 ----
        item_b = db.add_item("pdd", "ESIGN_DIRECT_XYZ", title="直查商品B")["item"]
        store["requests"].clear()
        quote3 = adapter.fetch(item_b)
        req_types = [r["type"] for r in store["requests"]]
        check("字符型 ID 直查（无搜索请求）",
              req_types == ["pdd.ddk.goods.detail"], req_types)
        check("直查请求携带原样 goods_sign",
              store["requests"][0]["params"].get("goods_sign") == "ESIGN_DIRECT_XYZ")
        check("直查价格解析正确", abs(quote3.price - 9.90) < 1e-9)

        # ---- 搜索无匹配 ----
        item_c = db.add_item("pdd", "777766665555", title="无果商品C")["item"]

        def responder_two_unmatched(api_type, params):
            if api_type == "pdd.ddk.goods.search":
                return {"goods_search_response": {"goods_list": [
                    {"goods_id": 111, "goods_sign": "S1"},
                    {"goods_id": 222, "goods_sign": "S2"}]}}
            return detail_payload(sign=str(params.get("goods_sign") or ""))

        store["responder"] = responder_two_unmatched
        store["requests"].clear()
        message = ""
        try:
            adapter.fetch(item_c)
        except Exception as exc:
            message = str(exc)
        check("搜索无匹配时明确报错", "未能从搜索接口找到该商品" in message, message)
        check("失败时不再调用详情接口",
              [r["type"] for r in store["requests"]] == ["pdd.ddk.goods.search"])

        # ---- 单条结果兜底 ----
        def responder_single(api_type, params):
            if api_type == "pdd.ddk.goods.search":
                return {"goods_search_response": {"goods_list": [
                    {"goods_id": 999999, "goods_sign": "ESIGN_SINGLE"}]}}
            return detail_payload(sign=str(params.get("goods_sign") or ""))

        store["responder"] = responder_single
        quote4 = adapter.fetch(item_c)
        check("单条结果兜底换算成功",
              abs(quote4.price - 9.90) < 1e-9
              and db.get_setting("pdd_sign:777766665555") == "ESIGN_SINGLE")

        # ---- 接口报错 ----
        def responder_detail_error(api_type, params):
            if api_type == "pdd.ddk.goods.detail":
                return {"error_response": {"error_code": 40001,
                                           "error_msg": "goods_sign 无效"}}
            return {"error_response": {"error_code": 1, "error_msg": "未知接口"}}

        store["responder"] = responder_detail_error
        message = ""
        try:
            adapter.fetch(item_b)
        except Exception as exc:
            message = str(exc)
        check("接口报错原样透出（含错误码）",
              "40001" in message and "goods_sign 无效" in message, message)

        # ---- 缓存自愈 ----
        def responder_selfheal(api_type, params):
            if api_type == "pdd.ddk.goods.search":
                return search_payload(goods_id=str(params.get("keyword") or ""),
                                      sign="ESIGN_FRESH")
            if api_type == "pdd.ddk.goods.detail":
                if str(params.get("goods_sign")) == "ESIGN_FROM_SEARCH":
                    return {"error_response": {"error_code": 40001,
                                               "error_msg": "goods_sign 已失效，请重新获取"}}
                return detail_payload(sign=str(params.get("goods_sign") or ""))
            return {"error_response": {"error_code": 1, "error_msg": "未知接口"}}

        store["responder"] = responder_selfheal
        store["requests"].clear()
        quote5 = adapter.fetch(item_a)
        check("缓存失效自愈：自动重取并成功",
              abs(quote5.price - 9.90) < 1e-9, quote5.price)
        check("自愈后缓存已更新",
              db.get_setting("pdd_sign:872234708625") == "ESIGN_FRESH")
        seq = [r["type"] for r in store["requests"]]
        check("自愈时序：detail → search → detail",
              seq == ["pdd.ddk.goods.detail", "pdd.ddk.goods.search",
                      "pdd.ddk.goods.detail"], seq)

        # ---- HTTP 500 / 非 JSON / 超时 ----
        store["responder"] = lambda t, p: ("http", 500, "boom")
        message = ""
        try:
            adapter.fetch(item_b)
        except Exception as exc:
            message = str(exc)
        check("HTTP 500 报错可读", "网络错误" in message and "500" in message, message)

        store["responder"] = lambda t, p: ("raw", "<html>gateway error</html>")
        message = ""
        try:
            adapter.fetch(item_b)
        except Exception as exc:
            message = str(exc)
        check("非 JSON 返回报错可读", "无法解析" in message, message)

        def responder_slow(t, p):
            time.sleep(1.2)
            return detail_payload(sign=str(p.get("goods_sign") or ""))

        store["responder"] = responder_slow
        slow_adapter = PddCollector(ctx, endpoint=store["url"], timeout=0.4)
        message = ""
        try:
            slow_adapter.fetch(item_b)
        except Exception as exc:
            message = str(exc)
        check("请求超时报错可读", "网络错误" in message, message)

        # ---- 集成：调度器一轮 ----
        def responder_e2e(api_type, params):
            if api_type == "pdd.ddk.goods.search":
                kw = str(params.get("keyword") or "")
                return search_payload(goods_id=kw, sign="ESIGN_" + kw)
            if api_type == "pdd.ddk.goods.detail":
                return detail_payload(sign=str(params.get("goods_sign") or ""),
                                      group=1990, normal=2590, coupon=0)
            return {"error_response": {"error_code": 1, "error_msg": "未知接口"}}

        store["responder"] = responder_e2e
        engine = RefreshEngine(ctx, collector_factory=lambda pf: adapter if pf == "pdd" else None)
        result = engine.run_once("test")
        check("调度器一轮：3 个商品全部成功",
              bool(result.get("ok")) and result.get("total") == 3
              and result.get("changed") == 3 and result.get("new_low") == 3
              and result.get("failed") == 0,
              {k: result.get(k) for k in ("total", "changed", "new_low", "failed")})

        prices_a = db.list_prices(int(item_a["id"]))
        check("新记录来源=api、备注=多多进宝",
              len(prices_a) == 1 and prices_a[0]["source"] == "api"
              and prices_a[0]["note"] == "多多进宝", prices_a[:1])
        check("新记录价格 19.90", abs(float(prices_a[0]["price"]) - 19.90) < 1e-9)
        runs = db.recent_refresh_runs(5)
        check("刷新日志已记录",
              bool(runs) and int(runs[0]["changed"]) == 3, runs[:1])

        # ---- 框架就绪 ----
        check("真适配器就绪（adapters_ready）", collectors.adapters_ready() is True)
        collectors.reset_cache()
        col = collectors.get_collector("pdd", ctx)
        check("get_collector 返回拼多多采集器",
              col is not None and col.__class__.__name__ == "PddCollector")
        collectors.reset_cache()
    finally:
        if engine is not None:
            engine.stop()
        if ctx is not None:
            ctx.stop_refresh()
            ctx.stop_api()
            ctx.close()
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
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