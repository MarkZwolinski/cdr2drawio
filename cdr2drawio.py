#!/usr/bin/env python3
"""Convert a CorelDRAW (.cdr) drawing to draw.io XML (.drawio).

The container is decoded directly; nothing is recovered by rendering:

  - modern ZCF container: ZIP; content/root.dat is a RIFF 'CDR*' object
    directory, content/data/page1.dat the payload stream; leaf payloads are
    redirected (16-byte wrapper -> [stream, len, ofs, pad] into page1.dat).
  - legacy containers: the .cdr file is itself a RIFF body (e.g. 'CDR7',
    'CDR8'); leaf payloads are inline. Very old drawings may compress the
    whole body into a top-level LIST cmpr (two zlib 'CPng' streams: the
    content and a pool of chunk sizes).

  - object directory: LIST chunks; an object is a LIST typed 'obj ' (shape or
    text) or 'lnkg' (connector). Its records are leaves (bbox, loda, txsm, ...).
  - page frame: the page LIST has a 'bbox' leaf holding 4 x int32
    (x0, y_top, x1, y_bottom) in Corel units (1/10000 mm). The document origin
    (raw 0,0) is treated as the centre of the output page, which yields the
    svg transform
        x = ox + (v - page_x0) / 100      y = oy - (v - page_ytop) / 100
    with (ox, oy) the rounded svg position of the page's top-left corner.
  - shape geometry: the loda chunk holds an argument table
    [chunk_length, num_of_args, start_of_args, start_of_arg_types,
     chunk_type_int]; the arg of type 30 holds the point list. Local points
    are mapped through the object's trfd matrix onto the page. Bezier points
    are sampled from their control points. Ellipse objects (chunk type 2) are
    drawn from their bbox.
  - connectors ('lnkg'): no loda geometry; the two endpoints are read from the
    nested obj/npps/ppdt record (int32 x0,y0,x1,y1 at byte 8). Arrow direction
    comes from the outline JSON leftArrow/rightArrow fields.
  - shapes carry stroke colour in outline.color (modern) or default to Corel
    black; texts carry font name/size in the txsm JSON (modern) or in the
    binary txsm_7 style records (legacy; size falls back to the bbox height).
  - text string is at the txsm tail (modern [u32 len][bytes][5 x 00]) or parsed
    from txsm_7 paragraphs; bbox = typographic box.

Colours are CMYK strings ("CMYK,USER,c,m,y,k,...") converted to RGB; Corel
renders pure K100 black as a rich black, reproduced by COREL_BLACK.

The output page is A4 (794 x 1123 px); px = svg_units * 96 / 2540.
"""

import json
import os
import re
import struct
import sys
import zipfile
import zlib

SCALE = 96.0 / 2540.0  # svg units (1/100 mm) -> px @96dpi
PAGE_W_SVG = 21000.0   # A4 width in svg units (1/100 mm)
PAGE_H_SVG = 29700.0   # A4 height in svg units
COREL_BLACK = "#1B1918"  # Corel K100 as rendered
ARROW_END_SIZE = "6"


def px(v):
    return round(v * SCALE, 2)


# Arial advance widths (per mille em) for natural text width estimation
ARIAL = {
    " ": 278, "!": 278, '"': 355, "#": 556, "$": 556, "%": 889, "&": 667, "'": 191,
    "(": 333, ")": 333, "*": 389, "+": 584, ",": 278, "-": 333, ".": 278, "/": 278,
    "0": 556, "1": 556, "2": 556, "3": 556, "4": 556, "5": 556, "6": 556, "7": 556,
    "8": 556, "9": 556, ":": 278, ";": 278, "<": 584, "=": 584, ">": 584, "?": 556,
    "@": 1015, "A": 667, "B": 667, "C": 722, "D": 722, "E": 667, "F": 611, "G": 778,
    "H": 722, "I": 278, "J": 500, "K": 667, "L": 556, "M": 833, "N": 722, "O": 778,
    "P": 667, "Q": 778, "R": 722, "S": 667, "T": 611, "U": 722, "V": 667, "W": 944,
    "X": 667, "Y": 667, "Z": 611, "[": 278, "\\": 278, "]": 278, "^": 469, "_": 556,
    "`": 333, "a": 556, "b": 556, "c": 500, "d": 556, "e": 556, "f": 278, "g": 556,
    "h": 556, "i": 222, "j": 222, "k": 500, "l": 222, "m": 833, "n": 556, "o": 556,
    "p": 556, "q": 556, "r": 333, "s": 500, "t": 278, "u": 556, "v": 500, "w": 722,
    "x": 500, "y": 500, "z": 500, "{": 334, "|": 260, "}": 334, "~": 584,
}


