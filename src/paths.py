# -*- coding: utf-8 -*-
"""路径解析：锚点 = 程序自身所在目录。禁止使用 os.getcwd()。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from const import DATA_ROOT_NAME, LOCATION_DIRNAME, LOCATION_FILENAME

# 系统保护目录（禁止作为数据根）
SYSTEM_PROTECTED = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
)


# ---------- 程序自身位置 ----------

def is_frozen() -> bool:
    """是否运行在打包后的 exe 中。"""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """应用根目录：打包后 = exe 所在目录；开发时 = 项目根。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def web_root() -> Path:
    """前端资源目录。"""
    return app_root() / "web"


def default_data_root() -> Path:
    """默认数据根：程序目录下的专属文件夹（PriceLensData）。

    程序文件与数据分离：根目录只放程序，所有可写数据集中在专属文件夹内。
    备份/迁移 = 复制这一个文件夹；卸载 = 删除整个程序文件夹（零残留）。
    """
    return app_root() / DATA_ROOT_NAME


def app_root_writable() -> bool:
    """程序目录能否作为数据根使用。"""
    return is_writable(app_root()) and not is_protected(app_root())


# ---------- 可写性 / 保护目录判断 ----------

def is_writable(path: Path) -> bool:
    """真实写盘测试（不能只看权限位，Windows 上权限位经常骗人）。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def is_protected(path: Path) -> bool:
    """是否落在系统保护目录内（如 C:\\Program Files）。"""
    try:
        p = str(Path(path).resolve()).lower().rstrip("\\")
    except Exception:
        return True
    for sp in SYSTEM_PROTECTED:
        sp = sp.rstrip("\\")
        if p == sp or p.startswith(sp + "\\"):
            return True
    return False


# ---------- 逃生通道：路标文件 ----------

def location_file() -> Path:
    """路标文件位置（S-3 唯一豁免）：%LOCALAPPDATA%\\PriceLens\\location.txt"""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / LOCATION_DIRNAME / LOCATION_FILENAME


def read_location() -> Optional[Path]:
    """读取用户自选的数据根；不存在或非法则返回 None。"""
    lf = location_file()
    try:
        if not lf.is_file():
            return None
        text = lf.read_text(encoding="utf-8").strip()
        return Path(text) if text else None
    except Exception:
        return None


def write_location(path: Path) -> None:
    """记录用户自选的数据根到路标文件。"""
    lf = location_file()
    lf.parent.mkdir(parents=True, exist_ok=True)
    lf.write_text(str(path), encoding="utf-8")


def clear_location() -> None:
    """删除路标（恢复默认模式时使用）。"""
    try:
        location_file().unlink(missing_ok=True)
    except Exception:
        pass