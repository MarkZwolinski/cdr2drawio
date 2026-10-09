#!/usr/bin/env python3
"""Per-text ink bbox/centroid comparison render vs thumbnail. See
README docstring in verify_common.py for the mapping conventions."""

from verify_common import *  # noqa: F401,F403  (K, SCALE, V, add_args, parser helpers)

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
    if not n:
        return None
    return (n, sxx/n, syy/n, bx0, by0, bx1, by1)


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    V_ = V(args)
    tw, th = V_.tdims()
    K_ = K * SCALE                     # svg -> render px
    print('render %dx%d  thumb %dx%d' % (V_.rw, V_.rh, tw, th))

    txt = []
    for c in V_.cells:
        if c['id'].startswith('t') and c['geo']:
            x, y, w, h = c['geo']
            txt.append((c['id'], c['val'].replace('&lt;br&gt;', '/').replace('&amp;', '&'),
                        x/K, y/K, (x+w)/K, (y+h)/K))

    print('%-14s %6s %6s | %-28s | centroid delta (svg)' % ('text', 'nR', 'nT', 'ink bbox ratio (w,h)'))
    worst = 0
    for cid, val, x0, y0, x1, y1 in txt:
        mr = stats(V_.R, V_.rn, V_.rw, V_.rh, x0-30, y0-30, x1+30, y1+30, V_.to_r)
        mt = stats(V_.T, V_.tn, tw, th, x0-30, y0-30, x1+30, y1+30, V_.to_t)
        if not mr or not mt:
            print('%-14s MISSING %s %s' % (val, mr, mt)); continue
        rb = (mr[3]/K_, mr[4]/K_, mr[5]/K_, mr[6]/K_)
        C = V_.C
        tb = (C[0] + mt[3]/(tw-1)*(C[2]-C[0]), C[1] + mt[4]/(th-1)*(C[3]-C[1]),
              C[0] + mt[5]/(tw-1)*(C[2]-C[0]), C[1] + mt[6]/(th-1)*(C[3]-C[1]))
        rcx = mr[1]/K_                    # render centroid -> svg
        rcy = mr[2]/K_
        tcx = C[0] + mt[1]/(tw-1)*(C[2]-C[0])
        tcy = C[1] + mt[2]/(th-1)*(C[3]-C[1])
        dx, dy = rcx - tcx, rcy - tcy
        rbs = rb; rw_svg = rbs[2]-rbs[0]; rh_svg = rbs[3]-rbs[1]
        tw_svg = tb[2]-tb[0]; th_svg = tb[3]-tb[1]
        worst = max(worst, abs(dx), abs(dy))
        print('%-14s %6d %6d | %4.0fx%-4.0f vs %4.0fx%-4.0f | d=(%+5.0f,%+5.0f)'
              % (val, mr[0], mt[0], rw_svg, rh_svg, tw_svg, th_svg, dx, dy))
    print('worst centroid delta: %.0f svg (%.1f thumb px)' % (worst, worst/28.4))


if __name__ == '__main__':
    main()