def cmyk_to_hex(color):
    """Convert a Corel 'CMYK,USER,c,m,y,k,...' string to #RRGGBB.

    Uses an additive ink-stacking model (r = 1 - min(1, channel + k), as in
    Ghostscript's default CMYK->RGB) instead of the naive per-channel
    multiply, which darkens colours that combine CMYK with black. Pure K100
    is Corel's rich black (COREL_BLACK)."""
    if not color:
        return COREL_BLACK
    parts = color.split(",")
    try:
        if parts[0] == "CMYK":
            c, m, y, k = (float(parts[i]) for i in (2, 3, 4, 5))
            if k >= 100 and c <= 0 and m <= 0 and y <= 0:
                return COREL_BLACK  # Corel's rich black
            r = round(255 * (1 - min(100.0, c + k) / 100.0))
            g = round(255 * (1 - min(100.0, m + k) / 100.0))
            b = round(255 * (1 - min(100.0, y + k) / 100.0))
            r = max(0, min(255, r)); g = max(0, min(255, g)); b = max(0, min(255, b))
            return "#%02X%02X%02X" % (r, g, b)
    except (ValueError, IndexError):
        pass
    return COREL_BLACK


def _parse_version(marker):
    """Corel version from the 4-byte form type at a RIFF body's offset 8."""
    c = marker[3]
    if marker[:3] == b"cdr" and c == 0x38:
        return 801
    if c == 0x20:
        return 300
    if c < 0x31:
        return 0
    if c < 0x3A:
        return 100 * (c - 0x30)
    if c < 0x41:
        return 0
    if c < 0x49:
        return 100 * (c - 0x37)
    if c == 0x49:
        return 0
    return 100 * (c - 0x38)


