# -*- coding: utf-8 -*-
"""原生对话框：文件夹选择 + 消息提示。

兼容 pywebview 5.x / 6.x：
  · 6.x 使用 webview.FileDialog.FOLDER
  · 5.x 使用 webview.FOLDER_DIALOG
两者都失败时回退到 Win32 原生 API。
"""
from __future__ import annotations

from typing import Optional


def pick_folder(window, initial: str = "") -> Optional[str]:
    """弹出文件夹选择框，返回绝对路径；取消返回 None。"""
    # 方案 1：pywebview 6.x（FileDialog 枚举）
    try:
        import webview
        folder = getattr(webview, "FileDialog", None)
        if folder is not None and hasattr(folder, "FOLDER"):
            result = window.create_file_dialog(folder.FOLDER, directory=initial or "")
            return _first(result)
    except Exception:
        pass

    # 方案 2：pywebview 5.x（旧常量）
    try:
        import webview
        old = getattr(webview, "FOLDER_DIALOG", None)
        if old is not None:
            result = window.create_file_dialog(old, directory=initial or "")
            return _first(result)
    except Exception:
        pass

    # 方案 3：Win32 原生
    return _pick_folder_win32()


def _first(result) -> Optional[str]:
    if not result:
        return None
    if isinstance(result, (list, tuple)):
        return str(result[0]) if result else None
    return str(result)


def _pick_folder_win32() -> Optional[str]:
    """回退方案：调用 Windows 原生 SHBrowseForFolder。"""
    try:
        import ctypes
        from ctypes import wintypes

        BIF_RETURNONLYFSDIRS = 0x0001
        BIF_NEWDIALOGSTYLE = 0x0040

        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wintypes.HWND),
                ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", wintypes.LPWSTR),
                ("lpszTitle", wintypes.LPCWSTR),
                ("ulFlags", wintypes.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", ctypes.c_void_p),
                ("iImage", ctypes.c_int),
            ]

        shell32 = ctypes.windll.shell32
        ole32 = ctypes.windll.ole32
        try:
            ole32.CoInitialize(None)
        except Exception:
            pass

        buf = ctypes.create_unicode_buffer(260)
        bi = BROWSEINFOW()
        bi.pszDisplayName = ctypes.cast(buf, wintypes.LPWSTR)
        bi.lpszTitle = "请选择 PriceLens 的数据存放目录"
        bi.ulFlags = BIF_RETURNONLYFSDIRS | BIF_NEWDIALOGSTYLE

        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return None
        path_buf = ctypes.create_unicode_buffer(260)
        shell32.SHGetPathFromIDListW(pidl, path_buf)
        try:
            ole32.CoTaskMemFree(pidl)
        except Exception:
            pass
        return path_buf.value or None
    except Exception:
        return None


def message_box(title: str, text: str, flags: int = 0x40) -> None:
    """Win32 消息框（不依赖任何 GUI 框架）。flags: 0x40=信息 0x10=错误"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, flags)
    except Exception:
        print(f"[{title}] {text}")