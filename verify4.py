#!/usr/bin/env python3
"""Density-based structural diff (robust to subpixel registration) plus fine
arrow probes. Optional argv: 'arrows' or 'all' to run the probe section."""

from verify_common import *  # noqa: F401,F403
import sys


def density(rows, nch, w, h, is_render, C, GW, GH):
    grid = [[0.0]*GW for _ in range(GH)]
    if is_render:
        x0, y0 = C[0]*K*SCALE, C[1]*K*SCALE
        x1, y1 = C[2]*K*SCALE, C[3]*K*SCALE
    else:
        x0, y0 = 0.0, 0.0
        x1, y1 = float(w-1), float(h-1)
    for gy in range(GH):
        sy0 = y0 + gy*(y1-y0)/GH
        sy1 = y0 + (gy+1)*(y1-y0)/GH
        for gx in range(GW):
            sx0 = x0 + gx*(x1-x0)/GW
            sx1 = x0 + (gx+1)*(x1-x0)/GW
            n = 0; ink = 0.0
            for iy in range(4):
                yy = int(sy0 + (sy1-sy0)*(iy+0.5)/4)
                for ix in range(4):
                    xx = int(sx0 + (sx1-sx0)*(ix+0.5)/4)
                    if 0 <= xx < w and 0 <= yy < h:
                        v = lum(rows, nch, xx, yy, w, h)
                        ink += (255.0-v)/255.0; n += 1
            grid[gy][gx] = ink/n if n else 0.0
    return grid


def fine(V_, name, tip_svg, dirv, span=8):
    u = dirv; n = math.hypot(*u); u = (u[0]/n, u[1]/n)
    def s2t(x, y):
        return ((x-C[0])/(C[2]-C[0])*(tw-1), (y-C[1])/(C[3]-C[1])*(th-1))
    C = V_.C; tw, th = V_.tdims()
    tt = s2t(*tip_svg)
    svg_per_tx = (C[2]-C[0])/(tw-1)
    svg_per_ty = (C[3]-C[1])/(th-1)
    print('== %s tip %s dir %s (1 cell = 1 thumb px ~%.0f svg)'
          % (name, tip_svg, dirv, (C[2]-C[0])/(tw-1)))
    al = (-u[0], -u[1]); pe = (-u[1], u[0])
    for iy in range(-2, span+3):
        lr = ''; lt = ''
        for ix in range(-7, 8):
            ox = al[0]*iy + pe[0]*ix
            oy = al[1]*iy + pe[1]*ix
            tpx = int(round(tt[0] + ox)); tpy = int(round(tt[1] + oy))
            v = lum(V_.T, V_.tn, tpx, tpy, tw, th)
            lt += '#' if v < 170 else ('+' if v < 235 else '.')
            sx = tip_svg[0] + ox*svg_per_tx
            sy = tip_svg[1] + oy*svg_per_ty
            rpx = sx*K*SCALE; rpy = sy*K*SCALE
            v = min(lum(V_.R, V_.rn, int(rpx)+dx, int(rpy)+dy, V_.rw, V_.rh)
                    for dx in (0, 1) for dy in (0, 1))
            lr += '#' if v < 170 else ('+' if v < 235 else '.')
        print('   R %s | T %s   (back %d px)' % (lr, lt, iy))
    print()


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    ap.add_argument('--probe', action='store_true',
                    help='also print fine arrow probes')
    args = ap.parse_args()
    V_ = V(args)
    C = V_.C; tw, th = V_.tdims()
    GW, GH = 136, 64

    dr = density(V_.R, V_.rn, V_.rw, V_.rh, True, C, GW, GH)
    dt = density(V_.T, V_.tn, tw, th, False, C, GW, GH)
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
    ir = sum(sum(r) for r in dr); it = sum(sum(r) for r in dt)
    print('total ink: render %.1f  thumb %.1f  ratio %.3f' % (ir, it, ir/it))

    if args.probe:
        arrow_tips = [  # (name, tip svg, unit dir) from known arrow cells
            ('e32 up', (5493, 9701), (0, -1)),
            ('s19 right', (12493, 10951), (1, 0)),
            ('e34 down', (1993, 13201), (0, 1)),
            ('s14 left', (2493, 11451), (-1, 0)),
            ('s16 right', (8243, 11951), (1, 0)),
        ]
        ids = {c['id'] for c in V_.cells}
        for name, tip, d in arrow_tips:
            cid = name.split()[0]
            if cid in ids:
                fine(V_, name, tip, d)


if __name__ == '__main__':
    main()