class Cdr:
    def __init__(self, path):
        data = open(path, "rb").read()
        self.page = None
        if data[:4] == b"RIFF":
            # Legacy container: the RIFF body is the file itself.
            self.root = data
            self.redirect = False
        else:
            # ZCF container: root.dat is a RIFF body, payload in page1.dat.
            zf = zipfile.ZipFile(path)
            self.root = zf.read("content/root.dat")
            self.page = zf.read("content/data/page1.dat")
            self.redirect = True
        self.version = _parse_version(self.root[8:12])
        if self.version >= 1600:
            self.redirect = True
        self.nodes = []
        self.buf = self.root
        self._pool = None
        cmpr = self._big_cmpr()
        if cmpr is not None:
            self._walk_compressed(cmpr)
        else:
            end = 8 + struct.unpack_from("<I", self.root, 4)[0]
            self._walk(12, end, "")
        self.fonts = self._read_fonts()
        self.objs = [
            n for n in self.nodes
            if n["name"] == "LIST" and n["path"] == "/page/gobj/layr"
            and n["typ"].strip() in ("obj", "lnkg")
        ]
        self._set_transform()

    def _big_cmpr(self):
        """Offset of the top-level LIST cmpr holding the compressed body."""
        end = 8 + struct.unpack_from("<I", self.root, 4)[0]
        off = 12
        found = None
        while off + 8 <= end:
            size = struct.unpack_from("<I", self.root, off + 4)[0]
            if (self.root[off:off + 4] == b"LIST"
                    and self.root[off + 8:off + 12] == b"cmpr"):
                payload = self.root[off + 12:off + 12 + size - 4]
                if len(payload) >= 4 and struct.unpack_from("<I", payload, 0)[0] > 64:
                    found = off
            off += 8 + size + (size & 1)
        return found

    def _walk_compressed(self, cmpr):
        """Legacy `cmpr` LIST: two zlib streams (body + chunk-size pool)."""
        size = struct.unpack_from("<I", self.root, cmpr + 4)[0]
        payload = self.root[cmpr + 12:cmpr + 12 + size - 4]
        i1 = payload.find(b"CPng")
        i2 = payload.find(b"CPng", i1 + 4)
        d = zlib.decompressobj()
        content = d.decompress(payload[i1 + 8:])
        pool = zlib.decompress(payload[i2 + 8:])
        self.buf = content
        self._pool = pool

        def walk(o, e, path):
            while o + 8 <= e:
                cid = content[o:o + 4]
                idx = struct.unpack_from("<I", content, o + 4)[0]
                body_len = struct.unpack_from("<I", pool, idx * 4)[0]
                q = o + 8
                if cid == b"LIST":
                    ft = content[q:q + 4].decode("latin1")
                    self.nodes.append(dict(path=path, name="LIST", off=q,
                                           size=body_len, typ=ft))
                    if ft != "stlt":  # stlt body is not a chunk sequence
                        walk(q + 4, q + body_len, path + "/" + ft)
                else:
                    self.nodes.append(dict(path=path, name=cid.decode("latin1"),
                                           off=q, size=body_len, typ=""))
                o += 8 + body_len + (body_len & 1)

        walk(0, len(content), "")

    def _set_transform(self):
        """Map Corel units to svg units using the page frame bbox.

        The document origin is placed at the centre of the output page; the
        page's top-left corner is rounded to an integer svg coordinate.
        """
        box = self.page_bbox()
        x0, ytop = (box[0], box[1]) if box else (0, 0)
        self._raw_x0, self._raw_ytop = x0, ytop
        self._ox = round(PAGE_W_SVG / 2.0 + x0 / 100.0)
        self._oy = round(PAGE_H_SVG / 2.0 - ytop / 100.0)

    def page_bbox(self):
        boxes = []
        for n in self.nodes:
            if n["name"] == "bbox" and n["path"] == "/page":
                raw = self.deref(n)
                if len(raw) >= 16:
                    boxes.append(struct.unpack_from("<4i", raw))
        if not boxes:
            return None
        boxes.sort(key=lambda b: (b[2] - b[0]) * (b[1] - b[3]), reverse=True)
        return boxes[0]

    def sx(self, v):
        return self._ox + (v - self._raw_x0) / 100.0

    def sy(self, v):
        return self._oy - (v - self._raw_ytop) / 100.0

    def _walk(self, base, end, path):
        off = base
        while off + 8 <= end:
            cid = self.root[off:off + 4]
            size = struct.unpack_from("<I", self.root, off + 4)[0]
            if size > end - off - 8:
                break
            d = off + 8
            typ = self.root[d:d + 4].decode("latin1") if cid == b"LIST" else ""
            self.nodes.append(dict(path=path, name=cid.decode("latin1"),
                                   off=d, size=size, typ=typ))
            if cid == b"LIST" and typ != "stlt":  # stlt body is not chunks
                self._walk(d + 4, d + size, path + "/" + typ)
            off += 8 + size + (size & 1)

    def kids(self, node, path=None):
        p = path if path is not None else node["path"] + "/" + node["typ"]
        return [k for k in self.nodes if k["path"] == p
                and node["off"] <= k["off"] < node["off"] + node["size"]]

    def find(self, node, name):
        seen = set()
        stack = [node]
        while stack:
            n = stack.pop()
            p = n["path"] + "/" + n["typ"]
            for k in self.kids(n, p):
                if id(k) in seen:
                    continue
                seen.add(id(k))
                if k["name"] == name:
                    return k
                if k["name"] == "LIST":
                    stack.append(k)
        return None

    def find_list(self, node, typ):
        return next((k for k in self.kids(node)
                     if k["name"] == "LIST" and k["typ"] == typ), None)

    def deref(self, chunk, size=None):
        if self.redirect:
            _, sz, ptr, _ = struct.unpack_from("<4I", self.root, chunk["off"])
            n = size if size is not None else sz
            return self.page[ptr:ptr + n]
        n = size if size is not None else chunk["size"]
        return self.buf[chunk["off"]:chunk["off"] + n]

    def bbox(self, obj):
        b = self.find(obj, "bbox")
        x0, yt, x1, yb = struct.unpack_from("<4i", self.deref(b, 16))
        xs, ys = sorted((self.sx(x0), self.sx(x1))), sorted((self.sy(yt), self.sy(yb)))
        return (round(xs[0]), round(ys[0]), round(xs[1]), round(ys[1]))

    def loda_segment(self, obj):
        return self.deref(self.find(obj, "loda"))

    def _read_fonts(self):
        """Map font_id -> font name from the document font table."""
        fonts = {}
        for n in self.nodes:
            if n["name"] != "font" or n["size"] < 16:
                continue
            raw = self.deref(n)
            fid = struct.unpack_from("<H", raw, 0)[0]
            name = raw[16:].split(b"\x00")[0]
            name = bytes(b for b in name if b >= 32).decode("latin1", "ignore")
            if name:
                fonts[fid] = name
        return fonts

    def connector_points(self, obj):
        """Two endpoints (svg) of a connector from the nested npps/ppdt record."""
        inner = self.find_list(obj, "obj ")
        npps = self.find_list(inner, "npps") if inner else None
        ppdt = self.find(npps, "ppdt") if npps else None
        if ppdt is None:
            return None
        data = self.deref(ppdt)
        if len(data) < 24:
            return None
        x0, y0, x1, y1 = struct.unpack_from("<4i", data, 8)
        return ((self.sx(x0), self.sy(y0)), (self.sx(x1), self.sy(y1)))

    @staticmethod
    def json_of(seg):
        i = seg.find(b"{")
        if i < 0:
            return None
        depth = 0
        instr = esc = False
        for j in range(i, len(seg)):
            c = seg[j:j + 1]
            if instr:
                if esc:
                    esc = False
                elif c == b"\\":
                    esc = True
                elif c == b'"':
                    instr = False
                continue
            if c == b'"':
                instr = True
            elif c == b"{":
                depth += 1
            elif c == b"}":
                depth -= 1
                if depth == 0:
                    return json.loads(seg[i:j + 1].decode("latin1"))
        return None

    def geometry(self, obj, box):
        if self.redirect:
            return self.geometry_zcf(obj, box)
        return self.geometry_legacy(obj, box)

    def geometry_zcf(self, obj, box):
        """Return list of svg points, or None for a plain rectangle.

        The loda segment header is u32[size, count, ...] followed by `count`
        section offsets at u32[6:6+count]; the geometry record
        [u32 type][u32 npts][npts x (int32 x, int32 y)] starts at one of them.
        Geometry may be stored in a local frame, so it is translated onto the
        object bbox (verified: after translation geometry span == bbox span).
        """
        seg = self.loda_segment(obj)
        if len(seg) < 64:
            return None
        hdr = struct.unpack_from("<16I", seg, 0)
        count = hdr[1]
        if count > 16:
            return None
        w, h = box[2] - box[0], box[3] - box[1]
        tol = 40
        best = None
        for i in hdr[6:6 + count]:
            if i + 8 > len(seg):
                continue
            typ, npts = struct.unpack_from("<2I", seg, i)
            if not (1 <= typ <= 255 and 1 <= npts <= 64):
                continue
            if i + 8 + npts * 8 > len(seg):
                continue
            pts = [(self.sx(struct.unpack_from("<i", seg, i + 8 + k * 8)[0]),
                    self.sy(struct.unpack_from("<i", seg, i + 12 + k * 8)[0]))
                   for k in range(npts)]
            gx = max(p[0] for p in pts) - min(p[0] for p in pts)
            gy = max(p[1] for p in pts) - min(p[1] for p in pts)
            if abs(gx - w) > tol or abs(gy - h) > tol:
                continue
            if best is None or npts > len(best):
                best = pts
        if best is None:
            return None
        dx = box[0] - min(p[0] for p in best)
        dy = box[1] - min(p[1] for p in best)
        if abs(dx) > 0.01 or abs(dy) > 0.01:
            best = [(p[0] + dx, p[1] + dy) for p in best]
        return best

    def matrix_of(self, obj):
        """Object transform (a, c, tx, b, d, ty) in raw units, or None."""
        t = self.find(obj, "trfd")
        if t is None:
            return None
        raw = self.deref(t)
        try:
            soa = struct.unpack_from("<I", raw, 8)[0]
            offs = struct.unpack_from("<I", raw, soa)[0]
        except struct.error:
            return None
        off = offs + (8 if self.version >= 1300 else 0)
        if off + 2 > len(raw):
            return None
        if struct.unpack_from("<H", raw, off)[0] != 0x08:
            return None
        moff = off + 2 + (6 if self.version >= 600 else 0)
        if moff + 48 > len(raw):
            return None
        return struct.unpack_from("<6d", raw, moff)

    def geometry_legacy(self, obj, box):
        """Return svg polyline points for a legacy (RIFF) shape, or None.

        Geometry lives in the loda argument table: [chunk_length, num_of_args,
        start_of_args, start_of_arg_types, chunk_type_int] then the arg offsets
        and arg types. The arg with type 30 holds the point list; local points
        are mapped through the object's trfd matrix onto the page.
        """
        seg = self.loda_segment(obj)
        if len(seg) < 20:
            return None
        try:
            _, num, soa, soat, ct = struct.unpack_from("<5I", seg, 0)
            if not (0 < num <= 64):
                return None
            offs = struct.unpack_from("<%dI" % (num + 1), seg, soa)
            types = struct.unpack_from("<%dI" % num, seg, soat)
        except struct.error:
            return None
        gi = next((i for i in range(num) if types[num - 1 - i] == 30), None)
        if gi is None:
            return None
        g = seg[offs[gi]:offs[gi + 1]]
        pts, ops = self._points_of(ct, g)
        if len(pts) < 2:
            return None
        subs = self._subpaths(pts, ops)
        if not subs:
            return None
        m = self.matrix_of(obj)
        subs = [self._xform(m, sp) for sp in subs]
        best = max(subs, key=len)
        return [(self.sx(x), self.sy(y)) for x, y in best]

    def legacy_chunk_type(self, obj):
        """chunk_type_int of a legacy (RIFF) object, or None."""
        if self.redirect:
            return None
        seg = self.loda_segment(obj)
        if len(seg) < 20:
            return None
        try:
            return struct.unpack_from("<I", seg, 16)[0]
        except struct.error:
            return None

    def is_ellipse(self, obj):
        return self.legacy_chunk_type(obj) == 0x02

    @staticmethod
    def _points_of(ct, g):
        """Return ([(x, y)], [operation]) for a legacy geometry record."""
        if ct in (0x03, 0x14):
            base = 4
        elif ct == 0x25:
            base = 24
        else:
            return [], []
        if len(g) < base + 4:
            return [], []
        npts = struct.unpack_from("<I", g, 0)[0]
        if npts < 1 or base + npts * 9 > len(g):
            return [], []
        pts = [struct.unpack_from("<2i", g, base + k * 8) for k in range(npts)]
        ops = list(g[base + npts * 8:base + npts * 8 + npts])
        return pts, ops

    @staticmethod
    def _bezier(p0, p1, p2, p3, t):
        u = 1.0 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        return (a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1])

    @classmethod
    def _subpaths(cls, pts, ops):
        """Split a point list into subpaths, sampling cubic beziers."""
        subs = []
        cur = []
        pending = []
        for (x, y), op in zip(pts, ops):
            kind = (op & 0xC0) >> 6
            if kind == 0:              # move_to
                if len(cur) >= 2:
                    subs.append(cur)
                cur = [(x, y)]
                pending = []
            elif kind == 1:            # line_to
                cur.append((x, y))
                pending = []
            elif kind == 3:            # control_point (belongs to next curve)
                pending.append((x, y))
            else:                      # cubic_bezier_to (segment endpoint)
                if cur and len(pending) >= 2:
                    p0 = cur[-1]
                    p1, p2 = pending[-2], pending[-1]
                    for i in range(1, 13):
                        cur.append(cls._bezier(p0, p1, p2, (x, y), i / 12.0))
                else:
                    if not cur:
                        cur = [(x, y)]
                    else:
                        cur.append((x, y))
                pending = []
        if len(cur) >= 2:
            subs.append(cur)
        return subs

    @staticmethod
    def _xform(m, pts):
        if not m:
            return pts
        a, c, tx, b, d, ty = m
        return [(a * x + c * y + tx, b * x + d * y + ty) for x, y in pts]

    def text_of(self, obj):
        if self.redirect:
            return self.text_of_zcf(obj)
        return self.text_of_legacy(obj)

    def _txsm7(self, seg):
        """Parse a legacy txsm (versions 700..1599); return text, size, font."""
        v = self.version
        if v < 700:
            # compact v6 layout: [160-byte header] [u32 count][u32 pad]
            # followed by count 12-byte cells, each starting with a char.
            try:
                if len(seg) >= 168:
                    count = struct.unpack_from("<I", seg, 160)[0]
                    if 1 <= count <= 256 and len(seg) == 168 + 12 * count:
                        raw = bytes(seg[168 + 12 * i] for i in range(count))
                        if all(c == 9 or 32 <= c < 127 for c in raw):
                            return raw.decode("latin1"), None, self.fonts.get(
                                13, "Arial")
            except (struct.error, IndexError):
                pass
            return "", None, "Arial"
        try:
            o = 0
            frame_flag = struct.unpack_from("<I", seg, o)[0] != 0
            o += 4 + 32
            if v >= 1500:
                o += 1
            if v < 800:
                if struct.unpack_from("<I", seg, o)[0]:
                    o += 32
                o += 4
            num_frames = struct.unpack_from("<I", seg, o)[0]
            o += 4
            for _ in range(num_frames):
                o += 4 + 48
                if v >= 800:
                    on_path = struct.unpack_from("<I", seg, o)[0]
                    o += 4
                    if on_path:
                        o += 4 + (8 if v >= 1300 else 0) + 28 + (8 if v >= 1500 else 0)
                    elif v >= 1500:
                        o += 8
                if not frame_flag:
                    if v >= 1500:
                        o += 40
                    elif v >= 1400:
                        o += 36
                    elif v >= 801:
                        o += 34
                    elif v == 800:
                        o += 32
                    elif v >= 700:
                        o += 36
                elif v >= 1500:
                    o += 4
            num_par = struct.unpack_from("<I", seg, o)[0]
            o += 4
            out = []
            size = None
            fid = None
            for _ in range(num_par):
                o += 4 + 1
                if v >= 1300 and frame_flag:
                    o += 1
                num_styles = struct.unpack_from("<I", seg, o)[0]
                o += 4
                for _ in range(num_styles):
                    o += 2
                    fl = seg[o]
                    o += 1
                    if v >= 800:
                        o += 1
                    if fl & 0x01:
                        fid, _ = struct.unpack_from("<2H", seg, o)
                        o += 4
                    if fl & 0x02:
                        o += 2
                    if fl & 0x04:
                        size = struct.unpack_from("<i", seg, o)[0]
                        o += 4
                    for bit, extra in ((0x08, 4), (0x10, 4), (0x20, 4),
                                       (0x40, 4 + (48 if v >= 1300 else 0)),
                                       (0x80, 4)):
                        if fl & bit:
                            o += extra
                num_chars = struct.unpack_from("<I", seg, o)[0]
                o += 4
                o += num_chars * (8 if v >= 1200 else 4)
                nbytes = num_chars
                if v >= 1200:
                    nbytes = struct.unpack_from("<I", seg, o)[0]
                    o += 4
                out.append(seg[o:o + nbytes].decode("latin1", "replace"))
                o += nbytes
                has_path = seg[o]
                o += 1
                if has_path:
                    o += num_chars * 24
            text = "\n".join(out)
            if text:
                return text, size, self.fonts.get(fid, "Arial")
        except (struct.error, IndexError):
            pass
        return self._tail_txsm(seg)

    def _tail_txsm(self, seg):
        """Fallback for versions (e.g. v1200/CDRC) whose txsm layout differs:
        the text sits at the tail as [pad][u32 count][chars][00], with lines
        separated by \\r."""
        L = len(seg)
        for end in (L - 1, L):
            if end < 5:
                continue
            if end == L - 1 and seg[L - 1] != 0:
                continue
            for count in range(min(250, end - 4), 1, -1):
                q = end - count
                if struct.unpack_from("<I", seg, q - 4)[0] == count:
                    blk = bytes(seg[q:end])
                    if all(b in (9, 10, 13) or 32 <= b < 127 for b in blk):
                        return (blk.replace(b"\r", b"\n").decode("latin1"),
                                None, "Arial")
        return "", None, "Arial"

    def text_of_legacy(self, obj):
        t = self.find(obj, "txsm")
        if t is None:
            return None
        text, size, font = self._txsm7(self.deref(t))
        return text, size, font, COREL_BLACK

    def text_of_zcf(self, obj):
        """Return (string, size_1e4, font_name, colour_hex) for a text object."""
        t = self.find(obj, "txsm")
        if t is None:
            return None
        seg = self.deref(t)
        # string: [u32 length][bytes][5 zero bytes] at the tail
        end = len(seg)
        s = None
        for slen in range(1, 400):
            pos = end - 5 - slen
            if pos < 4:
                break
            if struct.unpack_from("<I", seg, pos - 4)[0] == slen:
                raw = seg[pos:pos + slen]
                if all(32 <= c < 127 or c in (9, 10, 13) for c in raw):
                    s = raw.decode("latin1")
                    break
        if s is None:
            raise ValueError("text string not found")
        m = re.search(rb'"size"\s*:\s*"(\d+)"', seg)
        size1e4 = int(m.group(1)) if m else 63499
        fm = re.search(rb'"latin"\s*:\s*\{.*?"font"\s*:\s*"([^"]*)"', seg, re.S)
        font = fm.group(1).decode("latin1") if fm else "Arial"
        cm = re.search(rb'"primaryColor"\s*:\s*"([^"]*)"', seg)
        color = cmyk_to_hex(cm.group(1).decode("latin1")) if cm else COREL_BLACK
        return s.replace("\r", "\n"), size1e4, font, color


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def arial_width_em(s):
    return sum(ARIAL.get(c, 556) for c in s) / 1000.0


