# -*- coding: utf-8 -*-
"""下载 ECharts 到 web/vendor/（多源自动回退）。

ECharts 仅用于本地渲染价格曲线；下载一次即可，之后完全离线可用。
"""
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "vendor" / "echarts.min.js"

VERSION = "5.4.3"
URLS = [
    f"https://registry.npmmirror.com/echarts/{VERSION}/files/dist/echarts.min.js",
    f"https://cdn.bootcdn.net/ajax/libs/echarts/{VERSION}/echarts.min.js",
    f"https://lib.baomitu.com/echarts/{VERSION}/echarts.min.js",
    f"https://cdn.staticfile.org/echarts/{VERSION}/echarts.min.js",
    f"https://cdn.jsdelivr.net/npm/echarts@{VERSION}/dist/echarts.min.js",
]

MIN_SIZE = 200_000   # 体积下限，用于判断是否下到了错误内容


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.is_file() and OUT.stat().st_size >= MIN_SIZE:
        print(f"已存在（{OUT.stat().st_size} 字节），跳过下载：{OUT}")
        return 0

    for url in URLS:
        print(f"尝试：{url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            data = urllib.request.urlopen(req, timeout=60).read()
        except Exception as exc:
            print(f"  失败：{exc}")
            continue
        if len(data) < MIN_SIZE:
            print(f"  内容过小（{len(data)} 字节），忽略")
            continue
        OUT.write_bytes(data)
        print(f"  完成：{len(data)} 字节 -> {OUT}")
        return 0

    print("全部下载源失败。可手动下载后放到：")
    print(f"  {OUT}")
    return 1


if __name__ == "__main__":
    sys.exit(main())