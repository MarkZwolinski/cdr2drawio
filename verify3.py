#!/usr/bin/env python3
"""verify3: (a) locate missing edge samples, (b) arrowhead profile in render
vs thumbnail, (c) tolerant mismatch clusters."""
import re, math, zlib, struct
from collections import deque

def read_png(path):
    data = open(path, 'rb').read()
    o = 8; idat = b''
    while o < len(data):
        ln = struct.unpack('>I', data[o:o+4])[0]; typ = data[o+4:o+8]
        ch = data[o+8:o+8+ln]; o += 12 + ln
        if typ == b'IHDR': w, h, bd, ct = struct.unpack('>IIBB', ch[:10])
        elif typ == b'IDAT': idat += ch
        elif typ == b'IEND': break
    raw = zlib.decompress(idat)
    nch = {0:1, 2:3, 3:1, 4:2, 6:4}[ct]
    bpp = nch*(bd//8); stride = w*bpp
    rows = []; prev = bytearray(stride); i = 0
    for y in range(h):
        f = raw[i]; i += 1
        line = bytearray(raw[i:i+stride]); i += stride
        for x in range(stride):
            a = line[x-bpp] if x >= bpp else 0
            b = prev[x]; c = prev[x-bpp] if x >= bpp else 0
            if f == 1: line[x] = (line[x]+a) & 255
            elif f == 2: line[x] = (line[x]+b) & 255
            elif f == 3: line[x] = (line[x]+(a+b)//2) & 255
            elif f == 4:
                p = a+b-c; pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x]+pr) & 255
        rows.append(bytes(line)); prev = line
    return w, h, nch, rows

K = 96.0/2540.0
CONTENT = (493, 8201, 15993, 15463)
CWD = ""
rw, rh, rn, rrows = read_png(CWD + 'cpu2_render.png')
tw, th, tn, trows = read_png('thumbnail.png')
SCALE = 2
RPX_PER_SVG = (CONTENT[2]-CONTENT[0])*K*SCALE/(tw)  # unused placeholder

def dark(rows, nch, x, y, w, h, thr=170):
    if not (0 <= x < w and 0 <= y < h): return False
    p = rows[y][x*nch:(x+1)*nch]
    return len(p) >= 3 and (p[0]+p[1]+p[2])/3.0 < thr

def dark_r(x, y, rad=4, thr=170):
    xi, yi = int(round(x)), int(round(y))
    return any(dark(rrows, rn, xi+dx, yi+dy, rw, rh, thr)
               for dy in range(-rad, rad+1) for dx in range(-rad, rad+1))

# ---- (a) missing samples per failing edge ------------------------------
xml = open(CWD + 'cpu2.drawio').read()
cells = []
for m in re.finditer(r'<mxCell id="([a-z]+\d+)" value="([^"]*)" style="([^"]*)"[^>]*>'
                     r'(.*?)</mxCell>', xml, re.S):
    cid, val, style, body = m.group(1), m.group(2), m.group(3), m.group(4)
    sp = re.search(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)" as="sourcePoint"', body)
    tp = re.search(r'<mxPoint x="([-\d.]+)" y="([-\d.]+)" as="targetPoint"', body)
    am = re.search(r'<Array as="points">(.*?)</Array>', body, re.S)
    pts = []
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
    geo = re.search(r'<mxGeometry x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" '
                    r'height="([-\d.]+)"', body)
    cells.append(dict(id=cid, val=val, style=style, pts=pts,
                      geo=tuple(float(v) for v in geo.groups()) if geo else None))

print('--- failing edges: missing sample locations (svg) ---')
for c in cells:
    if not c['pts'] or len(c['pts']) < 2: continue
    if c['id'] not in ('s14', 's16', 's17', 's18', 'e27'): continue
    pts = c['pts']
    segs = []
    for i in range(len(pts)-1):
        p, q = pts[i], pts[i+1]
        L = math.hypot(q[0]-p[0], q[1]-p[1])*SCALE
        n = max(2, int(L/12))
        miss = []
        for j in range(n+1):
            t = j/n
            x, y = (p[0]+(q[0]-p[0])*t)*SCALE, (p[1]+(q[1]-p[1])*t)*SCALE
            if not dark_r(x, y): miss.append((t, round((p[0]+(q[0]-p[0])*t)/K),
                                              round((p[1]+(q[1]-p[1])*t)/K)))
        if miss:
            segs.append((i, round(p[0]/K), round(p[1]/K), round(q[0]/K),
                         round(q[1]/K), len(miss), n+1))
    print('  %s pts(svg)=%s' % (c['id'],
          [(round(x/K), round(y/K)) for x, y in pts]))
    for s in segs:
        print('     seg %d (%d,%d)->(%d,%d): %d/%d missing' % s)

# ---- (b) arrow profiles ------------------------------------------------
print('--- arrow profile: halfwidth(svg) vs distance behind tip(svg) ---')
def profile(rows, nch, W, H, tip_img, u, px_per_svg, ds, smax_svg, scale_img):
    """tip_img: image px; u: unit dir from tip toward tail; returns list"""
    out = []
    for d in ds:
        cx = tip_img[0] - u[0]*d*px_per_svg
        cy = tip_img[1] - u[1]*d*px_per_svg
        hw = 0
        for s in range(1, int(smax_svg*px_per_svg)+1):
            a = dark(rows, nch, int(cx-u[1]*s), int(cy+u[0]*s), W, H) or \
                dark(rows, nch, int(cx+u[1]*s), int(cy-u[0]*s), W, H)
            if a: hw = s
            elif s > hw + 3: break
        out.append((d, round(hw/px_per_svg)))
    return out

