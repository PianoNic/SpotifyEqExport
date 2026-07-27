# <p align="center">spotify-eq-export</p>
<p align="center">
  <img src="https://raw.githubusercontent.com/PianoNic/spotify-eq-export/main/assets/logo.svg" width="160" alt="spotify-eq-export Logo">
</p>
<p align="center">
  <strong>Export the Spotify desktop equalizer to Wavelet, EqualizerAPO or any GraphicEQ target.</strong><br>
  Reads the six band gains straight out of Spotify's <code>prefs</code> file and rebuilds the actual filter curve.
</p>
<p align="center">
  <a href="https://github.com/PianoNic/spotify-eq-export"><img src="https://badgetrack.pianonic.ch/badge?tag=spotify-eq-export&label=visits&color=1DB954&style=flat" alt="visits"/></a>
  <img src="https://img.shields.io/badge/Python-3.8%2B-1DB954.svg?labelColor=0B0F14&color=1DB954" alt="Python 3.8+"/>
  <img src="https://img.shields.io/badge/dependencies-none-1DB954.svg?labelColor=0B0F14&color=1DB954" alt="no dependencies"/>
  <a href="https://github.com/PianoNic/spotify-eq-export/blob/main/LICENSE"><img src="https://img.shields.io/github/license/PianoNic/spotify-eq-export?labelColor=0B0F14&color=1DB954" alt="license"/></a>
</p>

---

> [!NOTE]
> Filter parameters were determined against Spotify 1.2.94. If a future version changes them, `verify_eq.py` will tell you.

## About The Project

Spotify's desktop equalizer has no export, and its settings UI occasionally stops rendering while the filters stay active — you can hear your profile but not see it. The values are still on disk, stored as fixed-point integers under undocumented keys.

This reads those keys, reconstructs the filter chain the same way Spotify builds it, and writes the 127-point `GraphicEQ` curve that [Wavelet](https://pittvandewitt.github.io/Wavelet/) imports. It also ships all 21 built-in Spotify presets, so you can export those without having Spotify installed at all.

Everything here is stdlib only. No pip install, no numpy.

## Filter parameters

Spotify uses a six-band chain of [RBJ Audio EQ Cookbook](https://webaudio.github.io/Audio-EQ-Cookbook/audio-eq-cookbook.html) biquads:

| Band | Type | Q / S | prefs key |
|---|---|---|---|
| 60 Hz | low shelf | S = 1.0 | `audio.equalizer.low_shelf_gain_v2` |
| 150 Hz | peaking | Q = 1.0 | `audio.equalizer.low_peak_gain_v2` |
| 400 Hz | peaking | Q = 1.0 | `audio.equalizer.low_mid_peak_gain_v2` |
| 1 kHz | peaking | Q = 1.0 | `audio.equalizer.high_mid_peak_gain_v2` |
| 2.4 kHz | peaking | Q = 1.0 | `audio.equalizer.high_peak_gain_v2` |
| 15 kHz | high shelf | S = 1.0 | `audio.equalizer.high_shelf_gain_v2` |

Gains are stored as `int32` scaled by `12 / INT32_MAX`, so `2147483647` is `+12 dB`.

Types, frequencies and the ±12 dB range come from `Apps/xpui/xpui-modules.js` (module `51332`). The scaling constant sits in `Spotify.dll` as a double at RVA `0x1a28048`, loaded by the prefs reader at `.text` RVA `0x1085340`. Q and S were recovered from the live filter coefficients — see below.

## Features

- **Reads your actual settings** — finds the `prefs` file automatically, no manual copying of slider values.
- **Real biquads** — evaluates the RBJ transfer function instead of interpolating between six points, which is all Spotify's own UI draws.
- **All 21 presets built in** — `--preset rock`, `--preset rnb`, and so on, extracted from the client bundle.
- **Clipping control** — `--scale` to tame the curve, `--rolloff` to fade the low shelf out below 60 Hz.
- **Verification tool** — `verify_eq.py` reads the coefficients Spotify is using right now and reports gain, Q and S.
- **Zero dependencies** — Python 3.8+ and nothing else.

## Installation

```sh
git clone https://github.com/PianoNic/spotify-eq-export
cd spotify-eq-export
```

## Usage

Export whatever is currently configured in Spotify:

```sh
python spotify_eq_export.py
```

```
      60 Hz  lowshelf   +12.00 dB
     150 Hz  peaking     +0.30 dB
     400 Hz  peaking     -6.70 dB
    1000 Hz  peaking     -6.70 dB
    2400 Hz  peaking     +0.70 dB
   15000 Hz  highshelf  +12.00 dB
-> Spotify EQ.txt
```

Import the resulting file in Wavelet under **AutoEq → Import**. The file name becomes the profile name.

Other options:

```sh
python spotify_eq_export.py --preset rock -o Rock.txt   # a built-in preset
python spotify_eq_export.py --scale 0.5                 # halve the curve
python spotify_eq_export.py --rolloff                   # fade sub-bass out
python spotify_eq_export.py --prefs /path/to/prefs      # explicit prefs file
python spotify_eq_export.py --selftest
```

### A note on clipping

Wavelet normalises on import to keep perceived loudness constant — it does not pull the peak down to 0 dB. Applied system-wide to already-limited material, a large low-shelf boost will clip, and a shelf is flat below its corner frequency, so a `+12 dB` shelf at 60 Hz also means `+12 dB` at 20 Hz where there is nothing to hear and plenty of excursion to lose. `--scale 0.5` and `--rolloff` exist for that.

## Verifying the parameters

While audio is playing, Spotify holds the six biquads in memory as a contiguous array of 48-byte blocks — doubles, unnormalised, laid out `[a0,a1,a2,b0,b1,b2]`. Since `a1 = -2·cos(ω₀)` depends only on frequency and samplerate, that value is enough to locate the array, and gain, Q and S follow analytically from the rest.

```sh
python verify_eq.py -v
```

```
PID 13876  block @ 0x1f551879610  fs=44100

  lowshelf      60 Hz   gain=+12.0000 dB   S=1.000000
  peaking      150 Hz   gain= +0.3000 dB   Q=1.000000
  peaking      400 Hz   gain= -6.7000 dB   Q=1.000000
  peaking     1000 Hz   gain= -6.7000 dB   Q=1.000000
  peaking     2400 Hz   gain= +0.7000 dB   Q=1.000000
  highshelf  15000 Hz   gain=+12.0000 dB   S=1.000000
```

The recovered gains match the `prefs` values, which confirms the block is the right one. Windows only, and playback has to be running — the filter objects are freed when the pipeline stops.

## Output format

Wavelet accepts a fixed 127-point curve from 20 Hz to 19871 Hz. Adding, removing or changing frequencies makes the file invalid:

```
GraphicEQ: 20 5.9; 21 5.9; 22 5.9; ... ; 19871 6.0
```

The same format is read by EqualizerAPO's `GraphicEQ` filter and by [AutoEq](https://github.com/jaakkopasanen/AutoEq) tooling.

## License

Distributed under the MIT License. See `LICENSE` for more information.

---

Not affiliated with or endorsed by Spotify AB.
