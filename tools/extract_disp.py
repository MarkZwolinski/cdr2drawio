#!/usr/bin/env python3
"""Extract every embedded 'DISP' bitmap (Corel thumbnail) from a CDR and write
canonical RGB PNGs. Reuses cdr2drawio.py's container/path walking."""
import os
import struct
import sys
import zlib

sys.path.insert(0, '/Users/mark/Projects/cdr2drawio')
from cdr2drawio import Cdr  # noqa: E402


def write_png(path, w, h, rows):
    def chunk(typ, data):
        c = struct.pack('>I', len(data)) + typ + data
        return c + struct.pack('>I', zlib.crc32(typ + data) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    raw = b''.join(b'\x00' + bytes(row) for row in rows)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', zlib.compress(raw, 9)))
        f.write(chunk(b'IEND', b''))


def decode_disp(payload):
    if payload[:2] == b'BM':
        base = 14          # standard BMP file header
    else:
        base = 4           # Corel DISP: 4 'unknown' bytes then a DIB header
    if len(payload) < base + 40:
        return None
    off0 = payload[base:base+4]
    bpp = struct.unpack_from('<H', payload, base + 14)[0]
    comp = struct.unpack_from('<I', payload, base + 16)[0]
    if off0[:2] == b'BM':        # embedded BMP at base: use its pixel offset
        off = struct.unpack_from('<I', payload, base + 10)[0]
    else:
        off = base + 40
    w = struct.unpack_from('<i', payload, base + 4)[0]
    h = struct.unpack_from('<i', payload, base + 8)[0]
    ncolors = struct.unpack_from('<I', payload, base + 32)[0]
    if ncolors == 0:
        ncolors = 256
    pal = [tuple(payload[base + 40 + 4*i:base + 40 + 4*i + 3])
           for i in range(ncolors)]
    if comp == 0:
        stride = ((w * bpp + 31) // 32) * 4
        rows = []
        for y in range(abs(h)):
            rows.append(payload[off + y*stride:off + (y+1)*stride])
        if h > 0:
            rows.reverse()
        return [[v for i in range(w) for v in pal[rows[y][i]]]
                for y in range(abs(h))]
    return None


def main():
    for cdr_path in sys.argv[1:]:
        base = os.path.splitext(os.path.basename(cdr_path))[0]
        cdr = Cdr(cdr_path)
        seen = set()
        for i, n in enumerate(cdr.nodes):
            if n['name'] != 'DISP':
                continue
            payload = cdr.deref(n, n['size'])
            name = '%s_disp%d.png' % (base, i)
            img = decode_disp(payload)
            if img is None:
                print('%s: DISP#%d undecodable (len=%d)' % (base, i, len(payload)))
                continue
            h = len(img); w = len(img[0]) // 3
            write_png('/tmp/' + name, w, h, img)
            print('%s: wrote /tmp/%s %dx%d' % (base, name, w, h))
            seen.add(id(n))
        # Some legacy files keep DISP at the top of the RIFF body, outside
        # the top-level cmpr stream that Cdr walks. Scan the raw bytes.
        raw = open(cdr_path, 'rb').read()
        off = 0
        while True:
            i = raw.find(b'DISP', off)
            if i < 0:
                break
            off = i + 1
            if i < 8:
                continue
            size = struct.unpack_from('<I', raw, i + 4)[0]
            if size > 4 * 1024 * 1024 or i + 8 + size > len(raw):
                continue
            payload = raw[i + 8:i + 8 + size]
            img = decode_disp(payload)
            if img is None:
                continue
            name = '%s_disp.png' % base
            h = len(img); w = len(img[0]) // 3
            if w == h == 96 and os.path.exists('/tmp/' + name):
                extras = 0
                while os.path.exists('/tmp/%s_disp%d.png' % (base, extras)):
                    extras += 1
                write_png('/tmp/%s_disp%d.png' % (base, extras), w, h, img)
            else:
                write_png('/tmp/' + name, w, h, img)
            print('%s: wrote /tmp/%s %dx%d (raw scan)' % (base, name, w, h))
            break


if __name__ == '__main__':
    main()