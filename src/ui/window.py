# -*- coding: utf-8 -*-
"""pywebview 窗口封装与启动（最终方案：本地服务 + 页面组装）。"""
from __future__ import annotations

import webview

import paths
from app_context import AppContext
from const import APP_TITLE
from ui.bridge import Bridge
from ui.webserver import start_static_server, stop_static_server


def run(ctx: AppContext) -> None:
    server = None
    try:
        server, port = start_static_server(paths.web_root(), ctx.port)
    except OSError:
        server, port = start_static_server(paths.web_root(), 0)

    url = f"http://127.0.0.1:{port}/index.html"
    ctx.log.info("界面地址：%s", url)

    webview.create_window(
        APP_TITLE,
        url=url,
        js_api=Bridge(ctx),
        width=1280,
        height=800,
        min_size=(1024, 680),
        text_select=True,
    )

    # WebView2 存储重定向到数据根（S-3 缓存不外泄）
    storage = str(((ctx.data_root or paths.app_root()) / "cache" / "webview").resolve())

    try:
        webview.start(storage_path=storage, private_mode=False, debug=False)
    finally:
        stop_static_server(server)