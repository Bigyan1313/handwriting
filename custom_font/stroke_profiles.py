#!/usr/bin/env python3
"""Extract reusable pen paths and calibrate their weight against a real font.

The sidecar uses source-pixel coordinates (x right, y down). Renderers extend
the middle of a bracket, or the shaft of an arrow, without scaling its pen
width. ``referenceStrokeEm`` is measured from the supplied TTF, not from the
oversized bracket samples. Only Pillow, NumPy and fontTools are required;
SciPy's distance transform is used when available for faster calibration.

    python3 custom_font/stroke_profiles.py --font custom_font/output/BigyanHand-A.ttf \
        --brackets custom_font/brackets_A --arrow custom_font/glyphs_math
"""
import argparse
import heapq
import json
import math
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont


REFERENCE_GLYPHS = "acemnorsu0123456789xXB"
NEIGHBORS = tuple((dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                  if (dy, dx) != (0, 0))


def thin(mask):
    """Deterministic Zhang–Suen thinning; retain bends and connected corners."""
    pixels = np.pad(np.asarray(mask, dtype=bool), 1)
    while True:
        changed = False
        for phase in (0, 1):
            p = pixels[1:-1, 1:-1]
            around = (pixels[:-2, 1:-1], pixels[:-2, 2:], pixels[1:-1, 2:],
                      pixels[2:, 2:], pixels[2:, 1:-1], pixels[2:, :-2],
                      pixels[1:-1, :-2], pixels[:-2, :-2])
            count = sum(v.astype(np.uint8) for v in around)
            transitions = sum((~around[i] & around[(i + 1) % 8]).astype(np.uint8)
                              for i in range(8))
            n, e, s, w = around[0], around[2], around[4], around[6]
            if phase == 0:
                preserve = ~(n & e & s) & ~(e & s & w)
            else:
                preserve = ~(n & e & w) & ~(n & s & w)
            remove = p & (count >= 2) & (count <= 6) & (transitions == 1) & preserve
            if np.any(remove):
                p[remove] = False
                changed = True
        if not changed:
            return pixels[1:-1, 1:-1]


def _edt_1d(values):
    """Squared Euclidean distance transform of one row (linear time)."""
    n = len(values)
    sites = np.empty(n, dtype=int)
    edges = np.empty(n + 1, dtype=float)
    result = np.empty(n, dtype=float)
    k = 0
    sites[0] = 0
    edges[:2] = (-np.inf, np.inf)
    for q in range(1, n):
        v = sites[k]
        boundary = ((values[q] + q * q) - (values[v] + v * v)) / (2 * (q - v))
        while boundary <= edges[k]:
            k -= 1
            v = sites[k]
            boundary = ((values[q] + q * q) - (values[v] + v * v)) / (2 * (q - v))
        k += 1
        sites[k] = q
        edges[k] = boundary
        edges[k + 1] = np.inf
    k = 0
    for q in range(n):
        while edges[k + 1] < q:
            k += 1
        result[q] = (q - sites[k]) ** 2 + values[sites[k]]
    return result


def distance_to_background(mask):
    """Pixel-center distance with a portable exact fallback."""
    padded = np.pad(np.asarray(mask, dtype=bool), 1)
    try:
        from scipy.ndimage import distance_transform_edt
        return distance_transform_edt(padded)[1:-1, 1:-1]
    except ImportError:
        # A finite sentinel avoids inf - inf in the lower-envelope algorithm.
        far = float(sum(v * v for v in padded.shape) + 1)
        work = np.where(padded, far, 0.0)
        for row in range(work.shape[0]):
            work[row] = _edt_1d(work[row])
        for col in range(work.shape[1]):
            work[:, col] = _edt_1d(work[:, col])
        return np.sqrt(work[1:-1, 1:-1])


def _graph(skeleton):
    points = set(map(tuple, np.argwhere(skeleton)))
    graph = {}
    for y, x in points:
        links = []
        for dy, dx in NEIGHBORS:
            neighbor = (y + dy, x + dx)
            if neighbor not in points:
                continue
            # Avoid triangles at orthogonal turns: diagonal shortcuts create
            # false branches and obscure the arrow's real meeting point.
            if dy and dx and ((y + dy, x) in points or (y, x + dx) in points):
                continue
            links.append(neighbor)
        graph[(y, x)] = sorted(links)
    return graph


def _largest_component(graph):
    unseen = set(graph)
    largest = set()
    while unseen:
        todo = [min(unseen)]
        component = set(todo)
        unseen.remove(todo[0])
        while todo:
            point = todo.pop()
            for neighbor in graph[point]:
                if neighbor in unseen:
                    unseen.remove(neighbor)
                    component.add(neighbor)
                    todo.append(neighbor)
        if len(component) > len(largest):
            largest = component
    return {point: graph[point] for point in sorted(largest)}


def _distances(graph, start):
    distances, previous = {start: 0.0}, {}
    queue = [(0.0, start)]
    while queue:
        distance, point = heapq.heappop(queue)
        if distance > distances[point]:
            continue
        for neighbor in graph[point]:
            trial = distance + math.hypot(neighbor[0] - point[0], neighbor[1] - point[1])
            if trial < distances.get(neighbor, math.inf):
                distances[neighbor] = trial
                previous[neighbor] = point
                heapq.heappush(queue, (trial, neighbor))
    return distances, previous


def _path(previous, start, end):
    points = [end]
    while points[-1] != start:
        points.append(previous[points[-1]])
    return list(reversed(points))


def _simplify(points, tolerance=0.85):
    """Ramer–Douglas–Peucker, returned as compact floating x/y coordinates."""
    p = np.asarray([(x, y) for y, x in points], dtype=float)

    def recurse(part):
        if len(part) <= 2:
            return part
        vector = part[-1] - part[0]
        length = float(np.dot(vector, vector))
        if length:
            t = np.clip((part - part[0]) @ vector / length, 0.0, 1.0)
            distances = np.linalg.norm(part - (part[0] + t[:, None] * vector), axis=1)
        else:
            distances = np.linalg.norm(part - part[0], axis=1)
        split = int(np.argmax(distances))
        if distances[split] <= tolerance:
            return part[[0, -1]]
        return np.vstack((recurse(part[:split + 1])[:-1], recurse(part[split:])))

    return [[round(float(x), 3), round(float(y), 3)] for x, y in recurse(p)]


def _load_ink(path):
    with Image.open(path) as image:
        # Composite alpha against white before thresholding scanned samples.
        if image.mode in ("RGBA", "LA"):
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", rgba.size, "white")
            background.alpha_composite(rgba)
            image = background
        mask = np.asarray(image.convert("L")) < 128
    if np.count_nonzero(mask) < 8:
        raise ValueError(f"No usable pen stroke in {path}")
    ys, xs = np.nonzero(mask)
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def bracket_profile(path):
    mask = _load_ink(path)
    graph = _largest_component(_graph(thin(mask)))
    ends = [point for point in graph if len(graph[point]) == 1]
    if len(ends) < 2:
        raise ValueError(f"Bracket must have two open ends: {path}")
    # The longest end-to-end path discards incidental short pen spurs.
    candidates = []
    for start in ends:
        distances, previous = _distances(graph, start)
        end = max(ends, key=lambda point: distances[point])
        candidates.append((distances[end], start, end, previous))
    _, start, end, previous = max(candidates, key=lambda item: item[:3])
    points = _path(previous, start, end)
    if points[0][0] > points[-1][0]:
        points.reverse()
    height, width = mask.shape
    middle = [x for y, x in points if height * .35 < y < height * .65]
    shaft_x = float(np.median(middle))
    top = [y for y, x in points if y < height * .30 and abs(x - shaft_x) > width * .15]
    bottom = [height - 1 - y for y, x in points
              if y > height * .70 and abs(x - shaft_x) > width * .15]
    cap = max(max(top, default=0), max(bottom, default=0)) + 3
    return {"points": _simplify(points), "width": int(width), "height": int(height),
            "capHeight": round(float(min(height * .30, max(cap, height * .06))), 3)}


def arrow_profile(path):
    mask = _load_ink(path)
    full_graph = _graph(thin(mask))
    components = []
    remaining = dict(full_graph)
    while remaining:
        component = _largest_component(remaining)
        if len(component) >= 5:
            components.append(component)
        remaining = {p: links for p, links in remaining.items() if p not in component}
    if len(components) > 1:
        # Some real samples lift the pen between the shaft and arrowhead. Keep
        # both components, connecting their small gap at the original arrow tip.
        shaft_graph = max(components, key=lambda g: max(x for y,x in g)-min(x for y,x in g))
        head_graph = max((g for g in components if g is not shaft_graph), key=lambda g: max(x for y,x in g))
        shaft_ends = [p for p in shaft_graph if len(shaft_graph[p]) == 1]
        head_ends = [p for p in head_graph if len(head_graph[p]) == 1]
        if len(shaft_ends) >= 2 and len(head_ends) >= 2:
            start = min(shaft_ends, key=lambda p: p[1])
            end = max(shaft_ends, key=lambda p: p[1])
            _, previous = _distances(shaft_graph, start)
            shaft = _path(previous, start, end)
            upper, lower = min(head_ends), max(head_ends)
            _, previous = _distances(head_graph, upper)
            head_path = _path(previous, upper, lower)
            tip_index = max(range(len(head_path)), key=lambda i: head_path[i][1])
            tip = head_path[tip_index]
            shaft.append(tip)
            height, width = mask.shape
            return {"shaft": _simplify(shaft),
                    "head": [_simplify(list(reversed(head_path[:tip_index+1]))), _simplify(head_path[tip_index:])],
                    "width": int(width), "height": int(height)}
    graph = max(components, key=len)
    ends = [point for point in graph if len(graph[point]) == 1]
    if len(ends) < 3:
        raise ValueError(f"Right arrow must have a shaft and two open head ends: {path}")
    start = min(ends, key=lambda point: (point[1], point[0]))
    head_ends = [point for point in ends if point != start]
    upper = min(head_ends)
    lower = max(head_ends)
    if upper == lower:
        raise ValueError(f"Cannot separate arrowhead strokes: {path}")
    _, previous = _distances(graph, start)
    to_upper = _path(previous, start, upper)
    to_lower = _path(previous, start, lower)
    shared = 0
    while shared < min(len(to_upper), len(to_lower)) and to_upper[shared] == to_lower[shared]:
        shared += 1
    if shared < 2:
        raise ValueError(f"Cannot find the arrow's shared shaft: {path}")
    shaft = to_upper[:shared]
    head = [to_upper[shared - 1:], to_lower[shared - 1:]]
    height, width = mask.shape
    return {"shaft": _simplify(shaft), "head": [_simplify(part) for part in head],
            "width": int(width), "height": int(height)}


def calibrate_font(font_path, render_em=768):
    """Median body stroke width, excluding endpoints, junctions and thick joins."""
    with TTFont(font_path) as font:
        coverage = font.getBestCmap()
        units = int(font["head"].unitsPerEm)
    raster_font = ImageFont.truetype(str(font_path), render_em)
    glyph_measurements = {}
    for char in REFERENCE_GLYPHS:
        if ord(char) not in coverage:
            continue
        left, top, right, bottom = raster_font.getbbox(char)
        if right <= left or bottom <= top:
            continue
        image = Image.new("L", (right - left + 8, bottom - top + 8), 255)
        ImageDraw.Draw(image).text((4 - left, 4 - top), char, font=raster_font, fill=0)
        mask = np.asarray(image) < 128
        skeleton = thin(mask)
        graph = _graph(skeleton)
        # Remove a five-pixel neighborhood around branch points and stroke
        # endings; neither represents normal pen thickness.
        excluded = {point for point, links in graph.items() if len(links) != 2}
        frontier = set(excluded)
        for _ in range(5):
            frontier = {neighbor for point in frontier for neighbor in graph[point]} - excluded
            excluded.update(frontier)
        clean = [point for point in graph if point not in excluded]
        if len(clean) < 10:
            continue
        distance = distance_to_background(mask)
        # Subtract one raster pixel for distance measured between pixel centers.
        widths = np.asarray([2 * distance[y, x] - 1 for y, x in clean])
        widths = widths[widths >= 2]
        if len(widths):
            glyph_measurements[char] = round(float(np.median(widths)) / render_em, 7)
    if not glyph_measurements:
        raise ValueError(f"Font has no measurable reference letters/digits: {font_path}")
    return units, round(float(np.median(list(glyph_measurements.values()))), 7), glyph_measurements


def generate_profile(font_path, brackets_dir, arrow_dir):
    font_path, brackets_dir, arrow_dir = map(Path, (font_path, brackets_dir, arrow_dir))
    units, reference, glyph_measurements = calibrate_font(font_path)
    return {
        "version": 1,
        "unitsPerEm": units,
        "referenceStrokeEm": reference,
        "brackets": {char: bracket_profile(brackets_dir / f"u{ord(char):04X}.png")
                     for char in "[]"},
        "arrow": arrow_profile(arrow_dir / "u2192.png"),
        "calibration": {"renderEm": 768, "glyphStrokeEm": glyph_measurements,
                        "method": "median-body-centerline-width"},
        "sources": {"font": font_path.name, "brackets": brackets_dir.name,
                    "arrow": arrow_dir.name},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--brackets", type=Path, required=True)
    parser.add_argument("--arrow", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Defaults to FONT.handwriting.json")
    args = parser.parse_args(argv)
    profile = generate_profile(args.font, args.brackets, args.arrow)
    output = args.output or args.font.with_suffix(".handwriting.json")
    output.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
    print(f"{output}: calibrated pen width {profile['referenceStrokeEm']:.5f} em")


if __name__ == "__main__":
    main()
