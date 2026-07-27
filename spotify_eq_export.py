#!/usr/bin/env python3
"""Export the Spotify desktop equalizer to Wavelet's GraphicEQ format.

Reads the six band gains from Spotify's prefs file, evaluates the filter
chain as RBJ biquads and writes the 127-point curve Wavelet expects.
"""
import argparse
import math
import os
import re
import sys

MAX_DB = 12.0
INT32_MAX = 2147483647
FS = 44100
Q = 1.0
S = 1.0

BANDS = [
    ("lowshelf", 60, "audio.equalizer.low_shelf_gain_v2"),
    ("peaking", 150, "audio.equalizer.low_peak_gain_v2"),
    ("peaking", 400, "audio.equalizer.low_mid_peak_gain_v2"),
    ("peaking", 1000, "audio.equalizer.high_mid_peak_gain_v2"),
    ("peaking", 2400, "audio.equalizer.high_peak_gain_v2"),
    ("highshelf", 15000, "audio.equalizer.high_shelf_gain_v2"),
]

# Wavelet rejects the file if these frequencies are altered.
FREQ = [20, 21, 22, 23, 24, 26, 27, 29, 30, 32, 34, 36, 38, 40, 43, 45, 48, 50,
        53, 56, 59, 63, 66, 70, 74, 78, 83, 87, 92, 97, 103, 109, 115, 121, 128,
        136, 143, 151, 160, 169, 178, 188, 199, 210, 222, 235, 248, 262, 277,
        292, 309, 326, 345, 364, 385, 406, 429, 453, 479, 506, 534, 565, 596,
        630, 665, 703, 743, 784, 829, 875, 924, 977, 1032, 1090, 1151, 1216,
        1284, 1357, 1433, 1514, 1599, 1689, 1784, 1885, 1991, 2103, 2221, 2347,
        2479, 2618, 2766, 2921, 3086, 3260, 3443, 3637, 3842, 4058, 4287, 4528,
        4783, 5052, 5337, 5637, 5955, 6290, 6644, 7018, 7414, 7831, 8272, 8738,
        9230, 9749, 10298, 10878, 11490, 12137, 12821, 13543, 14305, 15110,
        15961, 16860, 17809, 18812, 19871]

PRESETS = {
    "flat": [0, 0, 0, 0, 0, 0],
    "acoustic": [4.9, 3.95, 2.15, 1.75, 3.5, 2.15],
    "bass_booster": [4.25, 3.5, 1.25, 0, 0, 0],
    "bass_reducer": [-4.25, -3.5, -1.25, 0, 0, 0],
    "classical": [3.75, 3, -1.5, -1.5, 0, 3.75],
    "dance": [6.55, 4.99, 1.92, 3.65, 5.15, 0],
    "electronic": [3.8, 1.2, -2.15, 2.25, 0.85, 4.8],
    "hiphop": [4.25, 1.5, -1, -1, 1.5, 3],
    "jazz": [3, 1.5, -1.5, -1.5, 0, 3.75],
    "latin": [3, 0, -1.5, -1.5, -1.5, 4.5],
    "loudness": [4, 0, -2, 0, -1, 1],
    "lounge": [-1.5, -0.5, 4, 2.5, 0, 1],
    "piano": [2, 0, 3, 1.5, 3.5, 3.5],
    "pop": [-1, 0, 4, 4, 2, -1.5],
    "rnb": [6.92, 5.65, -2.19, -1.5, 2.32, 3.75],
    "rock": [4, 3, -0.5, -1, 0.5, 4.5],
    "small_speakers": [4.25, 3.5, 1.25, 0, -1.25, -4.25],
    "spoken_word": [-0.47, 0, 3.46, 4.61, 4.84, 0],
    "treble_booster": [0, 0, 0, 1.25, 2.5, 5.5],
    "treble_reducer": [0, 0, 0, -1.25, -2.5, -5.5],
    "vocal_booster": [-3, -3, 3.75, 3.75, 3, -1.5],
}


