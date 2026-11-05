"""hermes-ears measurement engine.

Every number this module returns is computed from the decoded audio with the
method recorded beside it. Nothing here interprets: interpretation happens in
``modes``, where each statement must name the measurement that supports it.

Design rules:
  * measure first, claim second — a claim without a measurement reference is a
    bug, and ``schema.check`` enforces it;
  * name what was actually computed — an unweighted RMS is called RMS, not
    LUFS; a mono-derived decay is called an estimate, not reverb time;
  * state the blind spot — anything the analysis cannot establish gets said out
    loud rather than quietly omitted.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import dataclass

import numpy as np

ENGINE_VERSION = "0.1.0"

# Octave-band centres; the band edges are sqrt(2) either side, which is the
# usual spacing for a one-octave analysis.
OCTAVE_CENTRES = [31.5, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]


@dataclass
class Audio:
    """Decoded audio plus the facts about how it was decoded."""

    mono: np.ndarray
    stereo: np.ndarray | None
    sample_rate: int
    source_rate: int
    source_channels: int
    duration: float
    container: str

    def as_dict(self) -> dict:
        return {
            "sample_rate": self.sample_rate,
            "source_sample_rate": self.source_rate,
            "source_channels": self.source_channels,
            "duration_s": round(self.duration, 3),
            "container": self.container,
        }


def _ffprobe(path: str) -> dict:
    probe = shutil.which("ffprobe")
    if not probe:
        return {}
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=60, check=True)
        return json.loads(out.stdout)
    except (subprocess.SubprocessError, ValueError):
        return {}


def decode(path: str, target_sr: int = 48000) -> Audio:
    """Decode to float32 via ffmpeg. Stereo when the source has it.

    ffmpeg is a hard dependency and is disclosed in the manifest; it is called
    with a fixed argv and a path, never with a shell.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to decode audio and was not found on PATH")

    meta = _ffprobe(path)
    stream = next((s for s in meta.get("streams", []) if s.get("codec_type") == "audio"), {})
    source_rate = int(stream.get("sample_rate") or 0)
    source_channels = int(stream.get("channels") or 0)

    # Decode at the source's own channel count. Forcing -ac 2 on a mono file
    # makes ffmpeg upmix at -3 dB per channel, so every level figure for a mono
    # source would read 3 dB low and a full-scale mono file would look unclipped.
    channels = source_channels if source_channels in (1, 2) else 2
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", path, "-vn",
         "-ac", str(channels), "-ar", str(target_sr), "-f", "f32le", "-"],
        capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to decode {path!r}: "
                           f"{proc.stderr.decode('utf-8', 'replace')[-400:]}")
    interleaved = np.frombuffer(proc.stdout, dtype="<f4")
    if interleaved.size < 1:
        raise RuntimeError("decoded audio is empty")
    frames = interleaved.reshape(-1, channels)
    if channels == 2:
        stereo = frames.astype(np.float64)
        mono = stereo.mean(axis=1)
    else:
        stereo = None
        mono = frames[:, 0].astype(np.float64)
    return Audio(
        mono=mono,
        stereo=stereo,
        sample_rate=target_sr,
        source_rate=source_rate,
        source_channels=source_channels,
        duration=len(mono) / target_sr,
        container=(meta.get("format", {}) or {}).get("format_name", ""),
    )


def _db(x: float) -> float:
    return 20.0 * math.log10(max(x, 1e-12))


def _m(value, unit: str, method: str) -> dict:
    """One measurement, with the method that produced it."""
    if isinstance(value, (np.floating, np.integer)):
        value = value.item()
    if isinstance(value, float):
        value = round(value, 3)
    return {"value": value, "unit": unit, "method": method}


# --------------------------------------------------------------------------
# levels
# --------------------------------------------------------------------------

def measure_levels(audio: Audio) -> dict:
    x = audio.mono
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x * x)))
    dc = float(np.mean(x))
    # consecutive runs within 1e-3 of full scale
    hot = np.abs(x) >= 0.999
    clip_runs = 0
    run = 0
    for flag in hot:
        if flag:
            run += 1
        else:
            if run:
                clip_runs += 1
            run = 0
    if run:
        clip_runs += 1
    return {
        "peak_dbfs": _m(_db(peak), "dBFS", "sample peak of the mono downmix"),
        "rms_dbfs": _m(_db(rms), "dBFS",
                       "unweighted RMS over the whole file (not LUFS: no K-weighting applied)"),
        "crest_factor_db": _m(_db(peak) - _db(rms), "dB", "sample peak minus unweighted RMS"),
        "dc_offset": _m(dc, "linear", "mean sample value of the mono downmix"),
        "clipped_runs": _m(clip_runs, "count", "runs of samples at or above -0.009 dBFS"),
        "has_signal": _m(peak > 1e-4, "bool", "peak above -80 dBFS"),
    }


