# -*- coding: utf-8 -*-
"""拼多多采集器（多多进宝 · pdd.ddk.goods.detail）。

要点（依据开放平台现行接口约定）：
  · 详情接口请求「字符型商品 ID」goods_sign（数字 goods_id 查询已下线）；
  · 若手上只有数字 ID（商品页 URL 里那种），先用搜索接口
    （pdd.ddk.goods.search，keyword 支持 goods_id 与商品链接）换算出
    goods_sign，并缓存到 settings（键：pdd_sign:<数字ID>），此后直接复用；
  · 签名：sign = MD5(client_secret + 排序后"键值直接拼接" + client_secret)，
    大写十六进制；所有参数（除 sign）参与签名；
  · 网关：POST https://gw-api.pinduoduo.com/api/router（表单编码，仅 POST）；
  · 公共参数含 data_type=JSON：明确要求返回 JSON（官方协议公共参数之一）；
  · 详情接口无需 access_token（多多客无须授权接口）；
  · 自测：构造参数 endpoint 或环境变量 PRICELENS_PDD_ENDPOINT 可覆盖网关。

价格单位：接口返回「分」，入库前换算为「元」。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

import config as cfg_mod
from collectors import BaseCollector, Quote

DEFAULT_ENDPOINT = "https://gw-api.pinduoduo.com/api/router"
API_DETAIL = "pdd.ddk.goods.detail"
API_SEARCH = "pdd.ddk.goods.search"
SIGN_CACHE_PREFIX = "pdd_sign:"
DEFAULT_TIMEOUT = 8.0


def make_sign(params: Dict[str, str], client_secret: str) -> str:
    """拼多多签名：secret + k1v1k2v2…（按键名排序）+ secret 的 MD5（大写）。"""
    joined = "".join(str(k) + str(params[k]) for k in sorted(params) if k != "sign")
    raw = (client_secret + joined + client_secret).encode("utf-8")
    return hashlib.md5(raw).hexdigest().upper()


def fen_to_yuan(value: Any) -> Optional[float]:
    """分 → 元；无效值返回 None（价格必须为正数）。"""
    try:
        num = float(value)
    except Exception:
        return None
    if num <= 0:
        return None
    return round(num / 100.0, 2)


class PddCollector(BaseCollector):
    platform = "pdd"
    name = "多多进宝"

    def __init__(self, ctx: Any = None, endpoint: str = "",
                 timeout: float = DEFAULT_TIMEOUT) -> None:
        super().__init__(ctx)
        self._endpoint = str(
            endpoint or os.environ.get("PRICELENS_PDD_ENDPOINT") or DEFAULT_ENDPOINT
        ).strip()
        try:
            self._timeout = float(timeout)
        except Exception:
            self._timeout = DEFAULT_TIMEOUT

    # ---------- 凭证与缓存 ----------

    def _credentials(self) -> Tuple[str, str, str]:
        cfg = getattr(self.ctx, "cfg", None)
        client_id = cfg_mod.get(cfg, "pdd", "client_id")
        client_secret = cfg_mod.get(cfg, "pdd", "client_secret")
        pid = cfg_mod.get(cfg, "pdd", "pid")
        if not client_id or not client_secret:
            raise RuntimeError(
                "拼多多密钥未配置：请打开「🔑 密钥设置」填写 client_id 与 client_secret"
            )
        return client_id, client_secret, pid

    def _cached_sign(self, goods_id: str) -> str:
        db = getattr(self.ctx, "db", None)
        if db is None or not goods_id.isdigit():
            return ""
        try:
            return str(db.get_setting(SIGN_CACHE_PREFIX + goods_id) or "").strip()
        except Exception:
            return ""

    def _store_sign(self, goods_id: str, sign: str) -> None:
        db = getattr(self.ctx, "db", None)
        if db is None or not sign:
            return
        try:
            db.set_setting(SIGN_CACHE_PREFIX + goods_id, sign)
        except Exception:
            pass

    def _clear_sign(self, goods_id: str) -> None:
        db = getattr(self.ctx, "db", None)
        if db is None:
            return
        try:
            db.set_setting(SIGN_CACHE_PREFIX + goods_id, "")
        except Exception:
            pass

    # ---------- 网关调用 ----------

    def _call(self, api_type: str, params: Dict[str, Any],
              client_id: str, client_secret: str) -> Dict[str, Any]:
        payload: Dict[str, str] = {
            "type": api_type,
            "client_id": client_id,
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
        }
        for key, value in (params or {}).items():
            text = "" if value is None else str(value).strip()
            if text:
                payload[key] = text
        payload["sign"] = make_sign(payload, client_secret)

        body = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint, data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                     "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                pass
            raise RuntimeError(f"网络错误：HTTP {exc.code} {detail}".strip())
        except Exception as exc:
            raise RuntimeError(f"网络错误：{exc}")

        try:
            data = json.loads(raw)
        except Exception:
            raise RuntimeError(f"返回内容无法解析（前 120 字）：{raw[:120]}")
        if not isinstance(data, dict):
            raise RuntimeError("返回内容格式异常（非 JSON 对象）")

        error = data.get("error_response")
        if error:
            code = (error or {}).get("error_code", "")
            msg = str((error or {}).get("error_msg") or "")
            hint = ""
            low = msg.lower()
            if "goods_sign" in low or "终端用户" in msg:
                hint = "（该商品需要 goods_sign，系统会自动换算；若持续失败请稍后用商品页采集一次）"
            elif "签名" in msg or "sign" in low:
                hint = "（请检查「密钥设置」里 client_secret 是否填对）"
            elif "权限" in msg or "审核" in msg:
                hint = "（请到开放平台确认应用与接口权限）"
            raise RuntimeError(f"接口错误[{code}]：{msg}{hint}")
        return data

    # ---------- goods_sign 获取 ----------

    def _sign_from_search(self, goods_id: str, client_id: str,
                          client_secret: str, pid: str) -> str:
        data = self._call(API_SEARCH, {"keyword": goods_id, "pid": pid or None},
                          client_id, client_secret)
        resp = data.get("goods_search_response")
        if not isinstance(resp, dict):
            raise RuntimeError("搜索接口未返回预期结构（goods_search_response）")
        goods_list = resp.get("goods_list") or []
        for goods in goods_list:
            if str(goods.get("goods_id") or "") == goods_id:
                sign = str(goods.get("goods_sign") or "").strip()
                if sign:
                    return sign
        if len(goods_list) == 1:
            sign = str(goods_list[0].get("goods_sign") or "").strip()
            if sign:
                return sign
        raise RuntimeError(
            f"未能从搜索接口找到该商品（返回 {len(goods_list)} 条结果）——稍后将重试")

    # ---------- 采集入口 ----------

    def fetch(self, item: Dict[str, Any]) -> Quote:
        client_id, client_secret, pid = self._credentials()
        raw_id = str(item.get("item_id") or "").strip()
        if not raw_id:
            raise RuntimeError("商品 ID 为空")

        from_cache = False
        if raw_id.isdigit():
            sign = self._cached_sign(raw_id)
            if sign:
                from_cache = True
            else:
                sign = self._sign_from_search(raw_id, client_id, client_secret, pid)
                self._store_sign(raw_id, sign)
        else:
            sign = raw_id                     # 已是字符型 ID（goods_sign）

        def call_detail(cur_sign: str) -> Dict[str, Any]:
            params = {"goods_sign": cur_sign, "pid": pid or None}
            return self._call(API_DETAIL, params, client_id, client_secret)

        try:
            data = call_detail(sign)
        except RuntimeError as exc:
            # 缓存失效自愈：换算过的 sign 可能过期/无效，重取一次再试
            if from_cache and ("goods_sign" in str(exc).lower() or "终端用户" in str(exc)):
                self._clear_sign(raw_id)
                sign = self._sign_from_search(raw_id, client_id, client_secret, pid)
                self._store_sign(raw_id, sign)
                data = call_detail(sign)
            else:
                raise

        resp = data.get("goods_detail_response")
        if not isinstance(resp, dict):
            raise RuntimeError("详情接口未返回预期结构（goods_detail_response）")
        details = resp.get("goods_details") or []
        target = None
        for goods in details:
            if str(goods.get("goods_sign") or "") == sign:
                target = goods
                break
        if target is None and len(details) == 1:
            target = details[0]
        if target is None:
            raise RuntimeError("未找到该商品（可能未参加多多进宝推广）")

        price = fen_to_yuan(target.get("min_group_price"))
        if price is None:
            price = fen_to_yuan(target.get("min_normal_price"))
        if price is None:
            raise RuntimeError("接口未返回有效价格（min_group_price / min_normal_price）")

        return Quote(
            price=price,
            list_price=fen_to_yuan(target.get("min_normal_price")),
            coupon=fen_to_yuan(target.get("coupon_discount")),
            note="多多进宝",
            origin=self.name,
        )