# -*- coding: utf-8 -*-
"""日志：按天滚动 + 敏感信息脱敏。"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from const import APP_VERSION, LOG_PREFIX

# 脱敏规则（顺序敏感：先长后短）
_RULES = [
    # key=value / key: value 形式
    (re.compile(r"(?i)\b(client_secret|app_secret|secretkey|app_key|access_key|"
                r"accesskey|authorization|sign|token|local_token)\b\s*[=:]\s*([^\s,;&\"']+)"),
     lambda m: f"{m.group(1)}=***"),
    # 32 位十六进制（MD5 签名 / 部分密钥）
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), lambda m: "***"),
    # 超长随机串（token / secret 特征）
    (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), lambda m: "***"),
]


def redact(text: str) -> str:
    """把文本中的敏感信息替换为 ***。"""
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text


class RedactFilter(logging.Filter):
    """在日志落盘前重写消息内容。"""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(str(record.msg))
            if record.args:
                record.args = tuple(redact(str(a)) for a in record.args)
        except Exception:
            pass
        return True


def setup_logger(log_dir: Path, debug: bool = False) -> logging.Logger:
    """初始化日志：文件（按天滚动）+ 控制台。幂等，可重复调用。"""
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOG_PREFIX)
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    logger.propagate = False
    if logger.handlers:          # 已初始化，避免重复添加 handler
        return logger

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    today = datetime.now().strftime("%Y-%m-%d")
    fh = TimedRotatingFileHandler(
        filename=str(log_dir / f"{LOG_PREFIX}-{today}.log"),
        when="midnight", backupCount=14, encoding="utf-8", delay=True,
    )
    fh.suffix = "%Y-%m-%d"
    fh.setFormatter(fmt)
    fh.addFilter(RedactFilter())
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.addFilter(RedactFilter())
    logger.addHandler(ch)

    logger.info("=== PriceLens v%s 日志启动 ===", APP_VERSION)
    return logger