# -*- coding: utf-8 -*-
"""开发工具：单独启动静态服务，便于在浏览器中验证前端页面。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ui.webserver import start_static_server  # noqa: E402

try:
    server, port = start_static_server(ROOT / "web", 8899)
except OSError:
    server, port = start_static_server(ROOT / "web", 0)

print("=" * 56)
print("  前端预览服务已启动")
print()
print(f"  请在 Edge 浏览器中打开：")
print(f"      http://127.0.0.1:{port}/index.html")
print()
print("  看完之后，回到本窗口按回车键退出")
print("=" * 56)

input()