# -*- coding: utf-8 -*-
"""PriceLens 全局常量。

约定：所有硬编码的字符串标识（应用名/文件名/互斥量名）只允许出现在本文件。
"""

APP_NAME = "PriceLens"
APP_NAME_CN = "价格透镜"
APP_ID = "pricelens"
APP_VERSION = "1.0.0"
APP_TITLE = f"{APP_NAME} · {APP_NAME_CN}"

# 文件名 / 系统标识
DB_FILENAME = "pricelens.db"
LOG_PREFIX = "pricelens"
MUTEX_NAME = "PriceLens_SingleInstance"
LOCATION_DIRNAME = "PriceLens"
LOCATION_FILENAME = "location.txt"
CONFIG_FILENAME = "config.ini"

# 默认参数
DEFAULT_PORT = 8765
DEFAULT_API_PORT = 8766     # 采集接口专用端口（与界面端口分开，互不干扰）
SCHEMA_VERSION = 2

# 数据根（专属文件夹）名称
DATA_ROOT_NAME = "PriceLensData"

# 数据根下的子目录名
DIR_DATA = "data"
DIR_LOGS = "logs"
DIR_CACHE = "cache"
DIR_CONFIG = "config"
DIR_BACKUPS = "backups"
DIR_USERSCRIPT = "userscript"