# --------------------------------------------------------------------------
# spectrum
# --------------------------------------------------------------------------

def _frames(x: np.ndarray, size: int, hop: int):
    if len(x) < size:
        padded = np.zeros(size)
        padded[: len(x)] = x
        yield padded
        return
    for start in range(0, len(x) - size + 1, hop):
        yield x[start:start + size]


def measure_spectrum(audio: Audio, size: int = 4096) -> dict:
    x = audio.mono
    if not np.any(x):
        return {"centroid_hz": _m(0.0, "Hz", "spectral centroid (silent input)"),
                "rolloff85_hz": _m(0.0, "Hz", "85% rolloff (silent input)"),
                "flatness": _m(0.0, "ratio", "spectral flatness (silent input)"),
                "bands": {}}

    window = np.hanning(size)
    freqs = np.fft.rfftfreq(size, 1.0 / audio.sample_rate)
    power_sum = np.zeros_like(freqs)
    flatness_vals = []
    frames = list(_frames(x, size, size // 2))
    for frame in frames:
        spec = np.abs(np.fft.rfft(frame * window))
        power = spec ** 2
        power_sum += power
        band = power[1:]
        if band.size and band.sum() > 0:
            geo = math.exp(float(np.mean(np.log(np.maximum(band, 1e-20)))))
            flatness_vals.append(geo / float(np.mean(band)))

    total = float(power_sum.sum())
    centroid = float((freqs * power_sum).sum() / total) if total > 0 else 0.0
    cumulative = np.cumsum(power_sum)
    rolloff = float(freqs[int(np.searchsorted(cumulative, 0.85 * cumulative[-1]))]) if total > 0 else 0.0

    bands = {}
    for centre in OCTAVE_CENTRES:
        lo, hi = centre / math.sqrt(2), centre * math.sqrt(2)
        mask = (freqs >= lo) & (freqs < hi)
        if not np.any(mask):
            continue
        band_power = float(power_sum[mask].sum())
        share = band_power / total if total > 0 else 0.0
        bands[f"{centre:g}"] = _m(round(100 * share, 2), "% of total power",
                                  f"power in {lo:.0f}-{hi:.0f} Hz")

    return {
        "centroid_hz": _m(centroid, "Hz",
                          f"power-weighted centroid over {len(frames)} frames, {size}-sample Hann"),
        "rolloff85_hz": _m(rolloff, "Hz", "frequency below which 85% of power lies"),
        "flatness": _m(float(np.mean(flatness_vals)) if flatness_vals else 0.0, "ratio",
                       "mean spectral flatness (1.0 = noise-like, 0 = tonal)"),
        "bands": bands,
        "frames_analysed": _m(len(frames), "count", "analysis frames"),
    }


# --------------------------------------------------------------------------
# timing
# --------------------------------------------------------------------------

def measure_timing(audio: Audio, frame_ms: float = 20.0,
                   silence_floor_db: float = -50.0,
                   min_silence_ms: float = 200.0) -> dict:
    x = audio.mono
    sr = audio.sample_rate
    hop = max(1, int(sr * frame_ms / 1000))
    n = len(x) // hop
    if n == 0:
        return {"onsets": _m(0, "count", "no frames"), "silences": _m([], "list", "none")}
    energy = np.array([float(np.sqrt(np.mean(x[i * hop:(i + 1) * hop] ** 2)))
                       for i in range(n)])
    db = 20 * np.log10(np.maximum(energy, 1e-12))

    # silence windows
    silent = db < silence_floor_db
    windows = []
    start = None
    for i, flag in enumerate(silent):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if (i - start) * frame_ms >= min_silence_ms:
                windows.append([round(start * frame_ms / 1000, 2), round(i * frame_ms / 1000, 2)])
            start = None
    if start is not None and (n - start) * frame_ms >= min_silence_ms:
        windows.append([round(start * frame_ms / 1000, 2), round(n * frame_ms / 1000, 2)])

    # onsets from a rising energy difference against a local mean
    flux = np.diff(db, prepend=db[0])
    positive = np.maximum(flux, 0.0)
    if positive.max() > 0:
        thresh = float(positive.mean() + 1.5 * positive.std())
        onsets = 0
        last = -10.0
        for i, v in enumerate(positive):
            t = i * frame_ms / 1000
            if v > thresh and t - last > 0.05:
                onsets += 1
                last = t
    else:
        onsets = 0

    return {
        "onsets": _m(onsets, "count",
                     f"rises in {frame_ms:g} ms frame energy above mean+1.5 sd, 50 ms refractory"),
        "onset_rate_per_s": _m(onsets / audio.duration if audio.duration else 0.0, "per second",
                               "onsets divided by duration"),
        "silence_windows": _m(windows, "seconds",
                              f"runs below {silence_floor_db:g} dBFS lasting {min_silence_ms:g} ms or more"),
        "silent_fraction": _m(float(silent.mean()), "fraction",
                              "share of frames below the silence floor"),
    }


# --------------------------------------------------------------------------
# space (deliberately humble)
# --------------------------------------------------------------------------

def measure_space(audio: Audio) -> dict:
    """Decay estimate and stereo facts.

    This is not reverb time. RT60 needs a known excitation and a measured decay
    below the noise floor; what is computed here is the energy decay slope after
    the loudest onset, extrapolated, and it is labelled as an estimate.
    """
    x = audio.mono
    sr = audio.sample_rate
    frame = max(1, int(sr * 0.01))
    n = len(x) // frame
    if n < 20:
        return {"decay_estimate": _m(None, "s", "too short to estimate")}
    energy = np.array([float(np.mean(x[i * frame:(i + 1) * frame] ** 2)) for i in range(n)])
    peak_i = int(np.argmax(energy))
    tail = energy[peak_i:peak_i + min(200, len(energy) - peak_i)]
    if tail.size < 5:
        return {"decay_estimate": _m(None, "s", "no usable tail after the loudest frame")}
    db = 10 * np.log10(np.maximum(tail, 1e-12))
    # slope over the first 40 dB of decay, in dB per 10 ms frame
    floor = db[0] - 40
    idx = np.where(db <= floor)[0]
    end = int(idx[0]) if idx.size else len(db) - 1
    if end < 3:
        return {"decay_estimate": _m(None, "s", "decay shorter than the frame size")}
    t = np.arange(end + 1) * 0.01
    slope = float(np.polyfit(t, db[: end + 1], 1)[0])
    estimate = (-60.0 / slope) if slope < -0.5 else None

    out = {
        "decay_estimate": _m(estimate, "s",
                             "energy decay after the loudest onset, fitted over the first 40 dB "
                             "and extrapolated to 60 dB; not a measured RT60"),
    }
    if audio.stereo is not None and audio.stereo.shape[1] == 2:
        left, right = audio.stereo[:, 0], audio.stereo[:, 1]
        denom = math.sqrt(float(np.sum(left ** 2)) * float(np.sum(right ** 2)))
        corr = float(np.sum(left * right) / denom) if denom > 0 else 0.0
        out["stereo_correlation"] = _m(corr, "-1..1",
                                       "Pearson correlation of the two channels over the file")
        balance = _db(float(np.sqrt(np.mean(left ** 2))) / max(float(np.sqrt(np.mean(right ** 2))), 1e-12))
        out["lr_balance_db"] = _m(balance, "dB", "L RMS minus R RMS")
        out["mono_summed_source"] = _m(audio.source_channels == 1, "bool",
                                       "source channel count reported by ffprobe")
    return out


def analyse(path: str, modes: list[str] | None = None) -> dict:
    """Measure everything requested. Returns measurements only — no prose."""
    audio = decode(path)
    want = set(modes or ["levels", "spectrum", "timing", "space"])
    out: dict = {"audio": audio.as_dict()}
    if "levels" in want:
        out["levels"] = measure_levels(audio)
    if "spectrum" in want:
        out["spectrum"] = measure_spectrum(audio)
    if "timing" in want:
        out["timing"] = measure_timing(audio)
    if "space" in want:
        out["space"] = measure_space(audio)
    return out
