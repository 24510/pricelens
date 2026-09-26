# -*- coding: utf-8 -*-
"""应用运行时上下文：数据根 + 配置 + 数据库 + 日志 + 采集接口 + 自动刷新。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, Optional

import config as cfg_mod
import paths
from const import (APP_VERSION, DEFAULT_API_PORT, DEFAULT_PORT, DIR_BACKUPS,
                   DIR_CACHE, DIR_CONFIG, DIR_DATA, DIR_LOGS, DIR_USERSCRIPT)
from db.dao import Database
from logger import setup_logger
from utils.security import mask, new_install_id, new_token
from utils.win_env import redirect_temp


class AppContext:
    def __init__(self) -> None:
        self.data_root: Optional[Path] = None
        self.escape_mode = False
        self.cfg = None
        self.db: Optional[Database] = None
        self.log: logging.Logger = logging.getLogger("pricelens")
        self.api = None                 # api_server.ApiServer 实例
        self.api_error = ""             # 采集接口启动失败原因（展示用）
        self.refresh = None             # refresh.RefreshEngine 实例（P3 自动刷新）

    # ---------- 初始化（确定数据根后调用） ----------

    def init_at(self, data_root: Path, escape: bool = False,
                start_api: bool = True, start_refresh: bool = True) -> None:
        self.stop_refresh()             # 切换数据目录时先停掉旧调度器
        self.data_root = Path(data_root).resolve()
        self.escape_mode = escape

        # 1) 建目录
        for sub in (DIR_DATA, DIR_LOGS, DIR_CACHE, DIR_CONFIG, DIR_BACKUPS,
                    DIR_USERSCRIPT):
            (self.data_root / sub).mkdir(parents=True, exist_ok=True)

        # 2) 重定向临时目录（必须尽早）
        redirect_temp(self.data_root / DIR_CACHE / "tmp")

        # 3) 日志
        self.log = setup_logger(self.data_root / DIR_LOGS)
        self.log.info("数据根: %s%s", self.data_root,
                      "（逃生模式）" if escape else "")

        # 4) 配置（不存在则生成全空模板）
        self.cfg = cfg_mod.load(self.data_root / DIR_CONFIG)

        changed = False
        if not cfg_mod.get(self.cfg, "app", "local_token"):
            cfg_mod.set_value(self.cfg, "app", "local_token", new_token())
            changed = True
        if not cfg_mod.get(self.cfg, "app", "api_port"):
            cfg_mod.set_value(self.cfg, "app", "api_port", str(DEFAULT_API_PORT))
            changed = True
        if not cfg_mod.get(self.cfg, "meta", "install_id"):
            cfg_mod.set_value(self.cfg, "meta", "install_id", new_install_id())
            changed = True
        if changed:
            cfg_mod.save(self.cfg, self.data_root / DIR_CONFIG)
            self.log.info("已生成本地令牌与安装标识")

        # 5) 数据库
        self.db = Database(self.data_root / DIR_DATA)
        self.db.init_schema()

        # 6) 采集接口（浏览器脚本上报用）
        if start_api:
            self.start_api()

        # 7) 自动刷新调度器（P3：官方接口定时查价）
        if start_refresh:
            self.start_refresh()
        else:
            self.refresh = None

        self.log.info("初始化完成：模式=%s，界面端口=%s，接口端口=%s",
                      "增强" if self.enhanced else "本地",
                      self.port, self.api_port())

    # ---------- 采集接口 ----------

    def local_token(self) -> str:
        if not self.cfg:
            return ""
        return cfg_mod.get(self.cfg, "app", "local_token")

    def api_port(self) -> int:
        """采集接口端口（与界面端口分开，避免两者冲突）。"""
        if self.cfg:
            try:
                return int(cfg_mod.get(self.cfg, "app", "api_port",
                                       str(DEFAULT_API_PORT)))
            except Exception:
                pass
        return DEFAULT_API_PORT

    def start_api(self) -> None:
        self.stop_api()
        self.api_error = ""
        if self.data_root is None:
            return
        try:
            from api_server import ApiServer
        except Exception as exc:
            self.api_error = f"接口模块加载失败：{exc}"
            self.log.warning(self.api_error)
            return

        srv = ApiServer(self)
        ok, err = srv.start(self.api_port(), self.local_token())
        if ok:
            self.api = srv
            self.log.info("采集接口已启动: http://127.0.0.1:%s", srv.port)
        else:
            self.api_error = err
            self.log.warning("采集接口未启动: %s", err)

    def stop_api(self) -> None:
        if self.api:
            try:
                self.api.stop()
            except Exception:
                pass
            self.api = None

    def api_running(self) -> bool:
        return bool(self.api and self.api.running())

    def api_info(self) -> Dict[str, object]:
        return {
            "running": self.api_running(),
            "port": self.api.port if self.api else 0,
            "token_masked": mask(self.local_token()),
            "error": self.api_error,
        }

    # ---------- 自动刷新（P3） ----------

    def start_refresh(self) -> None:
        """启动自动刷新调度器；任何异常都不影响主流程。"""
        self.stop_refresh()
        if self.db is None:
            return
        try:
            from refresh import RefreshEngine
            engine = RefreshEngine(self)
            engine.start()
            self.refresh = engine
        except Exception as exc:
            self.log.warning("自动刷新调度器启动失败：%s", exc)
            self.refresh = None

    def stop_refresh(self) -> None:
        if self.refresh is not None:
            try:
                self.refresh.stop()
            except Exception:
                pass
            self.refresh = None

    def refresh_status(self) -> Dict[str, object]:
        """供界面读取的调度器状态。"""
        if self.refresh is None:
            return {"enabled": False, "running": False, "busy": False,
                    "mock": False, "phase": "", "interval_minutes": 0,
                    "next_at": "", "last": None}
        try:
            return self.refresh.status()
        except Exception as exc:
            return {"enabled": False, "running": False, "busy": False,
                    "mock": False, "phase": "", "interval_minutes": 0,
                    "next_at": "", "last": None, "error": str(exc)}

    # ---------- 只读属性 ----------

    @property
    def initialized(self) -> bool:
        return self.data_root is not None

    @property
    def port(self) -> int:
        if self.cfg:
            try:
                return int(cfg_mod.get(self.cfg, "app", "port", str(DEFAULT_PORT)))
            except Exception:
                pass
        return DEFAULT_PORT

    @property
    def enhanced(self) -> bool:
        """任一平台进入增强模式即为 True。"""
        if not self.cfg:
            return False
        return any(v == "enhanced" for v in cfg_mod.all_modes(self.cfg).values())

    def modes(self) -> Dict[str, str]:
        if not self.cfg:
            return {"pdd": "local", "jd": "local", "tb": "local"}
        return cfg_mod.all_modes(self.cfg)

    # ---------- 供界面读取的状态 ----------

    def state(self) -> Dict[str, object]:
        modes = self.modes()
        enhanced_any = any(v == "enhanced" for v in modes.values())

        if not self.initialized:
            mode_text = "未初始化"
        elif enhanced_any:
            mode_text = "增强模式"
        else:
            mode_text = "本地模式"

        result: Dict[str, object] = {
            "version": APP_VERSION,
            "initialized": self.initialized,
            "need_choose": not self.initialized,
            "data_root": str(self.data_root) if self.data_root else "",
            "escape_mode": self.escape_mode,
            "app_root": str(paths.app_root()),
            "app_root_writable": paths.app_root_writable(),
            "port": self.port,
            "mode_text": mode_text,
            "platforms": [
                {"key": "pdd", "name": "拼多多", "mode": modes.get("pdd", "local")},
                {"key": "jd", "name": "京东", "mode": modes.get("jd", "local")},
                {"key": "tb", "name": "淘宝", "mode": "local",
                 "note": "无开放接口，使用浏览器脚本采集"},
            ],
        }
        result["stats"] = self.db.stats() if self.db else {"items": 0, "prices": 0}
        result["api"] = self.api_info()
        result["refresh"] = self.refresh_status()
        return result

    def close(self) -> None:
        self.stop_refresh()
        self.stop_api()
        if self.db:
            self.db.close()