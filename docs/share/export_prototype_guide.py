"""Export the prototype guide with existing Pandoc, Playwright, PyMuPDF and Chromium only.

No dependency/browser installation, model request, env-file loading or application startup.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import urllib.parse
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
FONT = ROOT / "prototype/web/node_modules/@sun-typeface/suit/fonts/variable/woff2/SUIT-Variable.woff2"
LICENSE = BASE / "system-architecture/SUIT-LICENSE.txt"

CSS = """<style>
@font-face{font-family:GuideSUIT;src:url(data:font/woff2;base64,__FONT__) format('woff2');font-weight:100 900}
@page{size:A4 landscape;margin:13mm 15mm}
html{color:#1b2926;background:#fff}
body{font-family:GuideSUIT,'Apple SD Gothic Neo',sans-serif;font-size:12px;line-height:1.6;max-width:1200px;margin:32px auto;padding:0 24px}
h1{font-size:30px;line-height:1.25;margin:20px 0}
h2{font-size:21px;margin-top:32px;border-top:1px solid #cad6d2;padding-top:14px}
h3{font-size:16px;margin-top:24px}
p,li{orphans:3;widows:3}
a{color:#0a5c48;text-underline-offset:2px}
blockquote{border-left:3px solid #0a5c48;padding:0 14px;margin:20px 0;color:#394f47}
header#title-block-header{display:none}
table{display:table;border-collapse:collapse;width:100%;font-size:11px;margin:15px 0}
th,td{border:1px solid #cad6d2;padding:7px 9px;vertical-align:top;overflow-wrap:anywhere}
th{background:#eef3f1;text-align:left}
tr{break-inside:avoid}thead{display:table-header-group}
code{font-family:ui-monospace,'SFMono-Regular',monospace;font-size:.94em;overflow-wrap:anywhere}
pre{background:#f3f6f4;border:1px solid #dce5e1;padding:12px;white-space:pre-wrap;break-inside:avoid;overflow-wrap:anywhere}
pre code{font-size:10px}
h1,h2,h3{break-after:avoid}img{max-width:100%}
@media print{body{margin:0;padding:0;max-width:none;font-size:11px}h2{font-size:19px;margin-top:24px}table{font-size:10px}a{color:inherit}}
</style>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", type=Path, required=True, help="Existing Chromium executable; never installs a browser")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright
    import pymupdf

    if not args.chromium.is_file():
        parser.error("--chromium must point to an existing executable")
    source = BASE / "prototype-guide.md"
    html_path = BASE / "prototype-guide.html"
    pdf_path = BASE / "prototype-guide.pdf"
    pages_path = BASE / "prototype-guide-pages"
    result = subprocess.run(
        ["pandoc", str(source), "--from=gfm", "--to=html5", "--standalone",
         "--metadata=title:줍 프로토타입 설명서", "--metadata=lang:ko"],
        check=True, capture_output=True, text=True,
    )
    style = CSS.replace("__FONT__", base64.b64encode(FONT.read_bytes()).decode())
    license_comment = "<!-- " + LICENSE.read_text().replace("--", "—") + " -->"
    html_path.write_text(result.stdout.replace("</head>", style + license_comment + "</head>"), encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(args.chromium))
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.route("http://**/*", lambda route: route.abort())
            page.route("https://**/*", lambda route: route.abort())
            page.goto(html_path.as_uri())
            page.evaluate("document.fonts.ready")
            if not page.evaluate("[...document.fonts].some(f => f.family === 'GuideSUIT' && f.status === 'loaded')"):
                raise RuntimeError("Embedded SUIT font did not load")
            assets = page.evaluate("[...document.querySelectorAll('[src],link[rel=stylesheet]')].map(e=>e.getAttribute('src')||e.getAttribute('href'))")
            if assets:
                raise RuntimeError(f"Guide must have no external asset references: {assets}")
            page.pdf(path=str(pdf_path), print_background=True, prefer_css_page_size=True)
        finally:
            browser.close()

    # Chrome emits absolute file-launch links. Make the repository bundle portable
    # without retaining obsolete absolute link objects in an incremental PDF save.
    portable = pdf_path.with_suffix(".portable.pdf")
    with pymupdf.open(pdf_path) as pdf:
        for page in pdf:
            for link in page.get_links():
                if link.get("file", "").startswith(str(ROOT) + "/"):
                    # A file-launch action cannot address a Markdown heading. Avoid
                    # turning its URL fragment into a percent-encoded filename.
                    attachment = urllib.parse.unquote(link["file"]).split("#", 1)[0]
                    link["file"] = os.path.relpath(attachment, BASE)
                    page.update_link(link)
        pdf.save(portable, garbage=4, deflate=True)
    portable.replace(pdf_path)
    pages_path.mkdir(exist_ok=True)
    with pymupdf.open(pdf_path) as pdf:
        count = len(pdf)
        for i, page in enumerate(pdf, 1):
            page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5)).save(pages_path / f"{i:02d}.png")
        # Only numbered proof images owned by this exporter can become obsolete.
        for path in pages_path.glob("[0-9][0-9].png"):
            if int(path.stem) > count:
                path.unlink()
    print(json.dumps({"guidePdfPages": count, "externalAssets": [], "relativeAttachmentLinks": True,
                      "html": str(html_path.relative_to(ROOT)), "pdf": str(pdf_path.relative_to(ROOT))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
