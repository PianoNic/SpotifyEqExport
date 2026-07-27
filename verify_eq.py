#!/usr/bin/env python3
"""Read Spotify's live biquad coefficients and recover gain, Q and S.

Spotify keeps six biquads as a contiguous array of 48-byte blocks
(doubles, unnormalised, layout [a0,a1,a2,b0,b1,b2]) while audio is playing.
Anchor is a1 == -2*cos(w0), which depends only on frequency and samplerate.

Windows only. Requires playback to be running with the equalizer enabled.
"""
import argparse
import ctypes as C
import ctypes.wintypes as W
import math
import struct
import subprocess
import sys

k32 = C.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = W.HANDLE
k32.VirtualQueryEx.restype = C.c_size_t

MEM_COMMIT, MEM_PRIVATE, PAGE_GUARD = 0x1000, 0x20000, 0x100
READABLE = (0x02, 0x04, 0x20, 0x40)

BANDS = [("lowshelf", 60), ("peaking", 150), ("peaking", 400),
         ("peaking", 1000), ("peaking", 2400), ("highshelf", 15000)]
ANCHOR_IDX = 2


class MBI(C.Structure):
    _fields_ = [("BaseAddress", C.c_void_p), ("AllocationBase", C.c_void_p),
                ("AllocationProtect", W.DWORD), ("__a", W.DWORD),
                ("RegionSize", C.c_size_t), ("State", W.DWORD),
                ("Protect", W.DWORD), ("Type", W.DWORD), ("__b", W.DWORD)]


def regions(h):
    addr, mbi = 0, MBI()
    while addr < 0x7FFFFFFFFFFF:
        if not k32.VirtualQueryEx(h, C.c_void_p(addr), C.byref(mbi), C.sizeof(mbi)):
            break
        size = mbi.RegionSize
        if (mbi.State == MEM_COMMIT and mbi.Type == MEM_PRIVATE
                and mbi.Protect & 0xFF in READABLE
                and not mbi.Protect & PAGE_GUARD
                and size < 256 * 1024 * 1024):
            yield mbi.BaseAddress or addr, size
        addr += size or 0x1000


def read(h, addr, size):
    buf = C.create_string_buffer(size)
    got = C.c_size_t()
    if k32.ReadProcessMemory(h, C.c_void_p(addr), buf, size, C.byref(got)):
        return buf.raw[:got.value]
    return b""


def peaking(c, f0, fs):
    a0, a1, a2, b0, b1, b2 = c
    w0 = 2 * math.pi * f0 / fs
    aa, ba = (a0 - a2) / 2, (b0 - b2) / 2
    if aa <= 0 or ba <= 0:
        return None
    A, alpha = math.sqrt(ba / aa), math.sqrt(ba * aa)
    return 40 * math.log10(A), math.sin(w0) / (2 * alpha)


def shelf(c, kind, f0, fs):
    a0, a1, a2, b0, b1, b2 = c
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    s = a0 + a2
    A = ((s - 2 * (1 - cw)) / (2 * (1 + cw)) if kind == "lowshelf"
         else (s - 2 * (1 + cw)) / (2 * (1 - cw)))
    if A <= 0:
        return None
    alpha = ((a0 - a2) / 2) / (2 * math.sqrt(A))
    rad = (2 * alpha / sw) ** 2
    denom = (rad - 2) / (A + 1 / A) + 1
    if denom <= 0:
        return None
    return 40 * math.log10(A), 1 / denom


def spotify_pids():
    out = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process Spotify -ErrorAction SilentlyContinue).Id"], text=True)
    return [int(p) for p in out.split()]


def scan(fs, verbose=False):
    pat = struct.pack("<d", -2 * math.cos(2 * math.pi * BANDS[ANCHOR_IDX][1] / fs))
    for pid in spotify_pids():
        h = k32.OpenProcess(0x0010 | 0x0400, False, pid)
        if not h:
            continue
        try:
            for base, size in regions(h):
                data = read(h, base, size)
                i = data.find(pat) if data else -1
                while i != -1:
                    start = i - 8 - ANCHOR_IDX * 48
                    if start >= 0 and start + 288 <= len(data):
                        blk = [list(struct.unpack_from("<6d", data, start + k * 48))
                               for k in range(6)]
                        if report(blk, fs, pid, base + start, verbose):
                            return True
                    i = data.find(pat, i + 1)
        finally:
            k32.CloseHandle(h)
    return False


def report(blk, fs, pid, addr, verbose):
    rows = []
    for (kind, f0), c in zip(BANDS, blk):
        if not all(math.isfinite(x) for x in c):
            return False
        r = peaking(c, f0, fs) if kind == "peaking" else shelf(c, kind, f0, fs)
        if r is None or not (-25 < r[0] < 25) or not (0.05 < r[1] < 20):
            return False
        rows.append((kind, f0, r[0], r[1]))

    print(f"PID {pid}  block @ 0x{addr:x}  fs={fs}\n")
    for kind, f0, gain, q in rows:
        label = "Q" if kind == "peaking" else "S"
        print(f"  {kind:<10}{f0:>6} Hz   gain={gain:+8.4f} dB   {label}={q:.6f}")
    if verbose:
        print("\n  raw [a0,a1,a2,b0,b1,b2]:")
        for (kind, f0), c in zip(BANDS, blk):
            print(f"   {f0:>6} Hz  " + "  ".join(f"{x:+.12g}" for x in c))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-r", "--samplerate", type=int, action="append",
                    help="try this rate (repeatable, default 44100/48000/96000)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="also print raw coefficients")
    a = ap.parse_args()

    if sys.platform != "win32":
        sys.exit("Windows only")

    for fs in a.samplerate or (44100, 48000, 96000, 88200):
        if scan(fs, a.verbose):
            return
    sys.exit("No filter block found. Is playback running with the EQ enabled?")


if __name__ == "__main__":
    main()
