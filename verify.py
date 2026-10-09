#!/usr/bin/env python3
"""Verify the draw.io render against a Corel thumbnail: global mask agreement
plus per-element line/arrow/text checks derived from the drawio geometry.
Files and mapping: see verify_common.py."""

from verify_common import *  # noqa: F401,F403
import argparse


def main():
    ap = argparse.ArgumentParser()
    add_args(ap)
    args = ap.parse_args()
    V_ = V(args)
    C = V_.C; tw, th = V_.tdims()
    rw, rh = V_.rw, V_.rh
    print('render %dx%d  thumb %dx%d' % (rw, rh, tw, th))

    def lum_r(x, y):
        if 0 <= x < rw and 0 <= y < rh:
            return lum(V_.R, V_.rn, x, y, rw, rh)
        return 255.0

    def dark_svg(sx, sy, rad=2):
        return dark_near(V_.R, V_.rn, rw, rh, sx*K*SCALE, sy*K*SCALE, rad)

    # ---- 1. global comparison: downsample render crop to thumb size ------
    x0, y0 = V_.to_r(C[0], C[1])
    x1, y1 = V_.to_r(C[2], C[3])
    crop_w, crop_h = x1 - x0, y1 - y0
    agree = both = only_r = only_t = 0
    diff_map = []
    for ty_ in range(th):
        row = []
        for tx_ in range(tw):
            px = int(x0 + (tx_ + 0.5) / tw * crop_w)
            py = int(y0 + (ty_ + 0.5) / th * crop_h)
            r = lum_r(min(px, rw-1), min(py, rh-1)) < 180
            t = lum(V_.T, V_.tn, tx_, ty_, tw, th) < 180
            row.append((r, t))
            if r and t:
                both += 1
            elif r:
                only_r += 1
            elif t:
                only_t += 1
            else:
                agree += 1
        diff_map.append(row)
    tot = tw * th
    print('pixel agreement: both-dark %d (%.1f%%)  render-only %d (%.1f%%)  '
          'thumb-only %d (%.1f%%)  both-white %d (%.1f%%)'
          % (both, 100.0*both/tot, only_r, 100.0*only_r/tot,
             only_t, 100.0*only_t/tot, agree, 100.0*agree/tot))
    iou = both / float(both + only_r + only_t)
    print('ink IoU: %.3f' % iou)
    if iou < 0.25:
        print('WARNING: thumb does not register with the render (IoU %.2f); this '
              'image may be a placeholder preview. Mask-based checks below are '
              'unreliable - rely on the per-element checks, or pass --content.' % iou)
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
            if rr and tt:
                line += 'X'
            elif rr:
                line += 'R'
            elif tt:
                line += 'T'
            else:
                line += '.'
        print(line)

    # ---- 2. per-element line checks -------------------------------------
    fails = 0

    def check_line(p, q, name):
        nonlocal fails
        if math.hypot(q[0]-p[0], q[1]-p[1]) < 10:      # degenerate (invisible)
            print('  %-34s SKIP (degenerate, %.0f svg)' % (name, math.hypot(q[0]-p[0], q[1]-p[1])))
            return True
        n = max(2, int(math.hypot(q[0]-p[0], q[1]-p[1]) / 15))
        miss = 0
        for i in range(n+1):
            t = i / n
            x = p[0] + (q[0]-p[0])*t
            y = p[1] + (q[1]-p[1])*t
            if not dark_svg(x, y, 3):
                miss += 1
        ok = miss <= max(1, n // 10)
        if not ok:
            fails += 1
        print('  %-34s %s (%d/%d missing)' % (name, 'OK  ' if ok else 'FAIL', miss, n+1))
        return ok

    print('--- element checks (render) ---')
    for c in V_.cells:
        pts = [(p[0]/K, p[1]/K) for p in c['pts']]
        if c['id'].startswith('s') and c['geo'] and not pts:
            x, y, w, h = (v/K for v in c['geo'])
            corners = [(x, y), (x+w, y), (x+w, y+h), (x, y+h)]
            for i in range(4):
                check_line(corners[i], corners[(i+1) % 4],
                           '%s rect side%d' % (c['id'], i+1))
        elif len(pts) >= 2:
            for i in range(len(pts)-1):
                check_line(pts[i], pts[i+1],
                           '%s %s' % (c['id'], c['val'][:22] or c['style'][:22]))

    # ---- 3. arrowheads at expected tips ----------------------------------
    print('--- arrowhead checks ---')
    for c in V_.cells:
        st = c['style']
        pts = [(p[0]/K, p[1]/K) for p in c['pts']]
        if len(pts) < 2:
            continue
        is_end = 'endArrow=block' in st or 'endArrow=' in st and 'triangle' in st
        is_sta = 'startArrow=block' in st or 'startArrow=' in st and 'triangle' in st
        if not is_end and not is_sta:
            continue
        if is_end:
            tip = pts[-1]; ref = pts[-2]
            d = (tip[0]-ref[0], tip[1]-ref[1])
        else:
            tip = pts[0]; ref = pts[1]
            d = (tip[0]-ref[0], tip[1]-ref[1])
        dn = math.hypot(*d) or 1.0
        d = (d[0]/dn, d[1]/dn)
        L = 0
        for step in range(0, 40):
            dist = step * 10
            x = tip[0] - d[0]*dist
            y = tip[1] - d[1]*dist
            if dark_svg(x, y, 2):
                L = dist
            else:
                break
        px_, py_ = V_.to_r(tip[0] - d[0]*L*0.5, tip[1] - d[1]*L*0.5)
        wd = 0
        for step in range(-30, 31):
            x = tip[0] - d[0]*L*0.5 + (-d[1])*step*10
            y = tip[1] - d[1]*L*0.5 + (d[0])*step*10
            if dark_svg(x, y, 2):
                wd = abs(step)*10
        print('  %-24s ink-back=%d svg, width~%d svg  %s'
              % (c['id'], L, wd, 'OK' if L >= 60 else 'THIN'))

    # ---- 4. text glyph presence ------------------------------------------
    print('--- text checks ---')
    for c in V_.cells:
        if not c['id'].startswith('t') or not c['geo']:
            continue
        x, y, w, h = c['geo']
        a, b, cc_, d = int(x/K), int(y/K), int((x+w)/K), int((y+h)/K)
        dark_c = 0
        for yy in range(b, d+1, 8):
            for xx in range(a, cc_+1, 8):
                if dark_svg(xx, yy, 2):
                    dark_c += 1
        total = len(range(b, d+1, 8)) * len(range(a, cc_+1, 8))
        frac = dark_c / max(1, total)
        print('  %-12s ink coverage %.0f%%  %s'
              % (c['val'][:12], 100*frac, 'OK' if frac > 0.08 else 'MISSING'))

    print('FAILS: %d' % fails)


if __name__ == '__main__':
    main()