#!/usr/bin/env python3
"""Fail the build if the Mac AppIcon artwork lost its safe-area padding.

macOS renders Dock icons assuming the squircle occupies ~824px of the 1024px
canvas (~80.5%) with a transparent margin around it. Regenerating the icons
without that margin makes Fluent's Dock icon render ~24% larger than every
other app (regressed once already in the green rebrand, commit 1329b8b).

Usage: check-appicon-padding.py [appiconset_dir]
Stdlib only (minimal PNG decoder) so build scripts don't need Pillow.
"""

import struct
import sys
import zlib
from pathlib import Path

# Opaque content must stay within this fraction of the canvas per axis.
# Correct padding gives ~80.5%; full-bleed artwork is 100%.
MAX_CONTENT_RATIO = 0.88

DEFAULT_ICONSET = (
    Path(__file__).resolve().parent.parent
    / "fluent/Fluent/Assets.xcassets/AppIcon.appiconset"
)


def alpha_bbox(png_path):
    """Return (width, height, bbox) where bbox is the opaque-pixel bounding
    box (left, top, right, bottom) exclusive, or None if fully transparent."""
    data = png_path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{png_path.name}: not a PNG")

    width = height = None
    bit_depth = color_type = interlace = None
    idat = b""
    pos = 8
    while pos < len(data):
        length, ctype = struct.unpack(">I4s", data[pos : pos + 8])
        chunk = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if ctype == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", chunk
            )
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break

    if (bit_depth, color_type, interlace) != (8, 6, 0):
        raise ValueError(
            f"{png_path.name}: expected 8-bit non-interlaced RGBA "
            f"(depth={bit_depth} color={color_type} interlace={interlace})"
        )

    raw = zlib.decompress(idat)
    stride = width * 4
    prev = bytearray(stride)
    left, top, right, bottom = width, height, -1, -1

    for y in range(height):
        offset = y * (stride + 1)
        filt = raw[offset]
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        if filt == 1:  # Sub
            for i in range(4, stride):
                line[i] = (line[i] + line[i - 4]) & 0xFF
        elif filt == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filt == 3:  # Average
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif filt == 4:  # Paeth
            for i in range(stride):
                a = line[i - 4] if i >= 4 else 0
                b = prev[i]
                c = prev[i - 4] if i >= 4 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        prev = line

        for x in range(width):
            if line[x * 4 + 3] > 0:
                if x < left:
                    left = x
                if x > right:
                    right = x
                if y < top:
                    top = y
                bottom = y

    if right < 0:
        return width, height, None
    return width, height, (left, top, right + 1, bottom + 1)


def main():
    iconset = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ICONSET
    pngs = sorted(iconset.glob("icon_*.png"))
    if not pngs:
        print(f"ERROR: no icon_*.png found in {iconset}", file=sys.stderr)
        return 1

    failed = False
    for png in pngs:
        width, height, bbox = alpha_bbox(png)
        if bbox is None:
            print(f"ERROR: {png.name} is fully transparent", file=sys.stderr)
            failed = True
            continue
        ratio = max((bbox[2] - bbox[0]) / width, (bbox[3] - bbox[1]) / height)
        if ratio > MAX_CONTENT_RATIO:
            print(
                f"ERROR: {png.name} artwork spans {ratio:.0%} of the canvas "
                f"(max {MAX_CONTENT_RATIO:.0%}). The icon needs a transparent "
                f"safe-area margin (squircle at ~80.5% of canvas, e.g. 824px "
                f"on 1024px) or it renders oversized in the Dock.",
                file=sys.stderr,
            )
            failed = True
        else:
            print(f"ok: {png.name} content at {ratio:.0%} of canvas")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
