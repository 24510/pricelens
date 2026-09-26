# -*- coding: utf-8 -*-
"""PriceLens 程序入口。

启动顺序（严格遵守）：
  1. 单实例检查
  2. 解析数据根（路标 → 程序目录下的专属文件夹 → 交给用户选择）
  3. 初始化（目录/日志/配置/数据库）
  4. 启动界面
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

# 开发模式：把 src 加入模块搜索路径
# 打包后（无控制台模式）stdout/stderr 可能为 None：先兜底，避免 print 报错
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

# 开发模式：把 src 加入模块搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths                                      # noqa: E402
from app_context import AppContext                # noqa: E402
from const import (APP_TITLE, CONFIG_FILENAME, DB_FILENAME,  # noqa: E402
                   DIR_BACKUPS, DIR_CACHE, DIR_CONFIG, DIR_DATA,
                   DIR_LOGS, MUTEX_NAME)
from ui.dialogs import message_box                # noqa: E402
from ui.window import run as run_window           # noqa: E402

_mutex_handle = None


def acquire_single_instance() -> bool:
    """Windows 命名互斥量：防止重复启动。"""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        ERROR_ALREADY_EXISTS = 183
        kernel32 = ctypes.windll.kernel32
        _mutex_handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        return True
    except Exception:
        return True


def migrate_legacy_layout(app_root: Path, target: Path) -> None:
    """把旧版散放在程序根目录下的 data/logs/cache/config/backups
    收进专属数据文件夹。

    仅在目标尚未建立、且检测到旧版痕迹时执行；
    任何失败都忽略（退回全新初始化），不影响启动。
    """
    try:
        if target.exists():
            return
        names = (DIR_DATA, DIR_LOGS, DIR_CACHE, DIR_CONFIG, DIR_BACKUPS)
        present = [n for n in names if (app_root / n).is_dir()]
        if not present:
            return

        markers = (app_root / DIR_DATA / DB_FILENAME,
                   app_root / DIR_CONFIG / CONFIG_FILENAME)
        if not any(m.is_file() for m in markers):
            return

        target.mkdir(parents=True, exist_ok=True)
        moved, failed = [], []
        for name in present:
            try:
                shutil.move(str(app_root / name), str(target / name))
                moved.append(name)
            except Exception as exc:            # 单个失败不影响其余
                failed.append(f"{name}({exc})")
        print(f"[info] 旧数据布局已迁移到 {target}：{moved}")
        if failed:
            print(f"[warn] 部分目录未能迁移（可手动移动）：{failed}")
    except Exception as exc:
        print(f"[warn] 旧数据布局迁移跳过：{exc}")


def resolve_data_root(ctx: AppContext) -> None:
    """按优先级确定数据根。全部失败则保持未初始化（由界面引导选择）。"""
    # ① 逃生通道路标
    loc = paths.read_location()
    if loc:
        if paths.is_protected(loc):
            print(f"[warn] 路标目录受保护，忽略：{loc}")
        elif not paths.is_writable(loc):
            print(f"[warn] 路标目录不可写：{loc}")
        else:
            ctx.init_at(loc, escape=True)
            return

    # ② 程序目录下的专属数据文件夹（默认，推荐）
    if paths.app_root_writable():
        root = paths.default_data_root()
        migrate_legacy_layout(paths.app_root(), root)
        ctx.init_at(root, escape=False)
        return

    # ③ 都不行 → 交给用户选择
    print("[warn] 程序目录不可写，等待用户在界面选择数据目录")


def main() -> int:
    if not acquire_single_instance():
        message_box(APP_TITLE, "PriceLens 已经在运行中。")
        return 0

    ctx = AppContext()
    try:
        resolve_data_root(ctx)
        run_window(ctx)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        try:
            if ctx.data_root:
                ctx.log.exception("启动失败")
        except Exception:
            pass
        message_box(APP_TITLE, f"启动失败：\n{exc}\n\n详情见日志文件。", 0x10)
        return 1
    finally:
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())