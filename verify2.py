#!/usr/bin/env python3
"""End-to-end verify: parse cpu2.drawio geometry, check ink in cpu2_render.png,
measure arrowheads vs Corel thumbnail, list mismatch clusters in svg space."""
import re, math, zlib, struct, sys
from collections import deque

def read_png(path):
    data = open(path, 'rb').read()
    o = 8; idat = b''
    while o < len(data):
        ln = struct.unpack('>I', data[o:o+4])[0]; typ = data[o+4:o+8]
        ch = data[o+8:o+8+ln]; o += 12 + ln
        if typ == b'IHDR':
            w, h, bd, ct = struct.unpack('>IIBB', ch[:10])
        elif typ == b'IDAT':
            idat += ch
        elif typ == b'IEND':
            break
    raw = zlib.decompress(idat)
    nch = {0:1, 2:3, 3:1, 4:2, 6:4}[ct]
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
            elif f == 3: line[x] = (line[x] + (a + b)//2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        rows.append(bytes(line)); prev = line
    return w, h, nch, rows

K = 96.0 / 2540.0                 # svg -> page px
CONTENT = (493, 8201, 15993, 15463)
rw, rh, rn, rrows = read_png('cpu2_render.png')
tw, th, tn, trows = read_png('thumbnail.png')
SCALE = 2                          # export scale

def dark(rows, nch, x, y, w, h, thr=160):
    if not (0 <= x < w and 0 <= y < h): return False
    p = rows[y][x*nch:(x+1)*nch]
    if len(p) < 3: return False
    return (p[0]+p[1]+p[2])/3.0 < thr

def dark_r(px_, py_, rad=3):
    x, y = int(round(px_)), int(round(py_))
    for dy in range(-rad, rad+1):
        for dx in range(-rad, rad+1):
            if dark(rrows, rn, x+dx, y+dy, rw, rh): return True
    return False

# ---- parse drawio file -------------------------------------------------
xml = open('cpu2.drawio').read()
cells = []
for m in re.finditer(r'<mxCell id="([a-z]+\d+)" value="([^"]*)" style="([^"]*)"[^>]*>'
                     r'(.*?)</mxCell>', xml, re.S):
    cid, val, style, body = m.group(1), m.group(2), m.group(3), m.group(4)
    pts = []
    sp = re.search(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)" as="sourcePoint"', body)
    tp = re.search(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)" as="targetPoint"', body)
    am = re.search(r'<Array as="points">(.*?)</Array>', body, re.S)
    if sp:
        pts.append((float(sp.group(1)), float(sp.group(2))))
        if am:
            for p in re.finditer(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)"', am.group(1)):
                pts.append((float(p.group(1)), float(p.group(2))))
        if tp:
            pts.append((float(tp.group(1)), float(tp.group(2))))
    else:
        for p in re.finditer(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)"', body):
            pts.append((float(p.group(1)), float(p.group(2))))
    geo = re.search(r'<mxGeometry x="([-\d.]+)" y="([-\d.]+)" '
                    r'width="([-\d.]+)" height="([-\d.]+)"', body)
    g = tuple(float(v) for v in geo.groups()) if geo else None
    cells.append(dict(id=cid, val=val, style=style, pts=pts, geo=g))

def to_r(ppx, ppy):               # page px -> render px
    return ppx * SCALE, ppy * SCALE

fails = 0
print('--- edge ink checks (render) ---')
edges = [c for c in cells if c['id'][0] == 'e' or (c['id'][0] == 's' and c['pts'])]
for c in edges:
    # edge cells: sourcePoint, waypoints, targetPoint in page px
    pts = c['pts']
    if len(pts) < 2:
        # vertex-style polyline (s-cells store x,y,w,h + points?) skip handled below
        continue
    miss = tot = 0
    for i in range(len(pts)-1):
        p, q = pts[i], pts[i+1]
        L = math.hypot(q[0]-p[0], q[1]-p[1]) * SCALE
        n = max(2, int(L / 12))
        for j in range(n+1):
            t = j / n
            x, y = to_r(p[0] + (q[0]-p[0])*t, p[1] + (q[1]-p[1])*t)
            tot += 1
            if not dark_r(x, y, 4): miss += 1
    ok = miss <= max(1, tot // 12)
    if not ok: fails += 1
    print('  %-8s %-28s %s (%d/%d missing)  %s' %
          (c['id'], c['val'][:28] or c['style'][:28], 'OK  ' if ok else 'FAIL',
           miss, tot, 'arrow' if 'endArrow=block' in c['style'] or
           'startArrow=block' in c['style'] else ''))

print('--- rect edge checks (render) ---')
for c in cells:
    if c['id'][0] != 's' or not c['geo']: continue
    if c['pts']: continue            # polyline s-cells (checked above if pts listed)
    x, y, w, h = c['geo']
    corners = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
    miss = tot = 0
    for i in range(4):
        p, q = corners[i], corners[(i+1) % 4]
        L = math.hypot(q[0]-p[0], q[1]-p[1]) * SCALE
        n = max(2, int(L / 12))
        for j in range(n+1):
            t = j / n
            px_, py_ = to_r(p[0] + (q[0]-p[0])*t, p[1] + (q[1]-p[1])*t)
            tot += 1
            if not dark_r(px_, py_, 4): miss += 1
    ok = miss <= max(1, tot // 12)
    if not ok: fails += 1
    print('  %-8s rect %s %s (%d/%d missing)' %
          (c['id'], 'OK  ' if ok else 'FAIL', '', miss, tot))

# ---- arrow size: render vs thumbnail ----------------------------------
print('--- arrowhead size (svg units) ---')
def svg_to_thumb(sx_, sy_):
    return ((sx_-CONTENT[0])/(CONTENT[2]-CONTENT[0])*(tw-1),
            (sy_-CONTENT[1])/(CONTENT[3]-CONTENT[1])*(th-1))

def measure_arrow(rows, nch, W, H, tip_ppx, dirv, back_ppx, width_ppx, sc):
    """tip/dir/back/width in page-px-space; sc converts page px -> image px."""
    tx, ty = tip_ppx[0]*sc, tip_ppx[1]*sc
    dx, dy = dirv
    n = math.hypot(dx, dy); dx, dy = dx/n, dy/n
    px_, py_ = -dy, dx
    best = 0
    for step in range(1, max(2, int(back_ppx*sc))):
        cx, cy = tx - dx*step, ty - dy*step
        halfw = 0
        for s in range(0, int(width_ppx*sc)):
            if dark(rows, nch, int(cx+px_*s), int(cy+py_*s), W, H, 180) or \
               dark(rows, nch, int(cx-px_*s), int(cy-py_*s), W, H, 180):
                halfw = s
        if halfw*2 > best: best = halfw*2
    return best / sc   # page px

# arrow edges from drawio (endArrow) with their tip point
for c in edges:
    st = c['style']
    if 'endArrow=block' in st:
        tip = c['pts'][-1]; prev = c['pts'][-2]
        dirv = (tip[0]-prev[0], tip[1]-prev[1])
        wr = measure_arrow(rrows, rn, rw, rh, tip, dirv, 30, 30, SCALE)
        wr_svg = wr / K
        # thumbnail: measure in thumb px, convert to svg
        tip_s = (tip[0]/K, tip[1]/K)
        prv_s = (prev[0]/K, prev[1]/K)
        tt = svg_to_thumb(*tip_s); pp = svg_to_thumb(*prv_s)
        dv = (tt[0]-pp[0], tt[1]-pp[1])
        n = math.hypot(*dv); ux, uy = dv[0]/n, dv[1]/n
        best = 0
        for step in range(1, 14):
            cx, cy = tt[0]-ux*step, tt[1]-uy*step
            hw = 0
            for s in range(0, 10):
                if dark(trows, tn, int(cx-uy*s), int(cy+ux*s), tw, th, 180) or \
                   dark(trows, tn, int(cx+uy*s), int(cy-ux*s), tw, th, 180):
                    hw = s
            if hw*2 > best: best = hw*2
        t_svg = best * (CONTENT[2]-CONTENT[0]) / (tw-1)
        print('  %-6s base: render %.0f svg  thumb %.0f svg  %s'
              % (c['id'], wr_svg, t_svg,
                 'OK' if abs(wr_svg - t_svg) < 0.45*max(t_svg, 1) else 'DIFF'))

# ---- mismatch clusters (thumb-only / render-only) ---------------------
print('--- mismatch clusters (svg bbox, size>=12 px) ---')
x0, y0 = CONTENT[0]*K*SCALE, CONTENT[1]*K*SCALE
x1, y1 = CONTENT[2]*K*SCALE, CONTENT[3]*K*SCALE
grid = []
for ty_ in range(th):
    row = []
    for tx_ in range(tw):
        px_ = int(x0 + (tx_+0.5)/tw*(x1-x0))
        py_ = int(y0 + (ty_+0.5)/th*(y1-y0))
        r = dark(rrows, rn, min(px_, rw-1), min(py_, rh-1), rw, rh, 180)
        t = dark(trows, tn, tx_, ty_, tw, th, 180)
        row.append(1 if (t and not r) else (2 if (r and not t) else 0))
    grid.append(row)
seen = [[False]*tw for _ in range(th)]
clusters = []
for yy in range(th):
    for xx in range(tw):
        v = grid[yy][xx]
        if not v or seen[yy][xx]: continue
        q = deque([(xx, yy)]); seen[yy][xx] = True
        n1 = n2 = 0; bx = [xx, xx]; by = [yy, yy]
        while q:
            cx, cy = q.popleft()
            w_ = grid[cy][cx]
            if w_ == 1: n1 += 1
            elif w_ == 2: n2 += 1
            bx[0] = min(bx[0], cx); bx[1] = max(bx[1], cx)
            by[0] = min(by[0], cy); by[1] = max(by[1], cy)
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nx, ny = cx+dx, cy+dy
                if 0 <= nx < tw and 0 <= ny < th and grid[ny][nx] and not seen[ny][nx]:
                    seen[ny][nx] = True; q.append((nx, ny))
        if n1+n2 >= 12:
            sx_ = CONTENT[0] + bx[0]/(tw-1)*(CONTENT[2]-CONTENT[0])
            sxe = CONTENT[0] + bx[1]/(tw-1)*(CONTENT[2]-CONTENT[0])
            sy_ = CONTENT[1] + by[0]/(th-1)*(CONTENT[3]-CONTENT[1])
            sye = CONTENT[1] + by[1]/(th-1)*(CONTENT[3]-CONTENT[1])
            kind = 'thumb-only' if n1 > n2 else 'render-only'
            clusters.append((n1+n2, kind, (round(sx_), round(sy_), round(sxe), round(sye))))
clusters.sort(reverse=True)
for n, kind, bb in clusters[:25]:
    print('  %-12s %4d px  svg bbox %s' % (kind, n, bb))
print('FAILS: %d' % fails)