# pick arrows: e32 (vertical up), s19 (horizontal right), e35 (vertical up)
want = {'e32': None, 's19': None, 'e35': None, 's14': None, 's18': None}
for c in cells:
    if c['id'] in want and 'triangle' in c['style']:
        tip = c['pts'][-1]; prv = c['pts'][-2]
        dx, dy = tip[0]-prv[0], tip[1]-prv[1]
        n = math.hypot(dx, dy); u = (dx/n, dy/n)
        ds = [20, 40, 60, 80, 100, 120, 140, 160, 180, 200, 240, 280, 320, 400]
        # render
        pr = profile(rrows, rn, rw, rh, (tip[0]*SCALE, tip[1]*SCALE), u,
                     (CONTENT[2]-CONTENT[0])*K*SCALE/rw if False else
                     (K*SCALE), ds, 260, 1)
        # thumb
        def s2t(x, y):
            return ((x-CONTENT[0])/(CONTENT[2]-CONTENT[0])*(tw-1),
                    (y-CONTENT[1])/(CONTENT[3]-CONTENT[1])*(th-1))
        tt = s2t(tip[0], tip[1]); pp = s2t(prv[0], prv[1])
        dv = (tt[0]-pp[0], tt[1]-pp[1]); n2 = math.hypot(*dv); u2 = (dv[0]/n2, dv[1]/n2)
        ts = (CONTENT[2]-CONTENT[0])/(tw-1)   # svg per thumb px
        pt = profile(trows, tn, tw, th, tt, u2, 1.0/ts, ds, 260, 1)
        print('  %s RENDER: %s' % (c['id'], [(d, hw) for d, hw in pr]))
        print('  %s THUMB : %s' % (c['id'], [(d, hw) for d, hw in pt]))

# ---- (c) tolerant clusters --------------------------------------------
print('--- mismatch clusters w/ tol=1 thumb px, 3x3 sampling ---')
def dilate(mask, w, h, r):
    out = [bytearray(w) for _ in range(h)]
    for y in range(h):
        row = mask[y]
        for x in range(w):
            if row[x]:
                for dy in range(-r, r+1):
                    yy = y+dy
                    if 0 <= yy < h:
                        rr = out[yy]
                        for dx in range(-r, r+1):
                            xx = x+dx
                            if 0 <= xx < w: rr[xx] = 1
    return out

x0, y0 = CONTENT[0]*K*SCALE, CONTENT[1]*K*SCALE
x1, y1 = CONTENT[2]*K*SCALE, CONTENT[3]*K*SCALE
R = [[0]*tw for _ in range(th)]
T = [[0]*tw for _ in range(th)]
for ty_ in range(th):
    for tx_ in range(tw):
        px_ = int(x0 + (tx_+0.5)/tw*(x1-x0))
        py_ = int(y0 + (ty_+0.5)/th*(y1-y0))
        if any(dark(rrows, rn, px_+dx, py_+dy, rw, rh)
               for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)): R[ty_][tx_] = 1
        if any(dark(trows, tn, tx_+dx, ty_+dy, tw, th)
               for dx in (-1, 0, 1) for dy in (-1, 0, 1)): T[ty_][tx_] = 1
Rb = dilate(R, tw, th, 1)
Tb = dilate(T, tw, th, 1)
grid = [[(1 if (T[y][x] and not Rb[y][x]) else
          (2 if (R[y][x] and not Tb[y][x]) else 0)) for x in range(tw)]
        for y in range(th)]
seen = [[False]*tw for _ in range(th)]
clusters = []
for yy in range(th):
    for xx in range(tw):
        v = grid[yy][xx]
        if not v or seen[yy][xx]: continue
        q = deque([(xx, yy)]); seen[yy][xx] = True
        n1 = n2 = 0; bx = [xx, xx]; by = [yy, yy]
        while q:
            cx, cy = q.popleft(); w_ = grid[cy][cx]
            if w_ == 1: n1 += 1
            elif w_ == 2: n2 += 1
            bx = [min(bx[0], cx), max(bx[1], cx)]
            by = [min(by[0], cy), max(by[1], cy)]
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
                nx, ny = cx+dx, cy+dy
                if 0 <= nx < tw and 0 <= ny < th and grid[ny][nx] and not seen[ny][nx]:
                    seen[ny][nx] = True; q.append((nx, ny))
        if n1+n2 >= 10:
            sxb = (CONTENT[0] + bx[0]/(tw-1)*(CONTENT[2]-CONTENT[0]),
                   CONTENT[1] + by[0]/(th-1)*(CONTENT[3]-CONTENT[1]),
                   CONTENT[0] + bx[1]/(tw-1)*(CONTENT[2]-CONTENT[0]),
                   CONTENT[1] + by[1]/(th-1)*(CONTENT[3]-CONTENT[1]))
            kind = 'thumb-only' if n1 > n2 else 'render-only'
            clusters.append((n1+n2, kind, tuple(round(v) for v in sxb)))
clusters.sort(reverse=True)
for n, kind, bb in clusters[:30]:
    print('  %-12s %4d px  svg bbox %s' % (kind, n, bb))
