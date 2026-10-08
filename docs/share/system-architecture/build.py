"""Render the three current diagrams using existing local tools and embedded assets."""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import mimetypes
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
WIDTH, HEIGHT = 1600, 1000
FONT = BASE / "assets/SUIT-Variable.woff2"


def data_uri(path: Path) -> str:
    mime = "image/svg+xml" if path.suffix == ".svg" else mimetypes.guess_type(path)[0]
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def render(page: dict, index: int, colors: dict, brand: str, font64: str) -> tuple[str, list[str]]:
    body: list[str] = []
    labels: list[str] = []

    def text(x, y, value, size=20, weight=400, anchor="start", secondary=False):
        labels.append(value)
        body.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{colors["text-secondary" if secondary else "text-primary"]}" font-weight="{weight}" text-anchor="{anchor}">{html.escape(value)}</text>')

    def image(name, x, y, w, h, kind="icon"):
        uri = data_uri(BASE / "assets" / name)
        body.append(f'<image data-kind="{kind}" x="{x}" y="{y}" width="{w}" height="{h}" href="{uri}" preserveAspectRatio="xMidYMid meet"/>')

    body.append(f'<rect width="{WIDTH}" height="{HEIGHT}" fill="{colors["surface-base"]}"/>')
    text(60, 79, page["title"], 42, 750)
    for zone in page.get("zones", []):
        dash = ' stroke-dasharray="8 7"' if zone.get("status") != "current" else ""
        body.append(f'<rect x="{zone["x"]}" y="{zone["y"]}" width="{zone["w"]}" height="{zone["h"]}" rx="22" fill="{colors["surface-sunken"] if zone.get("status") == "separate" else colors["surface-raised"]}" stroke="{colors["border-control"] if zone.get("status") != "current" else colors["border-subtle"]}"{dash}/>')
        text(zone["x"] + 24, zone["y"] + 34, zone["title"], 21, 650, secondary=True)
    for edge in page["edges"]:
        status = edge.get("status", "current")
        dash = ' stroke-dasharray="9 7"' if status != "current" else ""
        start = f' marker-start="url(#arrow-{index})"' if edge.get("both") else ""
        d = "M " + " L ".join(f"{x} {y}" for x, y in edge["points"])
        body.append(f'<path data-flow="{edge["a"]}-{edge["b"]}" d="{d}" fill="none" stroke="{brand if status == "current" else colors["text-tertiary"]}" stroke-width="3" stroke-linejoin="round"{dash}{start} marker-end="url(#arrow-{index})"/>')
    for node in page["nodes"]:
        x, y, w, h = [node[k] for k in ("x", "y", "w", "h")]
        cx = x + w / 2
        body.append(f'<g data-node="{node["id"]}" aria-label="{html.escape(node["title"] + " " + node.get("tech", ""))}">')
        if node.get("image"):
            text(x, y + 24, node["title"], 25, 700)
            if node.get("miniLogo"):
                image(node["miniLogo"], x + w - 70, y - 6, 70, 35)
            body.append(f'<rect x="{x}" y="{y+42}" width="{w}" height="{h-82}" rx="12" fill="{colors["surface-base"]}" stroke="{colors["border-control"]}"/>')
            image(node["image"], x + 8, y + 50, w - 16, h - 98, "screen")
            text(x, y + h - 10, node["tech"], 18, secondary=True)
        else:
            if node.get("kind") == "gate":
                body.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="18" fill="{colors["surface-base"]}" stroke="{brand}" stroke-width="2"/>')
            size = node.get("iconSize", 94)
            offset = node.get("titleOffset", 124)
            if node.get("logo") == "fastapi.svg":
                body.append(f'<circle cx="{cx}" cy="{y+2+size/2}" r="{size/2-2}" fill="{brand}"/>')
            image(node.get("logo", "role-" + node.get("icon", "server") + ".svg"), cx - size / 2, y + 2, size, size)
            if node.get("miniLogo"):
                image(node["miniLogo"], x + w - 70, y, 70, 32)
            text(cx, y + offset, node["title"], node.get("titleSize", 24), 700, "middle")
            if node.get("tech"):
                text(cx, y + offset + 28, node["tech"], node.get("techSize", 18), anchor="middle", secondary=True)
            if node.get("badge"):
                text(cx, y + offset + 56, node["badge"], 18, 650, "middle", True)
        body.append("</g>")
    for edge in page["edges"]:
        if edge.get("label"):
            body.append('<g data-edge-label="true">')
            text(edge["lx"], edge["ly"], edge["label"], 18, anchor="middle", secondary=True)
            body.append("</g>")
    for note in page.get("captions", []):
        text(note[1], note[2], note[0], note[3] if len(note) > 3 else 19, secondary=True)
    body.append(f'<path d="M 60 928 H 1540" stroke="{colors["border-subtle"]}"/>')
    for x, label, status, icon in [(60, "현재", "current", "check-check"), (240, "별도 · 승인 후", "approval", "lock-keyhole"), (570, "목표 · 미구현", "target", "cloud")]:
        image("role-" + icon + ".svg", x, 947, 25, 25)
        dash = ' stroke-dasharray="6 5"' if status != "current" else ""
        body.append(f'<path d="M {x+36} 960 H {x+94}" stroke="{brand}" stroke-width="3"{dash}/>')
        text(x + 108, 967, label, 19)
    text(1540, 967, "2026-10-08 · 현재 로컬 구현", 18, anchor="end", secondary=True)
    defs = f'''<defs><style>@font-face{{font-family:DiagramSUIT;src:url(data:font/woff2;base64,{font64}) format('woff2');font-weight:100 900}} text{{font-family:DiagramSUIT,system-ui,sans-serif}} [data-edge-label] text{{paint-order:stroke;stroke:{colors['surface-raised']};stroke-width:8px;stroke-linejoin:round}}</style><marker id="arrow-{index}" viewBox="0 0 12 12" refX="11" refY="6" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 2 2 L 10 6 L 2 10" fill="none" stroke="{brand}" stroke-width="1.8"/></marker></defs>'''
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{page["title"]}"><title>{page["title"]}</title><desc>{html.escape(page["description"])}</desc>{defs}{"".join(body)}</svg>'
    return svg, labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", type=Path, help="Existing Chromium executable; no browser install")
    args = parser.parse_args()
    from playwright.sync_api import sync_playwright
    import pymupdf
    from PIL import Image

    data = json.loads((BASE / "diagrams.json").read_text())
    tokens = json.loads((ROOT / "docs/design/tokens.json").read_text())["color"]
    colors = {k: v["$value"] for k, v in tokens["neutral"].items()}
    brand = tokens["brand"]["primary"]["$value"]
    font64 = base64.b64encode(FONT.read_bytes()).decode()
    manifest = json.loads((BASE / "assets/manifest.json").read_text())
    for asset in manifest["assets"]:
        path = BASE / "assets" / asset["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != asset["sha256"]:
            raise RuntimeError(f"Asset differs from manifest: {path}")
        if asset.get("notice") and not (BASE / "assets" / asset["notice"]).exists():
            raise RuntimeError(f"Missing notice: {asset['notice']}")
    out = BASE / "out"
    out.mkdir(exist_ok=True)
    source_md = ["# 구조도 원문", "", "`diagrams.json`의 같은 노드·간선으로 그림과 Mermaid를 생성합니다. 실선: 현재. 점선: 별도·승인 후 또는 목표. 구현 표시는 실호출 승인이나 전체 수용 기준 통과가 아닙니다.", ""]
    svgs, metrics = [], []
    baseline = {p["id"]: p for p in json.loads((BASE / "assets/text-baseline.json").read_text())["pages"]}
    for index, page in enumerate(data["pages"], 1):
        mmd = ["flowchart LR"]
        for node in page["nodes"]:
            label = html.escape(node["title"] + "<br/>" + node.get("tech", ""), quote=False).replace("&lt;br/&gt;", "<br/>")
            mmd.append(f'  {node["id"]}["{label}"]')
        for edge in page["edges"]:
            op = "-.->" if edge.get("status", "current") != "current" else "<-->" if edge.get("both") else "-->"
            mmd.append(f'  {edge["a"]} {op}|"{edge.get("label", "")}"| {edge["b"]}')
        (BASE / f"{page['id']}.mmd").write_text("\n".join(mmd) + "\n")
        source_md.extend([f"## {index}. {page['title']}", "", page["description"], "", "```mermaid", *mmd, "```", ""])
        svg, labels = render(page, index, colors, brand, font64)
        (out / f"{page['id']}.svg").write_text(svg)
        svgs.append(svg)
        authored_chars = sum(len("".join(label.split())) for label in labels)
        baseline_chars = baseline[page["id"]]["visibleTextCharactersWithoutWhitespace"]
        metrics.append({"id": page["id"], "baselineVisibleTextCharacters": baseline[page["id"]]["visibleTextCharacters"], "visibleTextCharacters": sum(len(label) for label in labels), "baselineCharactersWithoutWhitespace": baseline_chars, "charactersWithoutWhitespace": authored_chars, "textRatioWithoutWhitespace": round(authored_chars / baseline_chars, 4), "primaryRoles": sum(n.get("role") != "support" for n in page["nodes"]), "supportRoles": sum(n.get("role") == "support" for n in page["nodes"]), "nodeCount": len(page["nodes"]), "edgeCount": len(page["edges"])})
    (BASE / "diagrams.md").write_text("\n".join(source_md))
    document = '<!doctype html><html lang="ko"><meta charset="utf-8"><title>줍 시스템 구조도</title><style>@page{size:1600px 1000px;margin:0}html,body{margin:0}section{width:1600px;height:1000px;break-after:page}section:last-child{break-after:auto}svg{display:block}</style>' + ''.join(f'<section>{svg}</section>' for svg in svgs) + '</html>'
    (out / "system-architecture.html").write_text(document)
    requests = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=str(args.chromium) if args.chromium else None)
        tab = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        tab.route("http://**/*", lambda route: (requests.append(route.request.url), route.abort()))
        tab.route("https://**/*", lambda route: (requests.append(route.request.url), route.abort()))
        tab.goto((out / "system-architecture.html").as_uri())
        tab.evaluate("document.fonts.ready")
        checks = tab.evaluate('''() => [...document.querySelectorAll('svg')].map(svg => {
          const texts=[...svg.querySelectorAll('text')].map(t=>({text:t.textContent,b:t.getBBox()}));
          const overlaps=[]; for(let i=0;i<texts.length;i++)for(let j=i+1;j<texts.length;j++){
            const a=texts[i].b,b=texts[j].b;if(Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>1 && Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>1)overlaps.push([texts[i].text,texts[j].text]);}
          const images=[...svg.querySelectorAll('image')];
          const imageTextOverlaps=[];for(const image of images){const a=image.getBBox();for(const t of texts){const b=t.b;if(Math.min(a.x+a.width,b.x+b.width)-Math.max(a.x,b.x)>1&&Math.min(a.y+a.height,b.y+b.height)-Math.max(a.y,b.y)>1)imageTextOverlaps.push(t.text);}}
          return {textOutsidePage:texts.filter(({b})=>b.x<0||b.y<0||b.x+b.width>1600||b.y+b.height>1000).map(t=>t.text),textOverlaps:overlaps,imageTextOverlaps,embeddedImages:images.length,screenImages:images.filter(i=>i.dataset.kind==='screen').length,imageAreaFraction:images.reduce((s,i)=>s+i.width.baseVal.value*i.height.baseVal.value,0)/(1600*1000),textBoxAreaFraction:texts.reduce((s,t)=>s+t.b.width*t.b.height,0)/(1600*1000),nonEmbeddedImages:images.filter(i=>!i.getAttribute('href').startsWith('data:')).length};})''')
        for item, check in zip(metrics, checks):
            item.update(check)
        if any(c["textOutsidePage"] or c["textOverlaps"] or c["imageTextOverlaps"] or c["nonEmbeddedImages"] for c in checks):
            raise RuntimeError(f"Diagram layout failed: {checks}")
        if requests:
            raise RuntimeError(f"Unexpected remote request: {requests}")
        tab.pdf(path=str(out / "system-architecture.pdf"), print_background=True, prefer_css_page_size=True)
        browser.close()
    with pymupdf.open(out / "system-architecture.pdf") as pdf:
        if len(pdf) != 3:
            raise RuntimeError(f"Expected 3 pages, got {len(pdf)}")
        for i, page in enumerate(pdf):
            page.get_pixmap(matrix=pymupdf.Matrix(4 / 3, 4 / 3)).save(out / f"{data['pages'][i]['id']}.png")
        font_names = sorted({f[3] or f"{f[2]} embedded glyph programs" for page in pdf for f in page.get_fonts()})
        missing_glyphs = [c for page in pdf for c in page.get_text() if c == '\ufffd']
    contact = Image.new("RGB", (1600, 3060), colors["surface-base"])
    for i, page in enumerate(data["pages"]):
        im = Image.open(out / f"{page['id']}.png").convert("RGB")
        im.thumbnail((1600, 1000))
        contact.paste(im, (0, i * 1020))
    contact.save(out / "contact-sheet.png")
    report = {"pdfPages": 3, "remoteNetworkRequests": len(requests), "manifestAssets": len(manifest["assets"]), "missingAssets": 0, "fonts": font_names, "replacementGlyphs": len(missing_glyphs), "metricsMethod": "Unicode SVG text characters including spaces; excludes raster screenshot text; areas are summed SVG image/text bounding rectangles, not ink or usability scores", "pages": metrics}
    (out / "visual-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
