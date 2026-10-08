#!/usr/bin/env python3
"""Verify cpu2_render.png (draw.io export of cpu2.drawio) against the Corel
thumbnail: global mask agreement + per-element line/arrow/text checks."""
import struct, zlib, sys, math

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
            elif f == 3: line[x] = (line[x] + (a + b)//2) & 255
            elif f == 4:
                p = a + b - c; pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        rows.append(bytes(line)); prev = line
    return w, h, nch, rows

def lum(rows, nch, px, py):
    p = rows[py][px*nch:(px+1)*nch]
    if len(p) < 3: return 255
    return (p[0]+p[1]+p[2]) / 3.0

# --- geometry constants (svg units) --------------------------------------
K = 96.0 / 2540.0                       # svg -> page px
S = 2                                   # export scale
CONTENT = (493, 8201, 15993, 15463)     # union bbox of all objects

def rx(sx): return sx * K * S            # content-relative? no: page px * S
def to_render(sx_, sy_):                # svg -> render pixel
    return sx_ * K * S, sy_ * K * S

rw, rh, rn, rrows = read_png('cpu2_render.png')
tw, th, tn, trows = read_png('thumbnail.png')
print('render %dx%d  thumb %dx%d' % (rw, rh, tw, th))

# thumbnail mapping: content bbox -> (0,0)-(tw,th)
def tmap(sx_, sy_):
    x = (sx_ - CONTENT[0]) / (CONTENT[2] - CONTENT[0]) * tw
    y = (sy_ - CONTENT[1]) / (CONTENT[3] - CONTENT[1]) * th
    return x, y

# ---- 1. global comparison: downsample render crop to thumb size -------
x0, y0 = to_render(CONTENT[0], CONTENT[1])
x1, y1 = to_render(CONTENT[2], CONTENT[3])
crop_w, crop_h = x1 - x0, y1 - y0
agree = both = only_r = only_t = 0
diff_map = []
for ty_ in range(th):
    row = []
    for tx_ in range(tw):
        # sample render
        px = int(x0 + (tx_ + 0.5) / tw * crop_w)
        py = int(y0 + (ty_ + 0.5) / th * crop_h)
        r = lum(rrows, rn, min(px, rw-1), min(py, rh-1)) < 180
        t = lum(trows, tn, tx_, ty_) < 180
        row.append((r, t))
        if r and t: both += 1
        elif r: only_r += 1
        elif t: only_t += 1
        else: agree += 1
    diff_map.append(row)
tot = tw * th
print('pixel agreement: both-dark %d (%.1f%%)  render-only %d (%.1f%%)  '
      'thumb-only %d (%.1f%%)  both-white %d (%.1f%%)'
      % (both, 100.0*both/tot, only_r, 100.0*only_r/tot,
         only_t, 100.0*only_t/tot, agree, 100.0*agree/tot))
iou = both / float(both + only_r + only_t)
print('ink IoU: %.3f' % iou)

# coarse ASCII diff (4x downsample): R=render only, T=thumb only, X=both, #=neither skipped
print('--- diff map (R=render-only, T=thumb-only, .=ok) ---')
BS = 4
for y in range(0, th, BS):
    line = ''
    for x in range(0, tw, BS):
        rr = tt = 0
        for dy in range(BS):
            for dx in range(BS):
                if x+dx < tw and y+dy < th:
                    r, t = diff_map[y+dy][x+dx]
                    rr += r; tt += t
        if rr and tt: line += 'X'
        elif rr: line += 'R'
        elif tt: line += 'T'
        else: line += '.'
    print(line)

# ---- 2. per-element checks on the full-res render ----------------------
def dark_near(sx_, sy_, rad=2):
    px, py = to_render(sx_, sy_)
    for dy in range(-rad, rad+1):
        for dx in range(-rad, rad+1):
            x, y = int(px+dx), int(py+dy)
            if 0 <= x < rw and 0 <= y < rh and lum(rrows, rn, x, y) < 160:
                return True
    return False

def check_line(p, q, name):
    n = max(2, int(math.hypot(q[0]-p[0], q[1]-p[1]) / 15))
    miss = 0
    for i in range(n+1):
        t = i / n
        x = p[0] + (q[0]-p[0])*t
        y = p[1] + (q[1]-p[1])*t
        if not dark_near(x, y, 3):
            miss += 1
    ok = miss <= max(1, n // 10)
    print('  %-34s %s (%d/%d missing)' % (name, 'OK  ' if ok else 'FAIL', miss, n+1))
    return ok

lines = [
    # rects (edges)
    ('R IMEM', (1493,13201), (5493,15201)),
    ('R DMEM', (11743,13201), (15243,15201)),
    ('R PC', (493,10701), (2493,12201)),
    ('R IR', (4493,10701), (6493,12201)),
    ('R Decoder', (4243,8201), (6743,9701)),
    ('R REG', (12493,10451), (13993,11451)),
    # polylines
    ('P14 DMEM wire', (7243,11451), (11743,14951)),
    ('P15 IR-PC', (4493,11451), (2493,11451)),
    ('P16 to MUX', (11743,14201), (7743,14201)),
    ('P17 DMEM right', (14993,10951), (15993,14201)),
    ('P18 L-shape', (13993,10951), (14993,8451)),
    ('P19 ALU out', (11243,10951), (12493,10951)),
    ('P20 MUX out', (8743,11701), (9993,11701)),
    ('P21 REG to MUX', (6493,11451), (8243,11451)),
    ('P22 MUX top', (8243,11201), (8743,11451)),
    ('P22 MUX left', (8243,11201), (8243,12201)),
    # connectors
    ('C24 ALU left lo', (9993,11201), (9993,12701)),
    ('C25 notch lo', (10243,10951), (9993,11201)),
    ('C26 notch hi', (9993,10701), (10243,10951)),
    ('C27 degenerate', (11493,11201), (11493,11204)),
    ('C28 ALU left hi', (9993,9201), (9993,10701)),
    ('C29 ALU top', (9993,9201), (11243,9701)),
    ('C30 ALU bottom', (11243,12201), (9993,12701)),
    ('C31 ALU right', (11243,9701), (11243,12201)),
    ('C32 Dec-IR', (5498,10701), (5493,9701)),
    ('C34 PC-IMEM', (1988,12201), (1993,13201)),
    ('C35 IMEM-IR', (5015,13201), (4988,12201)),
]
print('--- element checks (render) ---')
fails = 0
for name, p, q in lines:
    if not check_line(p, q, name):
        fails += 1

# ---- 3. arrowheads at expected tips -----------------------------------
print('--- arrowhead checks ---')
tips = [
    ('a15 @2493,11451 left', (2493,11451), (-1, 0)),
    ('a14 @11743,14951 right', (11743,14951), (1, 0)),
    ('a16 @8243,11951 right', (8243,11951), (1, 0)),
    ('a17 @15243,14201 left', (15243,14201), (-1, 0)),
    ('a18 @9993,10201 right', (9993,10201), (1, 0)),
    ('a19 @12493,10951 right', (12493,10951), (1, 0)),
    ('a20 @9993,11701 right', (9993,11701), (1, 0)),
    ('a21 @8243,11451 right', (8243,11451), (1, 0)),
    ('a32 @5493,9701 up', (5493,9701), (0, -1)),
    ('a34 @1993,13201 down', (1993,13201), (0, 1)),
    ('a35 @4988,12201 up', (4988,12201), (0, -1)),
]
for name, tip, d in tips:
    # measure how far back from the tip the ink is thick (arrow body)
    L = 0
    for step in range(0, 40):
        dist = step * 10  # svg units
        x = tip[0] + d[0] * (-dist) if False else tip[0] - d[0]*dist
        y = tip[1] - d[1]*dist
        if dark_near(x, y, 2):
            L = dist
        else:
            break
    # width of ink perpendicular at 1/3 back
    px_, py_ = to_render(tip[0] - d[0]*L*0.5, tip[1] - d[1]*L*0.5)
    wd = 0
    for step in range(-30, 31):
        x = tip[0] - d[0]*L*0.5 + (-d[1])*step*10
        y = tip[1] - d[1]*L*0.5 + (d[0])*step*10
        if dark_near(x, y, 2):
            wd = abs(step)*10
    print('  %-24s ink-back=%d svg, width~%d svg  %s'
          % (name, L, wd, 'OK' if L >= 60 else 'THIN'))

# ---- 4. text glyph presence -------------------------------------------
print('--- text checks ---')
texts = [
    ('REG', 12600,10716,13886,11186), ('op', 5743,10040,6331,10451),
    ('branch-addr', 2847,10160,4743,11201), ('Idata', 5287,12540,6493,12951),
    ('operand', 6490,10671,8557,11187), ('Adata', 8341,12252,9811,12662),
    ('Rdata', 8769,13547,10232,13958), ('Iaddress', 2068,12539,4202,12949),
    ('Wdata', 14116,11521,15660,11931), ('Daddress', 8237,15052,10628,15463),
    ('ALU', 10058,10201,11243,10663), ('IR', 5209,11224,5777,11678),
    ('Decoder', 4366,8738,6725,9200), ('PC', 1089,11216,1897,11686),
    ('DMEM', 12572,13974,14414,14428), ('IMEM', 2718,13974,4268,14428),
]
for name, a, b, c, d in texts:
    dark = 0
    for yy in range(b, d+1, 8):
        for xx in range(a, c+1, 8):
            if dark_near(xx, yy, 2):
                dark += 1
    total = len(range(b, d+1, 8)) * len(range(a, c+1, 8))
    frac = dark / total
    print('  %-12s ink coverage %.0f%%  %s' % (name, 100*frac,
          'OK' if frac > 0.08 else 'MISSING'))

print('FAILS: %d' % fails)
