# -*- coding: utf-8 -*-
"""PriceLens 自检脚本：一次性检查文件、桥接与页面组装。

运行：.venv\Scripts\python.exe tools\doctor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

RESULTS = []


def add(flag, text):
    RESULTS.append((bool(flag), text))


def check(rel, min_size=10):
    p = ROOT / rel
    if not p.is_file():
        add(False, f"{rel} —— 不存在")
        return ""
    size = p.stat().st_size
    if size < min_size:
        add(False, f"{rel} —— 过小（{size} 字节）")
        return ""
    add(True, f"{rel} —— {size} 字节")
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def main():
    add(".venv" in sys.executable, f"解释器：{sys.executable}")
    try:
        import importlib.metadata as md
        add(True, f"pywebview {md.version('pywebview')} / pyinstaller {md.version('pyinstaller')}")
    except Exception as exc:
        add(False, f"依赖读取失败：{exc}")

    html = check("web/index.html")
    base = check("web/css/base.css")
    comp = check("web/css/components.css")
    bjs = check("web/js/bridge.js")
    mjs = check("web/js/main.js")
    win = check("src/ui/window.py")
    brg = check("src/ui/bridge.py")
    wes = check("src/ui/webserver.py")

    if html:
        add("</head>" in html, "index.html 含 </head> 闭合标签")
        add("</body>" in html, "index.html 含 </body> 闭合标签")
        add('class="topbar"' in html, "index.html 含顶部栏")
        n = html.count('class="card"')
        add(n == 4, f"index.html 卡片数量：{n}（应为 4）")
        add("charset" in html[:500].lower(), "index.html 含 charset 声明")
    if comp:
        add("repeat(4,1fr)" in comp, "components.css 含四列网格")
        add(".topbar" in comp, "components.css 含顶部栏样式")
    if base:
        add("--orange" in base, "base.css 含主题变量")
    if bjs:
        add("pywebviewready" in bjs, "bridge.js 含就绪监听")
    if mjs:
        add("PL." in mjs, "main.js 引用桥接对象 PL")
    if win:
        add("start_static_server" in win, "window.py 使用本地服务版本")
    if brg:
        add("self._ctx" in brg and "self.ctx" not in brg.replace("self._ctx", ""),
            "bridge.py 为私有 _ctx 版本")
    if wes:
        add("def build_page" in wes, "webserver.py 含页面组装")

    try:
        from ui.webserver import build_page
        page = build_page(ROOT / "web")
        add(True, f"页面组装：{len(page)} 字符")
        add(page.count("<style>") == 1, f"样式块数量：{page.count('<style>')}（应为 1）")
        add(page.count("<script>") >= 1, f"脚本块数量：{page.count('<script>')}")
    except Exception as exc:
        add(False, f"页面组装失败：{exc}")

    try:
        import paths
        from app_context import AppContext
        from ui.bridge import Bridge
        ctx = AppContext()
        ctx.init_at(paths.default_data_root())
        pub = [a for a in dir(Bridge(ctx)) if not a.startswith("_")]
        add("ctx" not in pub, f"Bridge 公开成员：{pub}")
        ctx.close()
    except Exception as exc:
        add(False, f"桥接检查失败：{exc}")

    lines = []
    bad = 0
    for ok, text in RESULTS:
        if not ok:
            bad += 1
        lines.append(("正常  " if ok else "异常  ") + text)
    out = "\n".join(lines)
    print(out)
    print()
    print(f"===== 自检完成：{len(RESULTS) - bad} 项正常，{bad} 项异常 =====")
    (ROOT / "doctor-report.txt").write_text(out, encoding="utf-8")
    print("报告已写入 doctor-report.txt")


if __name__ == "__main__":
    main()