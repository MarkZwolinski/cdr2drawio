#!/usr/bin/env python3
"""verify4: density-based structural diff (robust to subpixel registration)
+ fine arrow probes on regenerated render."""
import math, zlib, struct, sys

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
C = (493, 8201, 15993, 15463)
CWD = ""
rw, rh, rn, R = read_png(CWD + 'cpu2_render.png')
tw, th, tn, T = read_png('thumbnail.png')
SC = 2

def lum(rows, nch, x, y, w, h):
    if not (0 <= x < w and 0 <= y < h): return 255.0
    p = rows[y][x*nch:(x+1)*nch]
    return 255.0 if len(p) < 3 else (p[0]+p[1]+p[2])/3.0

# ---- density grid: 136 x 64 cells over content bbox -------------------
GW, GH = 136, 64
def density(rows, nch, w, h, is_render):
    grid = [[0.0]*GW for _ in range(GH)]
    cnt = [[0]*GW for _ in range(GH)]
    if is_render:
        x0, y0 = C[0]*K*SC, C[1]*K*SC
        x1, y1 = C[2]*K*SC, C[3]*K*SC
    else:
        x0, y0 = 0.0, 0.0
        x1, y1 = float(w-1), float(h-1)
    # sample every render px / thumb px inside each cell (bounded)
    for gy in range(GH):
        sy0 = y0 + gy*(y1-y0)/GH
        sy1 = y0 + (gy+1)*(y1-y0)/GH
        for gx in range(GW):
            sx0 = x0 + gx*(x1-x0)/GW
            sx1 = x0 + (gx+1)*(x1-x0)/GW
            n = 0; ink = 0.0
            # sample up to 4x4 points in the cell
            for iy in range(4):
                yy = int(sy0 + (sy1-sy0)*(iy+0.5)/4)
                for ix in range(4):
                    xx = int(sx0 + (sx1-sx0)*(ix+0.5)/4)
                    if 0 <= xx < w and 0 <= yy < h:
                        v = lum(rows, nch, xx, yy, w, h)
                        ink += (255.0-v)/255.0; n += 1
            grid[gy][gx] = ink/n if n else 0.0
    return grid

dr = density(R, rn, rw, rh, True)
dt = density(T, tn, tw, th, False)
print('--- density diff cells |dR-dT| > 0.18 (svg bbox) ---')
bad = []
for gy in range(GH):
    for gx in range(GW):
        d = dr[gy][gx] - dt[gy][gx]
        if abs(d) > 0.18:
            sx = C[0] + gx*(C[2]-C[0])/GW
            sy = C[1] + gy*(C[3]-C[1])/GH
            bad.append((abs(d), d, round(sx), round(sy),
                        round(sx+(C[2]-C[0])/GW), round(sy+(C[3]-C[1])/GH)))
bad.sort(reverse=True)
for a, d, x0, y0, x1, y1 in bad:
    print('  %s  %+0.2f  svg (%d,%d)-(%d,%d)' %
          ('render>' if d > 0 else 'thumb>', d, x0, y0, x1, y1))
print('total flagged cells: %d / %d' % (len(bad), GW*GH))

# overall ink
ir = sum(sum(r) for r in dr); it = sum(sum(r) for r in dt)
print('total ink: render %.1f  thumb %.1f  ratio %.3f' % (ir, it, ir/it))

# ---- fine arrow probes on new render ----------------------------------
def fine(name, tip_svg, dirv, span=8):
    u = dirv; n = math.hypot(*u); u = (u[0]/n, u[1]/n)
    def s2t(x, y):
        return ((x-C[0])/(C[2]-C[0])*(tw-1), (y-C[1])/(C[3]-C[1])*(th-1))
    tt = s2t(*tip_svg)
    svg_per_tx = (C[2]-C[0])/(tw-1)
    svg_per_ty = (C[3]-C[1])/(th-1)
    print('== %s tip %s dir %s (R=render T=thumb, 1 cell = 1 thumb px ~28 svg)'
          % (name, tip_svg, dirv))
    # orient: rows go from behind-tip to tip; cols perpendicular
    # build basis: along = -u (from tip backward), perp = (-uy, ux)
    al = (-u[0], -u[1]); pe = (-u[1], u[0])
    for iy in range(-2, span+3):        # along distance (0 = tip)
        lr = ''; lt = ''
        for ix in range(-7, 8):         # perpendicular
            ox = al[0]*iy + pe[0]*ix
            oy = al[1]*iy + pe[1]*ix
            tpx = int(round(tt[0] + ox)); tpy = int(round(tt[1] + oy))
            v = lum(T, tn, tpx, tpy, tw, th)
            lt += '#' if v < 170 else ('+' if v < 235 else '.')
            sx = tip_svg[0] + ox*svg_per_tx
            sy = tip_svg[1] + oy*svg_per_ty
            rpx = sx*K*SC; rpy = sy*K*SC
            v = min(lum(R, rn, int(rpx)+dx, int(rpy)+dy, rw, rh)
                    for dx in (0, 1) for dy in (0, 1))
            lr += '#' if v < 170 else ('+' if v < 235 else '.')
        print('   R %s | T %s   (back %d px)' % (lr, lt, iy))
    print()

if len(sys.argv) > 1 and sys.argv[1] in ('arrows', 'all'):
    fine('e32 up', (5493, 9701), (0, -1))
    fine('s19 right', (12493, 10951), (1, 0))
    fine('e34 down', (1993, 13201), (0, 1))
    fine('s14 left', (2493, 11451), (-1, 0))
    fine('s16 right', (8243, 11951), (1, 0))
