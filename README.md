# hermes-ears

A listening engine for Hermes Agent. Point it at an audio file and it measures; then it states
only what those measurements carry. Every claim names its evidence, and every record ends with
what the instrument cannot establish.

```
👂 /listen ~/audio/cue.wav
```

```
**hermes-ears — ~/audio/cue.wav**
*37.586 s · 48000 Hz source · 2 ch · sha256 1180373a4fb8…*  
*(a real 37.6 s stereo cue sketch; the filename is elided)*

**Measured**
- Peak is -8.834 dBFS and unweighted RMS is -21.885 dBFS over 37.586 s.
- Spectral centroid is 225.319 Hz and 85% of the power lies below 328.125 Hz.
- The largest octave-band shares are 125 Hz (60.85%), 250 Hz (28.44%).
- 119 onsets (3.166 per second); 6.8% of frames sit below the silence floor.
- Channel correlation is 0.84 and L/R balance is 0.092 dB.

**Inferred** *(not measurements)*
- The signal is tonal or harmonic rather than noise-like. — *moderate confidence; from spectrum.flatness*
- Energy sits low: this reads as bass-heavy or dull. — *moderate confidence; from spectrum.centroid_hz*
- Events arrive at a fast rate: this reads as rhythmic or percussive. — *moderate confidence; from timing.onset_rate_per_s*

**Blind spots**
- No speech recognition: this engine does not know what words, if any, are spoken. …
- No source separation: in a mix, nothing here can attribute a measurement to an individual instrument or voice.
- …
```

## Why it is built this way

Most audio tooling answers in prose, and most agent tooling answers in guesses. This separates the
two: **measurements** carry the method that produced them, **observations** restate measurements,
**claims** are tagged `inferred` and name the numbers they rest on. A claim with no basis is not
emitted — the test suite fails if one appears.

It also refuses to round its own numbers into confidence. An unweighted RMS is called RMS, not
LUFS. A decay extrapolated after the loudest onset is called an estimate, not RT60.

## Install

```bash
hermes plugins install <this repo> --enable
```

Requires `ffmpeg` and `ffprobe` on `PATH` (`brew install ffmpeg`), plus `numpy`.

## Use

| Pass | Figures |
|---|---|
| `levels` | peak dBFS, unweighted RMS dBFS, crest factor, DC offset, clipping runs, signal presence |
| `spectrum` | centroid, 85% rolloff, flatness, ten octave-band power shares |
| `timing` | onset count and rate, silence windows, silent fraction |
| `space` | decay estimate, stereo correlation, L/R balance |

All four run by default. `ears_listen` takes `path`, optional `modes`, and `format`
(`markdown`/`json`); the `/listen` command is the same thing from chat.

## Tests

```bash
python3 tests/test_engine.py
```

Known-input calibration rather than coverage: a −20 dBFS 1 kHz tone must measure −20 dBFS and
1000 Hz; five clicks a second apart must count as about five onsets; a full-scale square must be
flagged as clipped. These caught a real bug on first run — ffmpeg's mono→stereo upmix applies
−3 dB per channel, so forcing `-ac 2` on a mono file made every level read 3 dB low and a
full-scale mono file look unclipped.

## Licence

MIT. AKOÚŌ (emeisazam / Sonic Field Labs) is credited as the method lineage in `NOTICE`; none of
its material is redistributed. See `SCOPE.md` for the design and the passes still to come.
