# -*- coding: utf-8 -*-
"""平台密钥的读取与定点修改（保留 config.ini 的注释与排版）。

为什么单独成文件：
  · 只改动目标平台段落的键值，注释、顺序、其他段落原样保留。
  · 不依赖 config.py 的内部实现，独立可测。

安全约定：
  · 对外只提供「脱敏后的值」，完整密钥不出后端。
  · 写入的是"用户新输入的值"，界面不回显旧密钥。
"""
from __future__ import annotations

import configparser
import re
from pathlib import Path
from typing import Dict, Iterable, Tuple

# 平台定义（顺序即界面顺序）
PLATFORMS: Tuple[Dict, ...] = (
    {
        "id": "pdd",
        "name": "拼多多",
        "fields": (
            ("client_id", "Client ID", "应用 client_id"),
            ("client_secret", "Client Secret", "应用密钥"),
            ("pid", "推广位 PID", "推广位 ID"),
        ),
    },
    {
        "id": "jd",
        "name": "京东",
        "fields": (
            ("app_key", "App Key", "应用 AppKey"),
            ("app_secret", "App Secret", "应用 AppSecret"),
            ("access_key", "Access Token", "授权密钥（约 365 天有效）"),
            ("pid", "推广位 PID", "推广位 ID"),
        ),
    },
)


def get_platform(platform_id: str):
    """按 id 取平台定义，找不到返回 None。"""
    for pf in PLATFORMS:
        if pf["id"] == platform_id:
            return pf
    return None


def fields_of(platform_id: str) -> Tuple[Tuple[str, str, str], ...]:
    pf = get_platform(platform_id)
    return pf["fields"] if pf else ()


def mask_value(value: str) -> str:
    """脱敏显示：只保留头尾各 4 位。"""
    v = (value or "").strip()
    if not v:
        return ""
    if len(v) <= 8:
        return "****"
    return f"{v[:4]}****{v[-4:]}"


def _read_raw(path: Path) -> str:
    with path.open("r", encoding="utf-8", newline="") as f:
        return f.read()


def _write_raw(path: Path, text: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def read_values(ini_path, platform_id: str) -> Dict[str, str]:
    """读取某平台当前配置值；任何异常都返回空串集合。"""
    ini_path = Path(ini_path)
    result = {key: "" for key, _, _ in fields_of(platform_id)}
    try:
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(ini_path, encoding="utf-8")
        if cp.has_section(platform_id):
            for key in result:
                if cp.has_option(platform_id, key):
                    result[key] = (cp.get(platform_id, key) or "").strip()
    except Exception:
        pass
    return result


_SECTION_RE = re.compile(r"^\s*\[(.+?)\]\s*$")
_KV_RE = re.compile(r"^([ \t]*)([A-Za-z0-9_]+)[ \t]*=[ \t]*(.*?)[ \t]*(\r?\n)?$")


def _detect_eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def update_values(ini_path, platform_id: str,
                  mapping: Dict[str, str],
                  blank: Iterable[str] = ()) -> int:
    """定点改写：把 mapping / blank 中的键写回 ini（保留注释与排版）。

    · 键已存在 → 只替换值
    · 键缺失   → 追加到该段末尾
    · 段缺失   → 在文件末尾新建段落
    返回写入的键数量。
    """
    ini_path = Path(ini_path)
    text = _read_raw(ini_path) if ini_path.is_file() else ""
    eol = _detect_eol(text)

    wanted: Dict[str, str] = {}
    for key, value in (mapping or {}).items():
        wanted[key] = "" if value is None else str(value)
    for key in blank:
        wanted.setdefault(key, "")

    if not wanted:
        return 0

    lines = text.splitlines(keepends=True)

    start = None
    end = len(lines)
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if not m:
            continue
        if m.group(1).strip() == platform_id:
            start = i + 1
        elif start is not None:
            end = i
            break

    if start is not None:
        written = set()
        for i in range(start, end):
            m = _KV_RE.match(lines[i])
            if not m:
                continue
            key = m.group(2)
            if key in wanted:
                tail = m.group(4) or ""
                lines[i] = f"{m.group(1)}{key} = {wanted[key]}{tail}"
                written.add(key)
        missing = [k for k in wanted if k not in written]
        if missing:
            block = "".join(f"{k} = {wanted[k]}{eol}" for k in missing)
            lines.insert(end, block)
    else:
        prefix = ""
        if lines:
            if not lines[-1].endswith(("\n", "\r")):
                lines[-1] = lines[-1] + eol
            prefix = eol
        block = f"{prefix}[{platform_id}]{eol}" + "".join(
            f"{k} = {wanted[k]}{eol}" for k in wanted)
        lines.append(block)

    # 写前备份（同名 .bak），防手滑
    if ini_path.is_file():
        try:
            _write_raw(ini_path.with_name(ini_path.name + ".bak"), text)
        except Exception:
            pass

    _write_raw(ini_path, "".join(lines))
    return len(wanted)