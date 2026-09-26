# -*- mode: python ; coding: utf-8 -*-
"""PriceLens PyInstaller 打包配置（onedir 模式）。

要点：
  · onedir：不做单文件解包，程序与数据都可控（符合"数据自包含"要求）。
  · 显式收集 pythonnet / clr_loader / pywebview 的资源与隐藏导入：
    这是 pywebview 打包在 Windows 上最常见的坑（缺 .NET 桥会导致启动后无响应）。
  · web/ 前端资源不打包，由 build.bat 复制到 exe 旁（可以直接改界面，不必重打包）。
"""
import os
import pkgutil

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = []
binaries = []
hiddenimports = []

# ---- pythonnet / clr_loader：WebView2 后端的 .NET 桥 ----
for _pkg in ("pythonnet", "clr_loader"):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception as _exc:
        print(f"[spec] 收集 {_pkg} 失败（跳过）：{_exc}")

# ---- pywebview：平台后端 + WebView2 程序集 ----
try:
    import webview.platforms as _wvp
    hiddenimports += [f"webview.platforms.{m.name}"
                      for m in pkgutil.iter_modules(_wvp.__path__)]
except Exception:
    hiddenimports += ["webview.platforms.winforms", "webview.platforms.edgechromium"]

for _sub in ("lib", "js"):
    try:
        datas += collect_data_files("webview", subdir=_sub)
    except Exception:
        pass

# ---- pywebview 官方 hook 目录（双保险） ----
hook_dirs = []
try:
    import importlib.util
    _spec = importlib.util.find_spec("webview")
    if _spec and _spec.origin:
        _d = os.path.join(os.path.dirname(_spec.origin), "__pyinstaller")
        if os.path.isdir(_d):
            hook_dirs.append(_d)
except Exception:
    pass

# ---- 图标（可选：存在 tools\icon.ico 才会用） ----
_icon = os.path.join(ROOT, "tools", "icon.ico")
icon = _icon if os.path.isfile(_icon) else None

a = Analysis(
    [os.path.join(ROOT, "src", "main.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=hook_dirs,
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "pydoc", "doctest", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PriceLens",
    debug=False,
    strip=False,
    upx=False,
    console=False,      # 无黑窗口；排障时可临时改 True
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PriceLens",
)