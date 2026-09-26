# -*- coding: utf-8 -*-
"""采集器框架（P3）：把「查询某商品当前价格」抽象成统一接口。

约定：
  · 一个采集器负责一个平台，实现 fetch(item) -> Quote（只查询、不落库）；
  · 落库交给 refresh.RefreshEngine 统一完成（比对价格、防重复、记日志）；
  · 真实适配器放在 collectors/adapters/ 下（pdd.py / jd.py，P3.3 接入；
    未就绪时 get_collector 返回 None）；
  · 环境变量 PRICELENS_MOCK=1 时，pdd / jd 改用模拟采集器（本机演示 /
    自测用，不访问网络）。正常启动完全不受影响。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

# 可能进入增强模式的平台（有官方接口）；淘宝无接口，恒为页面采集
API_PLATFORMS = ("pdd", "jd")


@dataclass
class Quote:
    """一次采集结果。"""
    price: Optional[float] = None        # 当前价（必填）
    list_price: Optional[float] = None   # 划线价（可选）
    coupon: Optional[float] = None       # 券面额（可选）
    note: str = ""                       # 写入价格记录的备注（可选）
    origin: str = ""                     # 采集器名称（日志用）


class BaseCollector:
    """采集器基类：子类实现 fetch() 即可。"""

    platform: str = ""
    name: str = ""

    def __init__(self, ctx: Any = None) -> None:
        self.ctx = ctx

    def fetch(self, item: Dict[str, Any]) -> Quote:
        raise NotImplementedError("采集器未实现 fetch()")


# ---------- 模拟开关 / 适配器就绪判断 ----------

def mock_enabled() -> bool:
    """是否开启模拟模式（环境变量 PRICELENS_MOCK=1|true|yes|on）。"""
    return str(os.environ.get("PRICELENS_MOCK", "")).strip().lower() in (
        "1", "true", "yes", "on")


def adapters_ready() -> bool:
    """真实适配器是否至少有一个就绪（P3.3 接入后即为 True）。"""
    import importlib.util
    for name in ("collectors.adapters.pdd", "collectors.adapters.jd"):
        try:
            if importlib.util.find_spec(name) is not None:
                return True
        except Exception:
            continue
    return False


# ---------- 注册表 ----------

_real_instances: Dict[str, BaseCollector] = {}   # 真实采集器缓存（按平台）
_mock_instances: Dict[str, BaseCollector] = {}   # 模拟采集器缓存（按平台）


def _build_real(platform: str, ctx: Any) -> Optional[BaseCollector]:
    import importlib

    table = {"pdd": ("collectors.adapters.pdd", "PddCollector"),
             "jd": ("collectors.adapters.jd", "JdCollector")}
    entry = table.get(platform)
    if not entry:
        return None
    mod_name, cls_name = entry
    try:
        mod = importlib.import_module(mod_name)
    except ImportError:
        return None                      # 适配器尚未接入（P3.3）
    except Exception as exc:
        lg = getattr(ctx, "log", None)
        if lg is not None:
            try:
                lg.warning("采集器加载失败 %s：%s", mod_name, exc)
            except Exception:
                pass
        return None
    cls = getattr(mod, cls_name, None)
    if cls is None:
        return None
    try:
        return cls(ctx)
    except Exception:
        return None


def get_collector(platform: str, ctx: Any = None) -> Optional[BaseCollector]:
    """取某平台的采集器；没有可用采集器时返回 None。"""
    if platform not in API_PLATFORMS:
        return None
    if mock_enabled():
        if platform not in _mock_instances:
            from collectors.mock import MockCollector
            _mock_instances[platform] = MockCollector(ctx)
        return _mock_instances[platform]
    if platform not in _real_instances:
        col = _build_real(platform, ctx)
        if col is None:
            return None
        _real_instances[platform] = col
    return _real_instances[platform]


def reset_cache() -> None:
    """清空实例缓存（自测 / 模式切换时用）。"""
    _real_instances.clear()
    _mock_instances.clear()