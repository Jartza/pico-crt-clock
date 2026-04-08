# make_torus.py
#
# Pre-computes the torus LUT data and writes torus.bin.
# Run on PC whenever any parameter changes, then mpremote the bin to the Pico.
# On RP2040, loading from bin is much faster than recomputing (no float trig at boot).
# All parameters live here; clock_alt.py reads them from the bin at runtime.

import struct
from math import sin, cos

_TORUS_N    = 7     # tube segments
_TORUS_M    = 10    # ring segments
_TORUS_R    = 46    # major radius
_TORUS_r    = 20    # minor radius
_WB_AMP     = 1.3   # wobble amplitude (radians)
_PERSP_DIST = 120    # perspective view distance

def make_torus_bin(filename="torus.bin"):
    N, M = _TORUS_N, _TORUS_M
    R, r = _TORUS_R, _TORUS_r
    NM = N * M
    zoff = R + r            # z index offset for persp LUT
    zmax = 2 * (R + r)      # max z index (LUT size - 1)

    # Base vertices, fixed-point ×256 (int32)
    bx = [0] * NM;  by = [0] * NM;  bz = [0] * NM
    k = 0
    for j in range(M):
        phi = j * 6.2832 / M
        cp, sp = cos(phi), sin(phi)
        for i in range(N):
            theta = i * 6.2832 / N
            ct = cos(theta)
            bx[k] = int((R + r * ct) * cp * 256)
            by[k] = int((R + r * ct) * sp * 256)
            bz[k] = int(r * sin(theta) * 256)
            k += 1

    # Perspective LUT: int(PERSP_DIST×256 / (PERSP_DIST-zoff+i)) for i in 0..zmax (uint16)
    persp_lut = [int(_PERSP_DIST * 256 / (_PERSP_DIST - zoff + i)) for i in range(zmax + 1)]

    # Sine table: int(sin(i×2π/256)×256) for i in 0..255 (int16)
    sin_lut = [int(sin(i * 6.2832 / 256) * 256) for i in range(256)]

    # Wobble LUTs: cos/sin of sin(phase)×WB_AMP (int16)
    icx_lut = [int(cos(sin(i * 6.2832 / 256) * _WB_AMP) * 256) for i in range(256)]
    isx_lut = [int(sin(sin(i * 6.2832 / 256) * _WB_AMP) * 256) for i in range(256)]

    # Edge list: flat (a, b, c) int16 triples
    edges = []
    for j in range(M):
        nj = (j + 1) % M
        for i in range(N):
            ni = (i + 1) % N
            edges += [j*N+i, j*N+ni, nj*N+i]

    persp_size = zmax + 1
    with open(filename, "wb") as f:
        # Header: N, M, R, r (uint8), WB_AMP ×1000 (uint16), PERSP_DIST (uint16)
        f.write(struct.pack("4B2H", N, M, R, r, round(_WB_AMP * 1000), _PERSP_DIST))
        f.write(struct.pack(f"{NM}i", *bx))
        f.write(struct.pack(f"{NM}i", *by))
        f.write(struct.pack(f"{NM}i", *bz))
        f.write(struct.pack(f"{persp_size}H", *persp_lut))
        f.write(struct.pack(f"256h", *sin_lut))
        f.write(struct.pack(f"256h", *icx_lut))
        f.write(struct.pack(f"256h", *isx_lut))
        f.write(struct.pack(f"{NM*3}h", *edges))

    total = 8 + NM*4*3 + persp_size*2 + 256*2*3 + NM*3*2
    print(f"Wrote {filename} ({total} bytes)")

if __name__ == "__main__":
    make_torus_bin("torus.bin")
