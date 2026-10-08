#!/usr/bin/env python3
"""verify5: per-text ink bbox/centroid comparison render vs thumbnail."""
import re, zlib, struct

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

xml = open(CWD + 'cpu2.drawio').read()
texts = []
for m in re.finditer(r'<mxCell id="(t\d+)" value="([^"]*)" style="([^"]*)"[^>]*>\s*'
                     r'<mxGeometry x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" '
                     r'height="([-\d.]+)"', xml):
    cid, val = m.group(1), m.group(2)
    x, y, w, h = (float(v) for v in m.groups()[3:])
    # page px -> svg
    texts.append((cid, val.replace('&lt;br&gt;', '/').replace('&amp;', '&'),
                  x/K, y/K, (x+w)/K, (y+h)/K))

def stats(rows, nch, w, h, x0, y0, x1, y1, to_img):
    sx0, sy0 = to_img(x0, y0); sx1, sy1 = to_img(x1, y1)
    n = 0; sxx = syy = 0.0
    bx0, by0, bx1, by1 = 1e9, 1e9, -1e9, -1e9
    ys = range(int(min(sy0, sy1)), int(max(sy0, sy1)) + 1)
    xs = range(int(min(sx0, sx1)), int(max(sx0, sx1)) + 1)
    for yy in ys:
        for xx in xs:
            if lum(rows, nch, xx, yy, w, h) < 170:
                n += 1; sxx += xx; syy += yy
                bx0 = min(bx0, xx); bx1 = max(bx1, xx)
                by0 = min(by0, yy); by1 = max(by1, yy)
    if not n: return None
    return (n, sxx/n, syy/n, bx0, by0, bx1, by1)

def to_r(x, y): return x*K*SC, y*K*SC
def to_t(x, y):
    return ((x-C[0])/(C[2]-C[0])*(tw-1), (y-C[1])/(C[3]-C[1])*(th-1))

print('%-14s %6s %6s | %-28s | centroid delta (svg)' % ('text', 'nR', 'nT', 'ink bbox ratio (w,h)'))
worst = 0
for cid, val, x0, y0, x1, y1 in texts:
    mr = stats(R, rn, rw, rh, x0-30, y0-30, x1+30, y1+30, to_r)
    mt = stats(T, tn, tw, th, x0-30, y0-30, x1+30, y1+30, to_t)
    if not mr or not mt:
        print('%-14s MISSING %s %s' % (val, mr, mt)); continue
    # bbox in svg
    rb = (mr[3]/(K*SC), mr[4]/(K*SC), mr[5]/(K*SC), mr[6]/(K*SC))
    tb = (C[0] + mt[3]/(tw-1)*(C[2]-C[0]), C[1] + mt[4]/(th-1)*(C[3]-C[1]),
          C[0] + mt[5]/(tw-1)*(C[2]-C[0]), C[1] + mt[6]/(th-1)*(C[3]-C[1]))
    rw_svg = rb[2]-rb[0]; rh_svg = rb[3]-rb[1]
    tw_svg = tb[2]-tb[0]; th_svg = tb[3]-tb[1]
    rcx = C[0] + mr[1]/(K*SC*(C[2]-C[0])/(C[2]-C[0]))*0 or 0
    rcx = mr[1]/(K*SC)  # render centroid -> svg x (offset: render px = svg*K*SC + 0)
    rcy = mr[2]/(K*SC)
    tcx = C[0] + mt[1]/(tw-1)*(C[2]-C[0])
    tcy = C[1] + mt[2]/(th-1)*(C[3]-C[1])
    dx, dy = rcx - tcx, rcy - tcy
    # note: render px origin maps svg 0 -> 0? content starts at svg493 -> render 37.27
    # render px = svg * K * SC exactly (page coords), so centroid svg = px/(K*SC)
    worst = max(worst, abs(dx), abs(dy))
    print('%-14s %6d %6d | %4.0fx%-4.0f vs %4.0fx%-4.0f | d=(%+5.0f,%+5.0f)'
          % (val, mr[0], mt[0], rw_svg, rh_svg, tw_svg, th_svg, dx, dy))
print('worst centroid delta: %.0f svg (%.1f thumb px)' % (worst, worst/28.4))