def text_dims(box, text, size1e4):
    """Text cell (w, h, cx, cy, font) from its bbox and parsed size."""
    b0, b1, b2, b3 = box
    F = size1e4 / 100.0 if size1e4 else (b3 - b1)
    lines = text.split("\n")
    natural = max(arial_width_em(l) for l in lines) * F
    w = max(b2 - b0, natural) + 20
    h = max(b3 - b1, len(lines) * 1.25 * F)
    cx, cy = (b0 + b2) / 2.0, (b1 + b3) / 2.0
    return w, h, cx, cy, F


def emit(cdr, out_path, name="diagram"):
    cells = []
    stats = {"rect": 0, "poly": 0, "conn": 0, "text": 0}
    # Anchor content at the page origin so off-page (negative) coordinates
    # don't push the drawing out of the viewport. Content already on the
    # page is left untouched.
    PAD = 100.0
    lefts, tops = [], []
    for o in cdr.objs:
        b = cdr.bbox(o)
        lefts.append(b[0]); tops.append(b[1])
        if cdr.find(o, "txsm") is not None:
            t = cdr.text_of(o)
            if t and t[0].strip():
                w, h, cx, cy, _ = text_dims(b, t[0], t[1])
                lefts.append(cx - w / 2.0)
                tops.append(cy - h / 2.0)
    minx = min(lefts) if lefts else 0.0
    miny = min(tops) if tops else 0.0
    dx = (PAD - minx) if minx < PAD else 0.0
    dy = (PAD - miny) if miny < PAD else 0.0
    for n, obj in enumerate(cdr.objs):
        box = cdr.bbox(obj)
        b0, b1, b2, b3 = (box[0] + dx, box[1] + dy,
                          box[2] + dx, box[3] + dy)
        kind = obj["typ"].strip()
        style_json = Cdr.json_of(cdr.loda_segment(obj)) or {}
        outline = style_json.get("outline", {})
        stroke = cmyk_to_hex(outline.get("color") or
                             style_json.get("fill", {}).get("primaryColor"))
        width = int(outline.get("width", "2000")) / 100.0  # -> svg units
        stroke_px = max(1.0, round(width * SCALE, 2))
        has_ra = bool(outline.get("rightArrow", "|0").split("|")[0])
        has_la = bool(outline.get("leftArrow", "|0").split("|")[0])

        if kind == "lnkg":
            stats["conn"] += 1
            ends = cdr.connector_points(obj)
            if ends:
                pts = [(x + dx, y + dy) for x, y in ends]
            else:
                pts = [(b0, b1), (b2, b3)]
            if has_la and not has_ra:
                pts = [pts[1], pts[0]]  # put the arrow tip at the end
            arrow = "endArrow=block;endFill=1;endSize=%s;" % ARROW_END_SIZE \
                if (has_ra or has_la) else "endArrow=none;"
            cells.append(edge_cell("e%d" % n, pts, stroke, stroke_px,
                                   "startArrow=none;" + arrow))

        elif cdr.find(obj, "txsm") is not None:
            stats["text"] += 1
            text, size1e4, font, color = cdr.text_of(obj)
            if not text.strip():
                continue
            # Legacy text has no explicit size; scale to the bbox height.
            w, h, cx, cy, F = text_dims((b0, b1, b2, b3), text, size1e4)
            style = ("text;html=1;align=center;verticalAlign=middle;"
                     "fontSize=%d;fontFamily=%s;fontColor=%s;"
                     "fillColor=none;strokeColor=none;"
                     % (round(F * SCALE), font, color))
            cells.append(vertex_cell("t%d" % n, esc(text.replace("\n", "<br>")),
                                     style, cx - w / 2.0, cy - h / 2.0, w, h))
        else:
            pts = cdr.geometry(obj, box)
            if pts is None:
                stats["rect"] += 1
                shape = "ellipse;" if cdr.is_ellipse(obj) else "rounded=0;"
                style = ("%swhiteSpace=wrap;html=1;fillColor=none;"
                         "strokeColor=%s;strokeWidth=%s;" % (shape, stroke, stroke_px))
                cells.append(vertex_cell("s%d" % n, "", style,
                                         b0, b1, b2 - b0, b3 - b1))
            else:
                stats["poly"] += 1
                start = "startArrow=block;startFill=1;startSize=%s;" % \
                    ARROW_END_SIZE if has_la else "startArrow=none;"
                end = "endArrow=block;endFill=1;endSize=%s;" % \
                    ARROW_END_SIZE if has_ra else "endArrow=none;"
                cells.append(edge_cell("s%d" % n,
                                       [(x + dx, y + dy) for x, y in pts],
                                       stroke, stroke_px, start + end))

    xml = []
    xml.append('<mxfile host="app.diagrams.net" type="device">')
    xml.append('  <diagram id="%s" name="%s">' % (esc(name), esc(name)))
    xml.append('    <mxGraphModel dx="827" dy="816" grid="1" gridSize="10" '
               'guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
               'page="1" pageScale="1" pageWidth="794" pageHeight="1123" '
               'math="0" shadow="0">')
    xml.append('      <root>')
    xml.append('        <mxCell id="0"/>')
    xml.append('        <mxCell id="1" parent="0"/>')
    for c in cells:
        xml.append(c)
    xml.append('      </root>')
    xml.append('    </mxGraphModel>')
    xml.append('  </diagram>')
    xml.append('</mxfile>')
    with open(out_path, "w") as f:
        f.write("\n".join(xml) + "\n")
    return stats


