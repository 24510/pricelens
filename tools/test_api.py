# -*- coding: utf-8 -*-
"""采集接口自测：临时目录 + 随机端口，不接触真实数据。"""
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from app_context import AppContext          # noqa: E402
from api_server import ApiServer            # noqa: E402

PASS = []
FAIL = []


def check(name, cond, extra=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (("  → " + str(extra)) if extra else ""))


def call(base, method, path, payload=None, token=None, extra_headers=None):
    url = base + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-PL-Token", token)
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8")
            body = json.loads(raw) if raw else {}
            return resp.status, body, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
        except Exception:
            body = {}
        return exc.code, body, dict(exc.headers)


def get_raw(base, path):
    """原始 GET（返回文本，用于脚本下载这类非 JSON 响应）。"""
    req = urllib.request.Request(base + path, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            return resp.status, text, dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, "", dict(exc.headers)


def main():
    print("=== PriceLens 采集接口自测（临时数据，不影响真实数据） ===")
    root = Path(tempfile.mkdtemp(prefix="pricelens_api_test_"))
    ctx = None
    srv = None
    try:
        ctx = AppContext()
        ctx.init_at(root, start_api=False)
        token = ctx.local_token()
        check("临时环境初始化（含本机令牌）", bool(token))
        if not token:
            return 1

        srv = ApiServer(ctx)
        ok, err = srv.start(0, token)
        check("接口启动（随机端口）", ok, err)
        if not ok:
            return 1
        base = f"http://127.0.0.1:{srv.port}"

        st, body, _ = call(base, "GET", "/api/ping")
        check("接口存活检查（/api/ping）", st == 200 and body.get("ok"))

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "123456789", "price": 1.0})
        check("无令牌上报被拒绝（401）", st == 401)

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "123456789", "price": 1.0},
                           token="wrong-token-xxxx")
        check("错误令牌被拒绝（401）", st == 401)

        before = ctx.db.stats()["items"]
        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "872234708625",
                            "price": 12.3, "title": "自测商品", "dry": True},
                           token=token)
        after = ctx.db.stats()["items"]
        check("试运行（dry）不写入数据",
              st == 200 and body.get("dry") and before == after)

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "872234708625",
                            "price": 12.3, "title": "自测商品", "note": "自测"},
                           token=token)
        check("正常上报（新增商品 + 记录价格）",
              st == 200 and body.get("ok") and body.get("item_created")
              and body.get("stats", {}).get("count") == 1)

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "872234708625", "price": 12.3},
                           token=token)
        check("重复点击被拦截（同价 90 秒内）", st == 200 and body.get("duplicate"))

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "872234708625", "price": 9.9},
                           token=token)
        check("第二条价格正常入库",
              st == 200 and body.get("stats", {}).get("count") == 2)

        before_items = ctx.db.stats()["items"]
        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "111222333",
                            "price": 5.0, "mode": "auto"}, token=token)
        check("自动模式：未监控商品不会自动加入",
              st == 200 and body.get("skipped") and body.get("reason") == "unknown"
              and ctx.db.stats()["items"] == before_items)

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "872234708625",
                            "price": 9.9, "mode": "auto"}, token=token)
        check("自动模式：价格未变化时跳过",
              st == 200 and body.get("skipped") and body.get("reason") == "unchanged")

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "872234708625",
                            "price": 8.8, "mode": "auto"}, token=token)
        check("自动模式：价格变化时自动记录",
              st == 200 and body.get("ok") and not body.get("skipped")
              and body.get("stats", {}).get("count") == 3)

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "872234708625", "price": "abc"},
                           token=token)
        check("非法价格被拒绝（400）", st == 400)

        st, body, _ = call(base, "POST", "/api/report",
                           {"platform": "pdd", "item_id": "12", "price": 1},
                           token=token)
        check("非法商品 ID 被拒绝（400）", st == 400)

        st, body, hdr = call(base, "OPTIONS", "/api/report", None, None,
                             {"Origin": "https://item.jd.com",
                              "Access-Control-Request-Method": "POST",
                              "Access-Control-Request-Headers": "X-PL-Token, Content-Type"})
        check("CORS 预检（回显来源）",
              st == 204 and hdr.get("Access-Control-Allow-Origin") == "https://item.jd.com",
              st)

        st, body, hdr = call(base, "OPTIONS", "/api/report", None, None,
                             {"Origin": "https://item.jd.com",
                              "Access-Control-Request-Method": "POST",
                              "Access-Control-Request-Private-Network": "true"})
        check("私有网络预检头（PNA）已附带",
              hdr.get("Access-Control-Allow-Private-Network") == "true")

        st, text, hdr = get_raw(base, "/pricelens.user.js")
        check("在线安装：脚本可下载、内嵌正确端口与令牌",
              st == 200
              and ("var TOKEN = '" + token + "'") in text
              and ("var PORT = " + str(srv.port) + ";") in text,
              st)
        check("在线安装：响应不带 CORS 头（防跨站窃取令牌）",
              hdr.get("Access-Control-Allow-Origin") is None)
    finally:
        if srv:
            srv.stop()
        if ctx:
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