# -*- coding: utf-8 -*-
"""本地安全工具：令牌生成与掩码显示。"""
from __future__ import annotations

import secrets


def new_token() -> str:
    """生成高强度随机令牌（用于浏览器脚本上报鉴权）。"""
    return secrets.token_urlsafe(32)


def new_install_id() -> str:
    """生成安装标识（用于区分不同机器/实例，不含任何个人信息）。"""
    return secrets.token_hex(8)


def mask(value: str, head: int = 4, tail: int = 4) -> str:
    """掩码显示：abcd****wxyz。仅用于界面展示，绝不用于存储。"""
    if not value:
        return ""
    if len(value) <= head + tail:
        return "*" * len(value)
    return f"{value[:head]}{'*' * 6}{value[-tail:]}"