def vertex_cell(cid, value, style, x, y, w, h):
    return ('        <mxCell id="%s" value="%s" style="%s" vertex="1" parent="1">'
            '\n          <mxGeometry x="%s" y="%s" width="%s" height="%s" '
            'as="geometry"/>\n        </mxCell>'
            % (cid, value, style, round(px(x), 2), round(px(y), 2),
               round(px(w), 2), round(px(h), 2)))


def edge_cell(cid, pts, stroke, stroke_px, arrow_style):
    """pts: polyline points in svg units (first == last for closed shapes)."""
    p = [(px(x), px(y)) for x, y in pts]
    style = ("edgeStyle=none;html=1;strokeColor=%s;strokeWidth=%s;"
             "rounded=0;curved=0;%s" % (stroke, stroke_px, arrow_style))
    g = ['          <mxGeometry relative="1" as="geometry">']
    g.append('            <mxPoint x="%s" y="%s" as="sourcePoint"/>'
             % (round(p[0][0], 2), round(p[0][1], 2)))
    g.append('            <mxPoint x="%s" y="%s" as="targetPoint"/>'
             % (round(p[-1][0], 2), round(p[-1][1], 2)))
    if len(p) > 2:
        g.append('            <Array as="points">')
        for q in p[1:-1]:
            g.append('              <mxPoint x="%s" y="%s"/>'
                     % (round(q[0], 2), round(q[1], 2)))
        g.append('            </Array>')
    g.append('          </mxGeometry>')
    return ('        <mxCell id="%s" value="" style="%s" edge="1" parent="1">\n'
            '%s\n        </mxCell>' % (cid, style, "\n".join(g)))


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: cdr2drawio.py <input> [output.drawio]")
    src = sys.argv[1]
    if not src.lower().endswith(".cdr"):
        src += ".cdr"
    dst = sys.argv[2] if len(sys.argv) > 2 else \
        os.path.splitext(src)[0] + ".drawio"
    name = os.path.splitext(os.path.basename(src))[0]
    cdr = Cdr(src)
    stats = emit(cdr, dst, name)
    print("wrote %s: %s" % (dst, stats))


if __name__ == "__main__":
    main()
