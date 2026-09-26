# -*- coding: utf-8 -*-
"""把进程临时目录重定向到数据根的 cache/tmp/（S-3 要求）。"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


def redirect_temp(cache_tmp: Path) -> None:
    """必须在程序最早期调用（早于任何使用临时文件的库）。"""
    cache_tmp = Path(cache_tmp).resolve()      # ★ 保证绝对路径
    cache_tmp.mkdir(parents=True, exist_ok=True)
    p = str(cache_tmp)

    os.environ["TMP"] = p
    os.environ["TEMP"] = p
    os.environ["TMPDIR"] = p          # 兼容类 Unix 库

    # 让 tempfile 模块也认这个目录
    tempfile.tempdir = p


def cleanup_temp(cache_tmp: Path) -> None:
    """退出时清理临时文件（尽力而为，失败不影响退出）。"""
    try:
        if not cache_tmp.is_dir():
            return
        for item in cache_tmp.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass
    except Exception:
        pass


def current_temp() -> str:
    """返回当前生效的临时目录（用于自检/日志）。"""
    return tempfile.gettempdir()