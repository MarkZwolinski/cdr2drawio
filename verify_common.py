#!/usr/bin/env python3
"""Shared helpers for verify*.py: PNG decode, drawio parse, content-bbox
derivation and svg<->image mapping.  Every verify script takes the same args:

    python3 verifyX.py [--drawio F] [--render PNG] [--thumb PNG]
                       [--content X0 Y0 X1 Y1]

Defaults point at regenerated cpu2 artifacts (see DEFAULT_* below; override
with the VC_DRAWIO / VC_RENDER / VC_THUMB environment variables).

Mapping conventions
-------------------
drawio stores geometry in page px (1/100 mm); a render exported with
`drawio -x -f png -s 2` maps svg units u (1/100 mm) to page px as u*K, then to
render px as u*K*SCALE.  A thumbnail is a content-cropped bitmap; its visible
region is the union bbox of all objects, optionally snapped to the thumbnail
aspect so the two images line up.
"""
import argparse
import math
import os
import re
import struct
import zlib

K = 96.0 / 2540.0          # svg (1/100 mm) -> page px
SCALE = 2                  # draw.io export scale
DARK = 180                 # default ink threshold

DEFAULT_DRAWIO = '/tmp/cpu2_v.drawio'
DEFAULT_RENDER = '/tmp/cpu2_v_render.png'
DEFAULT_THUMB = '/tmp/cpu2_thumb.png'


