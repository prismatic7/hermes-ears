"""Known-input tests for the measurement engine.

The point is not coverage, it is calibration: a signal with a known level, a
known frequency and a known event rate must produce those numbers back. If a
figure drifts, one of these fails.

Run: python3 tests/test_engine.py
"""

from __future__ import annotations

import math
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ears import engine, modes  # noqa: E402

SR = 48000


def write_wav(path: Path, mono: np.ndarray, sr: int = SR) -> None:
    pcm = np.clip(mono, -1.0, 1.0)
    data = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def tone(freq: float, amp: float, seconds: float, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return amp * np.sin(2 * math.pi * freq * t)


def test_tone_level_and_centroid(tmp: Path) -> None:
    path = tmp / "tone.wav"
    write_wav(path, tone(1000, 0.1, 3.0))
    rec = modes.listen(str(path))
    peak = rec["measurements"]["levels"]["peak_dbfs"]["value"]
    centroid = rec["measurements"]["spectrum"]["centroid_hz"]["value"]
    flat = rec["measurements"]["spectrum"]["flatness"]["value"]

    assert abs(peak - (-20.0)) < 0.6, f"peak {peak} dBFS, expected about -20"
    assert 900 < centroid < 1100, f"centroid {centroid} Hz, expected about 1000"
    assert flat < 0.2, f"flatness {flat}, a pure tone should be tonal"
    assert rec["measurements"]["levels"]["has_signal"]["value"] is True
    # measured-first ordering: observations exist, and every claim has a basis
    assert rec["observations"], "no observations produced"
    for claim in rec["claims"]:
        assert claim["basis"], "a claim without a basis is a bug"


def test_silence(tmp: Path) -> None:
    path = tmp / "silence.wav"
    write_wav(path, np.zeros(SR * 2))
    rec = modes.listen(str(path))
    assert rec["measurements"]["levels"]["has_signal"]["value"] is False
    silent = rec["measurements"]["timing"]["silent_fraction"]["value"]
    assert silent > 0.95, f"silent fraction {silent}"


def test_event_rate(tmp: Path) -> None:
    """Five clicks one second apart: onset counting must see roughly five."""
    path = tmp / "clicks.wav"
    x = np.zeros(int(SR * 5.5))
    for i in range(5):
        start = int(SR * (0.5 + i))
        n = int(SR * 0.05)
        x[start:start + n] += np.random.default_rng(i).normal(0, 0.3, n)
    write_wav(path, x)
    rec = modes.listen(str(path))
    onsets = rec["measurements"]["timing"]["onsets"]["value"]
    sparse = rec["measurements"]["timing"]["silent_fraction"]["value"]
    assert 3 <= onsets <= 7, f"onsets {onsets}, expected about 5"
    assert sparse > 0.8, f"silent fraction {sparse}, expected mostly silence"


def test_clipping_is_flagged(tmp: Path) -> None:
    path = tmp / "clip.wav"
    x = np.sign(tone(200, 1.6, 1.0))  # hard square at well over full scale
    write_wav(path, x)
    rec = modes.listen(str(path))
    runs = rec["measurements"]["levels"]["clipped_runs"]["value"]
    assert runs > 0, "clipping not detected"
    assert any("clipping" in c["statement"].lower() for c in rec["claims"]), \
        "clipping measured but not claimed"


def test_blind_spots_always_present(tmp: Path) -> None:
    path = tmp / "tone2.wav"
    write_wav(path, tone(440, 0.2, 1.0))
    rec = modes.listen(str(path))
    text = " ".join(rec["blind_spots"]).lower()
    for expected in ("speech", "source separation", "source identity"):
        assert expected in text, f"blind spot about {expected!r} missing"


def test_engine_requires_ffmpeg(tmp: Path) -> None:
    """A missing ffmpeg must raise with an actionable message, not fail obscurely."""
    path = tmp / "tone3.wav"
    write_wav(path, tone(440, 0.2, 0.5))
    original = engine.shutil.which
    engine.shutil.which = lambda name: None if name == "ffmpeg" else original(name)
    try:
        try:
            engine.decode(str(path))
        except RuntimeError as exc:
            assert "ffmpeg" in str(exc)
        else:
            raise AssertionError("decode() should raise when ffmpeg is absent")
    finally:
        engine.shutil.which = original


def main() -> int:
    tests = [test_tone_level_and_centroid, test_silence, test_event_rate,
             test_clipping_is_flagged, test_blind_spots_always_present,
             test_engine_requires_ffmpeg]
    failures = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for test in tests:
            try:
                test(tmp)
                print(f"PASS  {test.__name__}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL  {test.__name__}: {exc}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"ERROR {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