def biquad(kind, f0, db):
    """RBJ Audio EQ Cookbook coefficients."""
    A = 10 ** (db / 40)
    w0 = 2 * math.pi * f0 / FS
    cw, sw = math.cos(w0), math.sin(w0)
    if kind == "peaking":
        al = sw / (2 * Q)
        return (1 + al * A, -2 * cw, 1 - al * A,
                1 + al / A, -2 * cw, 1 - al / A)
    al = sw / 2 * math.sqrt((A + 1 / A) * (1 / S - 1) + 2)
    t = 2 * math.sqrt(A) * al
    if kind == "lowshelf":
        return (A * ((A + 1) - (A - 1) * cw + t),
                2 * A * ((A - 1) - (A + 1) * cw),
                A * ((A + 1) - (A - 1) * cw - t),
                (A + 1) + (A - 1) * cw + t,
                -2 * ((A - 1) + (A + 1) * cw),
                (A + 1) + (A - 1) * cw - t)
    return (A * ((A + 1) + (A - 1) * cw + t),
            -2 * A * ((A - 1) + (A + 1) * cw),
            A * ((A + 1) + (A - 1) * cw - t),
            (A + 1) - (A - 1) * cw + t,
            2 * ((A - 1) - (A + 1) * cw),
            (A + 1) - (A - 1) * cw - t)


def response_db(c, f):
    b0, b1, b2, a0, a1, a2 = c
    a = -2 * math.pi * f / FS
    z = complex(math.cos(a), math.sin(a))
    return 20 * math.log10(abs((b0 + b1 * z + b2 * z * z) /
                               (a0 + a1 * z + a2 * z * z)))


def curve(gains, scale=1.0, subbass_rolloff=False):
    """Summed response of all six bands at Wavelet's 127 frequencies."""
    filters = [biquad(k, f, g * scale) for (k, f, _), g in zip(BANDS, gains)]
    out = [sum(response_db(c, f) for c in filters) for f in FREQ]
    if subbass_rolloff:
        lo, hi = 25.0, BANDS[0][1]
        for i, f in enumerate(FREQ):
            if f < hi:
                t = max(0.0, math.log10(max(f, lo) / lo) / math.log10(hi / lo))
                out[i] *= t
    return out


def default_prefs_path():
    base = os.path.join(os.environ.get("APPDATA", ""), "Spotify", "Users")
    if os.path.isdir(base):
        for d in os.listdir(base):
            p = os.path.join(base, d, "prefs")
            if d.endswith("-user") and os.path.isfile(p):
                return p
    return None


def read_prefs(path=None):
    """Six gains in dB, in BANDS order."""
    path = path or default_prefs_path()
    if not path:
        sys.exit("prefs not found, pass --prefs")
    txt = open(path, encoding="utf-8", errors="replace").read()
    gains = []
    for _, _, key in BANDS:
        m = re.search(re.escape(key) + r"=(-?\d+)", txt)
        gains.append(int(m.group(1)) / INT32_MAX * MAX_DB if m else 0.0)
    return gains


def graphic_eq(gains, scale=1.0, subbass_rolloff=False):
    vals = curve(gains, scale, subbass_rolloff)
    return "GraphicEQ: " + "; ".join(f"{f} {g:.1f}" for f, g in zip(FREQ, vals))


def selftest():
    assert all(abs(g) < 1e-9 for g in curve([0] * 6))
    assert abs(response_db(biquad("peaking", 1000, 6.0), 1000) - 6.0) < 0.01
    assert abs(response_db(biquad("lowshelf", 60, 6.0), 5) - 6.0) < 0.1
    assert abs(INT32_MAX / INT32_MAX * MAX_DB - 12.0) < 1e-9
    assert len(FREQ) == 127
    print("ok")


def main():
    global FS
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default="Spotify EQ.txt")
    ap.add_argument("-p", "--prefs", help="path to Spotify prefs file")
    ap.add_argument("-s", "--scale", type=float, default=1.0,
                    help="scale all gains, e.g. 0.5 to halve the curve")
    ap.add_argument("--preset", choices=sorted(PRESETS),
                    help="use a built-in Spotify preset instead of prefs")
    ap.add_argument("--rolloff", action="store_true",
                    help="fade the low shelf out below 60 Hz")
    ap.add_argument("--samplerate", type=int, default=FS)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    FS = a.samplerate
    gains = PRESETS[a.preset] if a.preset else read_prefs(a.prefs)

    for (kind, f0, _), g in zip(BANDS, gains):
        print(f"  {f0:>6} Hz  {kind:<10} {g * a.scale:+6.2f} dB", file=sys.stderr)

    with open(a.out, "w") as fh:
        fh.write(graphic_eq(gains, a.scale, a.rolloff))
    print(f"-> {a.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
