#!/usr/bin/env python3
"""verify3: (a) locate missing edge samples, (b) arrowhead profiles render vs
thumbnail, (c) tolerant mismatch clusters. Files see verify_common.py."""

from verify_common import *  # noqa: F401,F403
from collections import deque
import argparse

WANT_ARROWS = ('e32', 's19', 'e35', 's14', 's18')


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    V_ = V(args)
    C = V_.C; tw, th = V_.tdims()

    def dark_r(x, y, rad=4, thr=170):
        return dark_near(V_.R, V_.rn, V_.rw, V_.rh, x, y, rad, thr)

    # ---- (a) failing edges: missing sample locations (svg) --------------
    print('--- failing edges: missing sample locations (svg) ---')
    edges = [c for c in V_.cells if c['pts'] and len(c['pts']) >= 2]
    shown = 0
    for c in edges:
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
                if not dark_r(x, y):
                    miss.append((t, round((p[0]+(q[0]-p[0])*t)/K),
                                 round((p[1]+(q[1]-p[1])*t)/K)))
            if len(miss) > max(1, (n+1)//12):
                segs.append((i, round(p[0]/K), round(p[1]/K), round(q[0]/K),
                             round(q[1]/K), len(miss), n+1))
        if segs and shown < 8:
            shown += 1
            print('  %s pts(svg)=%s' % (c['id'],
                  [(round(x/K), round(y/K)) for x, y in pts]))
            for s in segs[:6]:
                print('     seg %d (%d,%d)->(%d,%d): %d/%d missing' % s)
    print('  (failing cells shown: %d / %d checked)' % (shown, len(edges)))

    # ---- (b) arrow profiles ----------------------------------------------
    print('--- arrow profile: halfwidth(svg) vs distance behind tip(svg) ---')
    ids = {c['id'] for c in V_.cells}

    def profile(rows, nch, W, H, tip_img, u, px_per_svg, ds, smax_svg):
        out = []
        for d in ds:
            cx = tip_img[0] - u[0]*d*px_per_svg
            cy = tip_img[1] - u[1]*d*px_per_svg
            hw = 0
            for s in range(1, int(smax_svg*px_per_svg)+1):
                a = dark(rows, nch, int(cx-u[1]*s), int(cy+u[0]*s), W, H) or \
                    dark(rows, nch, int(cx+u[1]*s), int(cy-u[0]*s), W, H)
                if a:
                    hw = s
                elif s > hw + 3:
                    break
            out.append((d, round(hw/px_per_svg)))
        return out

    ds = [20, 40, 60, 80, 100, 120, 140, 160, 180, 200, 240, 280, 320, 400]
    for c in V_.cells:
        if c['id'] in WANT_ARROWS and 'endArrow=' in c['style']:
            tip = c['pts'][-1]; prv = c['pts'][-2]
            dx, dy = tip[0]-prv[0], tip[1]-prv[1]
            n = math.hypot(dx, dy); u = (dx/n, dy/n)
            pr = profile(V_.R, V_.rn, V_.rw, V_.rh, (tip[0]*SCALE, tip[1]*SCALE),
                         u, K*SCALE, ds, 260)
            tt = V_.to_t(tip[0], tip[1]); pp = V_.to_t(prv[0], prv[1])
            dv = (tt[0]-pp[0], tt[1]-pp[1]); n2 = math.hypot(*dv); u2 = (dv[0]/n2, dv[1]/n2)
            ts = (C[2]-C[0])/tw                        # svg per thumb px
            pt = profile(V_.T, V_.tn, tw, th, tt, u2, 1.0/ts, ds, 260)
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
                                if 0 <= xx < w:
                                    rr[xx] = 1
        return out

    x0, y0 = C[0]*K*SCALE, C[1]*K*SCALE
    x1, y1 = C[2]*K*SCALE, C[3]*K*SCALE
    R = [[0]*tw for _ in range(th)]
    T = [[0]*tw for _ in range(th)]
    for ty_ in range(th):
        for tx_ in range(tw):
            px_ = int(x0 + (tx_+0.5)/tw*(x1-x0))
            py_ = int(y0 + (ty_+0.5)/th*(y1-y0))
            if any(dark(V_.R, V_.rn, px_+dx, py_+dy, V_.rw, V_.rh)
                   for dx in (-2, -1, 0, 1, 2) for dy in (-2, -1, 0, 1, 2)):
                R[ty_][tx_] = 1
            if any(dark(V_.T, V_.tn, tx_+dx, ty_+dy, tw, th)
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                T[ty_][tx_] = 1
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
            if not v or seen[yy][xx]:
                continue
            q = deque([(xx, yy)]); seen[yy][xx] = True
            n1 = n2 = 0; bx = [xx, xx]; by = [yy, yy]
            while q:
                cx, cy = q.popleft(); w_ = grid[cy][cx]
                if w_ == 1:
                    n1 += 1
                elif w_ == 2:
                    n2 += 1
                bx = [min(bx[0], cx), max(bx[1], cx)]
                by = [min(by[0], cy), max(by[1], cy)]
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                               (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = cx+dx, cy+dy
                    if 0 <= nx < tw and 0 <= ny < th \
                            and grid[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True; q.append((nx, ny))
            if n1+n2 >= 10:
                sxb = (C[0] + bx[0]/(tw-1)*(C[2]-C[0]),
                       C[1] + by[0]/(th-1)*(C[3]-C[1]),
                       C[0] + bx[1]/(tw-1)*(C[2]-C[0]),
                       C[1] + by[1]/(th-1)*(C[3]-C[1]))
                kind = 'thumb-only' if n1 > n2 else 'render-only'
                clusters.append((n1+n2, kind, tuple(round(v) for v in sxb)))
    clusters.sort(reverse=True)
    for n, kind, bb in clusters[:30]:
        print('  %-12s %4d px  svg bbox %s' % (kind, n, bb))


if __name__ == '__main__':
    main()