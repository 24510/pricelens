# -*- coding: utf-8 -*-
"""商品链接解析：从粘贴的文本里识别平台并提取商品 ID。

支持：
  · 拼多多  mobile.yangkeduo.com / pinduoduo.com 的 goods_id
  · 京东    item.jd.com/{id}.html、item.m.jd.com/product/{id}.html
  · 淘宝    item.taobao.com / detail.tmall.com 的 id 参数
不支持短链接（p.pinduoduo.com、3.cn、m.tb.cn）——这类必须先跳转拿到真实链接。
"""
from __future__ import annotations

import re
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

PLATFORM_NAMES = {"pdd": "拼多多", "jd": "京东", "tb": "淘宝"}

# 停止点：空白、引号、尖括号、中文字符、全角符号
_URL_RE = re.compile(
    r"https?://[^\s\"'<>\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]+",
    re.IGNORECASE)
_WS_RE = re.compile(r"[\s\u3000]+")

# 域名 → 平台
_HOST_MAP = (
    ("pdd", ("yangkeduo.com", "pinduoduo.com")),
    ("jd", ("jd.com", "jingdong.com", "jd.hk")),
    ("tb", ("taobao.com", "tmall.com", "tb.cn", "tmall.hk")),
)

# 短链接域名（需要先跳转才能拿到真实地址）
_SHORT_HOSTS = (
    "p.pinduoduo.com", "3.cn", "u.jd.com", "m.tb.cn", "tb.cn",
    "s.click.taobao.com",
)


def _extract_url(text: str) -> Optional[str]:
    """从任意粘贴文本中抠出第一个 http(s) 链接。"""
    if not text:
        return None
    flat = _WS_RE.sub("", text)
    m = _URL_RE.search(flat)
    if not m:
        return None
    url = m.group(0).replace("&amp;", "&")
    return url.rstrip("，。、；：！？）】}>,.;:!?)}]")


def _match_platform(host: str) -> Optional[str]:
    for plat, suffixes in _HOST_MAP:
        for suffix in suffixes:
            if host == suffix or host.endswith("." + suffix):
                return plat
    return None


def _is_short(host: str) -> bool:
    return any(host == h or host.endswith("." + h) for h in _SHORT_HOSTS)


def _id_pdd(url: str) -> Optional[str]:
    q = parse_qs(urlparse(url).query)
    for key in ("goods_id", "goodsId"):
        val = (q.get(key) or [""])[0]
        if val.isdigit():
            return val
    m = re.search(r"goods_id[=:](\d+)", url)
    return m.group(1) if m else None


def _id_jd(url: str) -> Optional[str]:
    path = urlparse(url).path
    m = re.search(r"/(\d{6,})\.html", path)
    if m:
        return m.group(1)
    m = re.search(r"/product/(\d{6,})", path)
    if m:
        return m.group(1)
    q = parse_qs(urlparse(url).query)
    for key in ("sku", "skuId"):
        val = (q.get(key) or [""])[0]
        if val.isdigit():
            return val
    return None


def _id_tb(url: str) -> Optional[str]:
    q = parse_qs(urlparse(url).query)
    for key in ("id", "itemId", "item_id"):
        val = (q.get(key) or [""])[0]
        if val.isdigit():
            return val
    return None


_ID_FUNCS = {"pdd": _id_pdd, "jd": _id_jd, "tb": _id_tb}


def canonical_url(platform: str, item_id: str) -> str:
    """生成规范链接（去掉分享参数，便于 P2 脚本使用）。"""
    if platform == "pdd":
        return f"https://mobile.yangkeduo.com/goods.html?goods_id={item_id}"
    if platform == "jd":
        return f"https://item.jd.com/{item_id}.html"
    if platform == "tb":
        return f"https://item.taobao.com/item.htm?id={item_id}"
    return ""


def parse(text: str) -> Dict:
    """解析粘贴内容。

    成功：{"ok": True, "platform", "platform_name", "item_id", "url"}
    失败：{"ok": False, "platform": None, "message": "..."}
    """
    url = _extract_url(text)
    if not url:
        return {"ok": False, "platform": None, "item_id": None,
                "message": "没有找到链接。请粘贴完整商品链接（以 http 开头）。"}

    host = urlparse(url).netloc.lower().split(":")[0]
    platform = _match_platform(host)

    if _is_short(host):
        name = PLATFORM_NAMES.get(platform, "该平台")
        return {"ok": False, "platform": platform, "item_id": None,
                "message": f"这是{name}的短链接，无法直接取得商品 ID。"
                           f"请先在浏览器中打开它，再复制地址栏里的完整链接。"}

    if not platform:
        return {"ok": False, "platform": None, "item_id": None,
                "message": "无法识别平台。请确认链接来自拼多多 / 京东 / 淘宝，"
                           "或展开下方「手动指定」填写。"}

    item_id = _ID_FUNCS[platform](url)
    if not item_id:
        return {"ok": False, "platform": platform, "item_id": None,
                "message": f"识别到{PLATFORM_NAMES[platform]}链接，但没找到商品 ID。"
                           f"请在浏览器中打开商品页，复制地址栏链接后重试。"}

    return {"ok": True, "platform": platform,
            "platform_name": PLATFORM_NAMES[platform],
            "item_id": item_id,
            "url": canonical_url(platform, item_id)}