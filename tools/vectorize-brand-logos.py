"""Trace supplied flat PNG logos to SVG paths (no embedded raster or font dependency).

Usage: python tools/vectorize-brand-logos.py KT.png Kakao.png output-directory
Requires Pillow and numpy. Source files stay untouched.
"""
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np
from PIL import Image


def paths(mask):
    edges = defaultdict(set)
    height, width = mask.shape
    for y, x in zip(*np.nonzero(mask)):
        x, y = int(x), int(y)
        if y == 0 or not mask[y - 1, x]: edges[(x, y)].add((x + 1, y))
        if x == width - 1 or not mask[y, x + 1]: edges[(x + 1, y)].add((x + 1, y + 1))
        if y == height - 1 or not mask[y + 1, x]: edges[(x + 1, y + 1)].add((x, y + 1))
        if x == 0 or not mask[y, x - 1]: edges[(x, y + 1)].add((x, y))
    result = []
    while edges:
        first = next(iter(edges))
        point, direction, contour = first, (1, 0), [first]
        while True:
            candidates = edges[point]
            def rank(next_point):
                dx, dy = next_point[0] - point[0], next_point[1] - point[1]
                cross = direction[0] * dy - direction[1] * dx
                dot = direction[0] * dx + direction[1] * dy
                return 0 if cross > 0 else 1 if dot > 0 else 2 if cross < 0 else 3
            target = min(candidates, key=rank)
            candidates.remove(target)
            if not candidates: del edges[point]
            direction = (target[0] - point[0], target[1] - point[1])
            point = target
            if point == first: break
            contour.append(point)
        # Remove collinear points; retain the source outline and all letter holes.
        clean = []
        for i, b in enumerate(contour):
            a, c = contour[i - 1], contour[(i + 1) % len(contour)]
            if (b[0]-a[0])*(c[1]-b[1]) != (b[1]-a[1])*(c[0]-b[0]): clean.append(b)
        if len(clean) >= 3:
            result.append('M' + 'L'.join(f'{x},{y}' for x,y in clean) + 'Z')
    return ''.join(result)


def save(source, destination, kakao=False):
    img = Image.open(source).convert('RGB')
    width, height = img.size
    if kakao:
        pixels = np.asarray(img)
        background = '#%02x%02x%02x' % tuple(pixels[0, 0])
        layers = [('#000000', np.max(pixels, axis=2) < 120)]
    else:
        background = '#000000'
        indexed = img.quantize(colors=16)
        pixels = np.asarray(indexed)
        palette = indexed.getpalette()
        layers = []
        for index in sorted(np.unique(pixels)):
            color = tuple(palette[index*3:index*3+3])
            if max(color) < 35: continue
            layers.append(('#%02x%02x%02x' % color, pixels == index))
    markup = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">',
              f'<rect width="{width}" height="{height}" fill="{background}"/>']
    for color, mask in layers:
        markup.append(f'<path fill="{color}" fill-rule="evenodd" d="{paths(mask)}"/>')
    markup.append('</svg>')
    destination.write_text('\n'.join(markup), encoding='utf-8')
    print(destination.name, destination.stat().st_size)


if __name__ == '__main__':
    out = Path(sys.argv[3])
    save(sys.argv[1], out / 'kt.svg')
    save(sys.argv[2], out / 'kakao.svg', kakao=True)
