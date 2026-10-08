#!/usr/bin/env python3
"""ASCII probes: render vs thumbnail at specific svg-space regions."""
import math, zlib, struct, sys
sys.path.insert(0, '/var/folders/9m/6zlh4bns5x5b04x4b3shf8dc0000gn/T/opencode/cdr')

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
    if not (0 <= x < w and 0 <= y < h): return 255
    p = rows[y][x*nch:(x+1)*nch]
    return 255 if len(p) < 3 else (p[0]+p[1]+p[2])/3.0

def patch(name, sx0, sy0, sx1, sy1, step_svg=None):
    """Print aligned ascii patches of render & thumb covering svg rect."""
    w_svg = sx1-sx0; h_svg = sy1-sy0
    # render patch
    rx0, ry0 = sx0*K*SC, sy0*K*SC
    rx1, ry1 = sx1*K*SC, sy1*K*SC
    step_r = max(1, int(math.ceil(max((rx1-rx0)/100.0, (ry1-ry0)/60.0))))
    rows_r = []
    y = ry0
    while y < ry1:
        line = ''
        x = rx0
        while x < rx1:
            v = min(lum(R, rn, int(x+dx), int(y+dy), rw, rh)
                    for dx in (0, step_r) for dy in (0, step_r))
            line += '#' if v < 170 else ('+' if v < 235 else '.')
            x += step_r
        rows_r.append(line); y += step_r
    # thumb patch
    tx0, ty0 = (sx0-C[0])/(C[2]-C[0])*(tw-1), (sy0-C[1])/(C[3]-C[1])*(th-1)
    tx1, ty1 = (sx1-C[0])/(C[2]-C[0])*(tw-1), (sy1-C[1])/(C[3]-C[1])*(th-1)
    step_t = max(1, int(math.ceil(max((tx1-tx0)/100.0, (ty1-ty0)/60.0))))
    rows_t = []
    y = ty0
    while y < ty1:
        line = ''
        x = tx0
        while x < tx1:
            v = min(lum(T, tn, int(x+dx), int(y+dy), tw, th)
                    for dx in (0, step_t) for dy in (0, step_t))
            line += '#' if v < 170 else ('+' if v < 235 else '.')
            x += step_t
        rows_t.append(line); y += step_t
    print('== %s  svg (%d,%d)-(%d,%d) ==' % (name, sx0, sy0, sx1, sy1))
    print('   RENDER%s   |   THUMB' % (' '*(max(len(r) for r in rows_r)-6)))
    n = max(len(rows_r), len(rows_t))
    for i in range(n):
        a = rows_r[i] if i < len(rows_r) else ''
        b = rows_t[i] if i < len(rows_t) else ''
        print('   %-100s|   %s' % (a, b))
    print()

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if mode in ('all', 'e32'):
        # e32 arrow tip (5493,9701) direction up (toward y decreasing)
        patch('e32 arrow tip', 5300, 9450, 5700, 10300)
    if mode in ('all', 'edges'):
        patch('DMEM top edge y=13201', 11700, 13050, 12300, 13350)
        patch('PC left edge x=493', 350, 10650, 950, 11250)
    if mode in ('all', 's14'):
        patch('s14 wire', 7100, 11350, 7800, 15100)
    if mode in ('all', 's16'):
        patch('s16 wire', 7600, 11850, 11850, 14350)
    if mode in ('all', 's17'):
        patch('s17 wire', 14850, 10850, 16100, 14350)
    if mode in ('all', 's18'):
        patch('s18 wire', 9150, 8350, 15100, 11050)
    if mode in ('all', 's19arrow'):
        patch('s19 arrow', 12150, 10750, 12750, 11150)
