#!/usr/bin/env python3
"""End-to-end verify: parse drawio geometry, check ink in the render PNG,
measure arrowheads vs the Corel thumbnail, list mismatch clusters in svg space.
Files and mapping: see verify_common.py."""

from verify_common import *  # noqa: F401,F403
from collections import deque
import argparse


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
        if halfw*2 > best:
            best = halfw*2
    return best / sc   # page px


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    V_ = V(args)
    C = V_.C; tw, th = V_.tdims()
    rw, rh = V_.rw, V_.rh

    def dark_r(px_, py_, rad=3):
        return dark_near(V_.R, V_.rn, rw, rh, px_, py_, rad)

    def to_r(ppx, ppy):                  # page px -> render px
        return ppx * SCALE, ppy * SCALE

    print('render %dx%d  thumb %dx%d' % (rw, rh, tw, th))
    fails = 0

    # ---- edge ink checks -------------------------------------------------
    print('--- edge ink checks (render) ---')
    edges = [c for c in V_.cells if c['pts'] and len(c['pts']) >= 2]
    for c in edges:
        pts = c['pts']
        miss = tot = 0
        arrow = 'arrow' if 'endArrow=block' in c['style'] or \
            'startArrow=block' in c['style'] else ''
        if all(math.hypot(q[0]-p[0], q[1]-p[1]) < 10*K
               for p, q in zip(pts, pts[1:])):
            print('  %-8s %-28s SKIP (degenerate)  %s' % (c['id'], c['val'][:28], arrow))
            continue
        for i in range(len(pts)-1):
            p, q = pts[i], pts[i+1]
            L = math.hypot(q[0]-p[0], q[1]-p[1]) * SCALE
            n = max(2, int(L / 12))
            for j in range(n+1):
                t = j / n
                x, y = to_r(p[0] + (q[0]-p[0])*t, p[1] + (q[1]-p[1])*t)
                tot += 1
                if not dark_r(x, y, 4):
                    miss += 1
        ok = miss <= max(1, tot // 12)
        if not ok:
            fails += 1
        arrow = 'arrow' if 'endArrow=block' in c['style'] or \
            'startArrow=block' in c['style'] else ''
        print('  %-8s %-28s %s (%d/%d missing)  %s' %
              (c['id'], c['val'][:28] or c['style'][:28], 'OK  ' if ok else 'FAIL',
               miss, tot, arrow))

    # ---- rect ink checks ---------------------------------------------------
    print('--- rect edge checks (render) ---')
    for c in V_.cells:
        if c['id'].startswith('s') and c['geo'] and not c['pts']:
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
                    if not dark_r(px_, py_, 4):
                        miss += 1
            ok = miss <= max(1, tot // 12)
            if not ok:
                fails += 1
            print('  %-8s rect %s %s (%d/%d missing)' %
                  (c['id'], 'OK  ' if ok else 'FAIL', '', miss, tot))

    # ---- arrow size: render vs thumbnail ----------------------------------
    print('--- arrowhead size (svg units) ---')

    def svg_to_thumb(sx_, sy_):
        return ((sx_-C[0])/(C[2]-C[0])*(tw-1),
                (sy_-C[1])/(C[3]-C[1])*(th-1))

    for c in edges:
        st = c['style']
        if 'endArrow=block' in st:
            tip = c['pts'][-1]; prev = c['pts'][-2]
            dirv = (tip[0]-prev[0], tip[1]-prev[1])
            wr = measure_arrow(V_.R, V_.rn, rw, rh, tip, dirv, 30, 30, SCALE)
            wr_svg = wr / K
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
                    if dark(V_.T, V_.tn, int(cx-uy*s), int(cy+ux*s), tw, th, 180) or \
                       dark(V_.T, V_.tn, int(cx+uy*s), int(cy-ux*s), tw, th, 180):
                        hw = s
                if hw*2 > best:
                    best = hw*2
            t_svg = best * (C[2]-C[0]) / (tw-1)
            print('  %-6s base: render %.0f svg  thumb %.0f svg  %s'
                  % (c['id'], wr_svg, t_svg,
                     'OK' if abs(wr_svg - t_svg) < 0.45*max(t_svg, 1) else 'DIFF'))

    # ---- mismatch clusters (thumb-only / render-only) ---------------------
    print('--- mismatch clusters (svg bbox, size>=12 px) ---')
    x0, y0 = C[0]*K*SCALE, C[1]*K*SCALE
    x1, y1 = C[2]*K*SCALE, C[3]*K*SCALE
    grid = []
    for ty_ in range(th):
        row = []
        for tx_ in range(tw):
            px_ = int(x0 + (tx_+0.5)/tw*(x1-x0))
            py_ = int(y0 + (ty_+0.5)/th*(y1-y0))
            r = dark(V_.R, V_.rn, min(px_, rw-1), min(py_, rh-1), rw, rh, 180)
            t = dark(V_.T, V_.tn, tx_, ty_, tw, th, 180)
            row.append(1 if (t and not r) else (2 if (r and not t) else 0))
        grid.append(row)
    seen = [[False]*tw for _ in range(th)]
    clusters = []
    for yy in range(th):
        for xx in range(tw):
            v = grid[yy][xx]
            if not v or seen[yy][xx]:
                continue
            q = deque([(xx, yy)]); seen[yy][xx] = True
            n1 = n2 = 0; bx = [xx, xx]; by = [yy, yy]
            while q:
                cx, cy = q.popleft()
                w_ = grid[cy][cx]
                if w_ == 1:
                    n1 += 1
                elif w_ == 2:
                    n2 += 1
                bx[0] = min(bx[0], cx); bx[1] = max(bx[1], cx)
                by[0] = min(by[0], cy); by[1] = max(by[1], cy)
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = cx+dx, cy+dy
                    if 0 <= nx < tw and 0 <= ny < th \
                            and grid[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True; q.append((nx, ny))
            if n1+n2 >= 12:
                sx_ = C[0] + bx[0]/(tw-1)*(C[2]-C[0])
                sxe = C[0] + bx[1]/(tw-1)*(C[2]-C[0])
                sy_ = C[1] + by[0]/(th-1)*(C[3]-C[1])
                sye = C[1] + by[1]/(th-1)*(C[3]-C[1])
                kind = 'thumb-only' if n1 > n2 else 'render-only'
                clusters.append((n1+n2, kind, (round(sx_), round(sy_), round(sxe), round(sye))))
    clusters.sort(reverse=True)
    for n, kind, bb in clusters[:25]:
        print('  %-12s %4d px  svg bbox %s' % (kind, n, bb))
    print('FAILS: %d' % fails)


if __name__ == '__main__':
    main()