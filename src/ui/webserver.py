# -*- coding: utf-8 -*-
"""本地服务：把 web/ 目录提供给 WebView2 / 浏览器。

三个关键保障（踩坑后的最终方案）：
  1. 强制 UTF-8：所有文本响应都带 charset=utf-8，杜绝中文乱码。
  2. 页面组装：请求 index.html 时把 CSS / JS 内联进 HTML 再返回，
     不依赖外部资源加载。
  3. 收集范围：web/css/*.css 与 web/js/*.js、web/vendor/*.js（放在前面，
     用于 ECharts 这类第三方库）。新增文件放进对应目录即自动生效。
图片等静态文件仍按普通方式提供。仅监听 127.0.0.1。
"""
from __future__ import annotations

import functools
import http.server
import re
import socketserver
import threading
from pathlib import Path
from typing import Optional, Tuple


def _read_text(path: Path) -> str:
    """读取文本文件，自动识别常见编码。"""
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _inject_head(html: str, block: str) -> str:
    """把内容插入头部区域；逐级降级，保证一定插入。"""
    if "</head>" in html:
        return html.replace("</head>", block + "</head>", 1)
    m = re.search(r"<head[^>]*>", html, flags=re.IGNORECASE)
    if m:
        return html[:m.end()] + "\n" + block + html[m.end():]
    m = re.search(r"<body[^>]*>", html, flags=re.IGNORECASE)
    if m:
        return html[:m.end()] + "\n" + block + html[m.end():]
    return block + html


def _inject_tail(html: str, block: str) -> str:
    """把内容插入文档末尾；逐级降级。"""
    for anchor in ("</body>", "</html>"):
        if anchor in html:
            return html.replace(anchor, block + anchor, 1)
    return html + block


def _collect_css(web_dir: Path) -> str:
    css_dir = web_dir / "css"
    if not css_dir.is_dir():
        return ""
    return "\n".join(_read_text(p) for p in sorted(css_dir.glob("*.css")))


def _collect_js(web_dir: Path) -> str:
    """收集顺序：vendor（第三方库）→ js（业务脚本）。"""
    parts = []
    vendor_dir = web_dir / "vendor"
    if vendor_dir.is_dir():
        parts += [_read_text(p) for p in sorted(vendor_dir.glob("*.js"))]
    js_dir = web_dir / "js"
    if js_dir.is_dir():
        parts += [_read_text(p) for p in sorted(js_dir.glob("*.js"))]
    return "\n".join(parts)


def build_page(web_dir: Path) -> str:
    """组装完整页面：内联 CSS / JS，并确保有 charset 声明。"""
    web_dir = Path(web_dir)
    index = web_dir / "index.html"
    if not index.is_file():
        return ("<!doctype html><html><head><meta charset='utf-8'></head>"
                "<body style=\"font-family:Microsoft YaHei;padding:40px\">"
                "<h2>前端资源缺失</h2>"
                f"<p>未找到 {index}</p></body></html>")

    html = _read_text(index)
    css = _collect_css(web_dir)
    js = _collect_js(web_dir)

    # 去掉外部资源引用（改为内联）
    html = re.sub(r"<link[^>]*>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<script[^>]*\bsrc\s*=[^>]*>\s*</script>", "", html, flags=re.IGNORECASE)

    # 无 charset 声明则补一个
    if "charset" not in html[:1000].lower():
        html = _inject_head(html, '<meta charset="utf-8"/>\n')

    # 内联样式与脚本
    if css.strip():
        html = _inject_head(html, "<style>\n" + css + "\n</style>\n")
    if js.strip():
        html = _inject_tail(html, "<script>\n" + js + "\n</script>\n")

    return html


class _Handler(http.server.SimpleHTTPRequestHandler):
    """静态文件服务 + 首页动态组装。"""

    def log_message(self, fmt, *args):
        pass

    def guess_type(self, path):
        ctype = super().guess_type(path)
        if isinstance(ctype, str):
            base = ctype.split(";")[0].strip()
            if base.startswith("text/"):
                return base + "; charset=utf-8"
        return ctype

    def do_GET(self):
        route = self.path.split("?")[0].split("#")[0].rstrip("/")
        if route in ("", "/index.html"):
            self._serve_page()
        else:
            super().do_GET()

    def _serve_page(self):
        try:
            page = build_page(Path(self.directory))
            body = page.encode("utf-8")
            print(f"[serve] 页面已组装: {len(page)} 字符 | "
                  f"样式 {'有' if '<style>' in page else '无'} | "
                  f"脚本 {'有' if '<script>' in page else '无'}")
        except Exception as exc:
            body = f"<h2>页面组装失败</h2><pre>{exc}</pre>".encode("utf-8")
            print(f"[serve] 组装失败: {exc}")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_static_server(directory: Path, port: int = 0) -> Tuple[_Server, int]:
    """启动本地服务。port=0 表示自动分配空闲端口。"""
    directory = Path(directory).resolve()
    handler = functools.partial(_Handler, directory=str(directory))
    httpd = _Server(("127.0.0.1", port), handler)
    actual = int(httpd.server_address[1])
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, actual


def stop_static_server(httpd: Optional[_Server]) -> None:
    if httpd is None:
        return
    try:
        httpd.shutdown()
        httpd.server_close()
    except Exception:
        pass