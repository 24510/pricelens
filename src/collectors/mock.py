# -*- coding: utf-8 -*-
"""模拟采集器：不访问网络，生成"会变化"的确定性价格。

用途：
  · PRICELENS_MOCK=1 时演示自动刷新全流程（P3.1 阶段真实适配器尚未接入）；
  · 排错对照：产生的记录备注固定为「模拟演示」，与真实数据一眼区分。

规则：同一商品每查询 2 次，价格变化一次（区间内小幅波动）；
      基准价由 item_id 决定 —— 同一商品结果可复现。
"""
from __future__ import annotations

from typing import Any, Dict

from collectors import BaseCollector, Quote

# 价格波动序列（元）；从第 2 次查询开始，每 2 次切换一档
_DELTAS = (0.0, -5.0, 2.5, -1.5, 4.0)


class MockCollector(BaseCollector):
    platform = "mock"
    name = "模拟采集器"

    def __init__(self, ctx: Any = None) -> None:
        super().__init__(ctx)
        self._calls: Dict[str, int] = {}      # item_id -> 查询次数

    @staticmethod
    def _base(item_id: str) -> float:
        digits = [int(c) for c in item_id if c.isdigit()] or [7]
        return 90.0 + (sum(digits) * 37 % 610)   # 90 ~ 699 元

    def fetch(self, item: Dict[str, Any]) -> Quote:
        item_id = str(item.get("item_id") or "")
        n = self._calls.get(item_id, 0)
        self._calls[item_id] = n + 1
        delta = _DELTAS[((n + 1) // 2) % len(_DELTAS)]
        price = round(self._base(item_id) + delta + 0.9, 2)
        return Quote(price=price, note="模拟演示", origin=self.name)