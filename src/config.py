# -*- coding: utf-8 -*-
"""配置读写 + 逐平台模式判定（S-1 / S-2）。

设计要点：
  · 模板中的密钥字段一律留空（S-1）。
  · 保存时自行序列化，保留注释（configparser 原生 write 会丢掉注释）。
"""
from __future__ import annotations

import configparser
from pathlib import Path
from typing import Dict

from const import CONFIG_FILENAME, DEFAULT_PORT, SCHEMA_VERSION

CONFIG_HEADER = """\
; ============================================================
;  PriceLens 配置文件
; ------------------------------------------------------------
;  使用说明：
;   · 留空 = 本地模式（手动记价 + 浏览器脚本采集），功能完整。
;   · 填入密钥 = 该平台切换为增强模式（自动刷新 + 自动枚举）。
;   · 本文件仅保存在本机，请勿上传到任何公开位置。
; ============================================================
"""

SECTION_COMMENTS = {
    "meta": "元数据（程序自动维护，通常无需修改）",
    "pdd": "拼多多开放平台 · 在应用详情页获取 client_id / client_secret",
    "jd": "京东联盟 · 在「导购媒体管理」「我的API」获取",
    "app": "应用设置",
}

# 首次启动生成的模板（密钥全空）
CONFIG_TEMPLATE = CONFIG_HEADER + """
[meta]
schema_version = {schema_version}
install_id =

[pdd]
client_id =
client_secret =
pid =

[jd]
app_key =
app_secret =
access_key =
pid =

[app]
port = {port}
local_token =
refresh_startup = true
refresh_interval_hot = 30
refresh_interval_focus = 60
refresh_interval_normal = 120
refresh_interval_night = 240
refresh_interval_cold = 720
""".format(schema_version=SCHEMA_VERSION, port=DEFAULT_PORT)

# 平台名 / 必需凭证（决定是否进入增强模式）
PLATFORMS: Dict[str, dict] = {
    "pdd": {"name": "拼多多", "required": ("client_id", "client_secret")},
    "jd": {"name": "京东", "required": ("app_key", "app_secret")},
}


def ensure_config(config_dir: Path) -> Path:
    """确保 config.ini 存在；不存在则从模板生成（全空）。"""
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = config_dir / CONFIG_FILENAME
    if not cfg_path.is_file():
        cfg_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return cfg_path


def load(config_dir: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(str(ensure_config(config_dir)), encoding="utf-8")
    return cfg


def save(cfg: configparser.ConfigParser, config_dir: Path) -> Path:
    """自行序列化：保留注释与分节顺序。"""
    cfg_path = config_dir / CONFIG_FILENAME
    lines = [CONFIG_HEADER.rstrip("\n"), ""]
    for section in cfg.sections():
        comment = SECTION_COMMENTS.get(section)
        if comment:
            lines.append(f"; {comment}")
        lines.append(f"[{section}]")
        for key, value in cfg.items(section):
            lines.append(f"{key} = {value}")
        lines.append("")
    cfg_path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return cfg_path


def get(cfg: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    try:
        return (cfg.get(section, key, fallback=default) or "").strip()
    except Exception:
        return default


def set_value(cfg: configparser.ConfigParser, section: str, key: str, value: str) -> None:
    if section not in cfg:
        cfg[section] = {}
    cfg[section][key] = "" if value is None else str(value)


def platform_mode(cfg: configparser.ConfigParser, key: str) -> str:
    """返回 'enhanced'（增强）或 'local'（本地）。"""
    info = PLATFORMS.get(key)
    if not info:
        return "local"
    for field in info["required"]:
        if not get(cfg, key, field):
            return "local"
    return "enhanced"


def all_modes(cfg: configparser.ConfigParser) -> Dict[str, str]:
    modes = {k: platform_mode(cfg, k) for k in PLATFORMS}
    modes["tb"] = "local"        # 淘宝无开放接口，恒为本地
    return modes