def read_png(path):
    """Decode a (non-interlaced, 8-bit) PNG. Returns (w, h, nch, rows) with
    RGB rows except nch==1 (grayscale). Color-indexed images are expanded."""
    data = open(path, 'rb').read()
    o = 8; idat = b''; w = h = bd = ct = 0; palette = None; trns = None
    while o < len(data):
        ln = struct.unpack('>I', data[o:o+4])[0]
        typ = data[o+4:o+8]; ch = data[o+8:o+8+ln]; o += 12 + ln
        if typ == b'IHDR':
            w, h, bd, ct = struct.unpack('>IIBB', ch[:10])
        elif typ == b'PLTE':
            palette = [tuple(ch[i:i+3]) for i in range(0, len(ch), 3)]
        elif typ == b'tRNS':
            trns = ch
        elif typ == b'IDAT':
            idat += ch
        elif typ == b'IEND':
            break
    raw = zlib.decompress(idat)
    nch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    bpp = nch * (bd // 8); stride = w * bpp
    rows = []; prev = bytearray(stride); i = 0
    for y in range(h):
        f = raw[i]; i += 1
        line = bytearray(raw[i:i+stride]); i += stride
        for x in range(stride):
            a = line[x-bpp] if x >= bpp else 0
            b = prev[x]; c = prev[x-bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + (a + b) // 2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        rows.append(bytes(line)); prev = line
    if ct == 3 and palette:
        rgb = []
        alpha = trns if trns is not None else None
        for y in range(h):
            row = bytearray()
            for x in range(w):
                idx = rows[y][x]
                r, g, b = palette[idx]
                if alpha is not None and idx < len(alpha) and alpha[idx] < 128:
                    r = g = b = 255
                row += bytes((r, g, b))
            rgb.append(bytes(row))
        return w, h, 3, rgb
    return w, h, nch, rows


def lum(rows, nch, x, y, w, h):
    x, y = int(x), int(y)
    if not (0 <= x < w and 0 <= y < h):
        return 255.0
    p = rows[y][x*nch:(x+1)*nch]
    if nch == 1:
        return float(p[0])
    return 255.0 if len(p) < 3 else (p[0] + p[1] + p[2]) / 3.0


def dark(rows, nch, x, y, w, h, thr=DARK):
    return lum(rows, nch, x, y, w, h) < thr


def dark_near(rows, nch, w, h, px, py, rad=2, thr=DARK):
    px, py = int(round(px)), int(round(py))
    for dy in range(-rad, rad+1):
        for dx in range(-rad, rad+1):
            if lum(rows, nch, px+dx, py+dy, w, h) < thr:
                return True
    return False


def parse_drawio(xml_path):
    """Return a list of cell dicts: {id, val, style, pts, geo}.
    pts: page-px points (sourcePoint, waypoints, targetPoint, or free points);
    geo: (x, y, w, h) page px for vertex cells (or None)."""
    xml = open(xml_path, encoding='utf-8').read()
    cells = []
    for m in re.finditer(r'<mxCell id="([a-z]+\d+)" value="([^"]*)" style="([^"]*)"'
                         r'[^>]*>(.*?)</mxCell>', xml, re.S):
        cid, val, style, body = m.group(1), m.group(2), m.group(3), m.group(4)
        pts = []
        sp = re.search(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)" as="sourcePoint"', body)
        am = re.search(r'<Array as="points">(.*?)</Array>', body, re.S)
        tp = re.search(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)" as="targetPoint"', body)
        if sp:
            pts.append((float(sp.group(1)), float(sp.group(2))))
            if am:
                pts += [(float(a), float(b)) for a, b in
                        re.findall(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)"', am.group(1))]
            if tp:
                pts.append((float(tp.group(1)), float(tp.group(2))))
        else:
            pts = [(float(a), float(b)) for a, b in
                   re.findall(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)"', body)]
        geo = re.search(r'<mxGeometry x="([-\d.]+)" y="([-\d.]+)"'
                        r' width="([-\d.]+)" height="([-\d.]+)"', body)
        cells.append(dict(id=cid, val=val, style=style, pts=pts,
                          geo=tuple(float(v) for v in geo.groups()) if geo else None))
    return cells


def content_bbox(cells, snap_to=None):
    """Union bbox (svg units) of all cells. If snap_to=(tw, th) and the union
    aspect differs from the thumbnail's, trim the over-long axis on the far
    (max) side, anchored at the min corner."""
    x0 = y0 = 1e18; x1 = y1 = -1e18
    for c in cells:
        if c['geo']:
            x, y, w, h = c['geo']
            x0 = min(x0, x); y0 = min(y0, y)
            x1 = max(x1, x+w); y1 = max(y1, y+h)
        for x, y in c['pts']:
            x0 = min(x0, x); y0 = min(y0, y)
            x1 = max(x1, x); y1 = max(y1, y)
    x0, y0, x1, y1 = x0/K, y0/K, x1/K, y1/K
    if snap_to:
        tw, th = snap_to
        w = x1 - x0; h = y1 - y0
        if w > h * tw / th:
            x1 = x0 + h * tw / th
        elif h > w * th / tw:
            y1 = y0 + w * th / tw
    return x0, y0, x1, y1


def add_args(parser):
    parser.add_argument('--drawio', default=os.environ.get('VC_DRAWIO', DEFAULT_DRAWIO),
                        help='drawio source (default: %(default)s)')
    parser.add_argument('--render', default=os.environ.get('VC_RENDER', DEFAULT_RENDER),
                        help='drawio PNG export (default: %(default)s)')
    parser.add_argument('--thumb', default=os.environ.get('VC_THUMB', DEFAULT_THUMB),
                        help='Corel thumbnail PNG (default: %(default)s)')
    parser.add_argument('--content', nargs=4, type=float, metavar=('X0', 'Y0', 'X1', 'Y1'),
                        help='content bbox in svg units (default: derived from drawio)')


class V:
    """Verification context: images, cells, content bbox, mappings."""

    def __init__(self, args, snap=True):
        self.rw, self.rh, self.rn, self.R = read_png(args.render)
        self.tw, self.th, self.tn, self.T = read_png(args.thumb)
        self.cells = parse_drawio(args.drawio)
        self.C = tuple(args.content) if args.content \
            else content_bbox(self.cells, (self.tw, self.th) if snap else None)

    def to_r(self, sx, sy):
        return sx * K * SCALE, sy * K * SCALE

    def to_t(self, sx, sy):
        return ((sx - self.C[0]) / (self.C[2] - self.C[0]) * self.tw,
                (sy - self.C[1]) / (self.C[3] - self.C[1]) * self.th)

    def tdims(self):
        return self.tw, self.th