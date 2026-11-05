"""From measurements to statements, with the evidence level held separate.

An observation restates a measurement. A claim interprets measurements. The two
are never mixed: every observation names the measurement keys it restates, and
every claim names the observations or measurements it rests on. A claim that
cannot point at a measurement is not emitted.

Blind spots are part of the record, not an afterthought. What this engine cannot
establish is listed every time, so a reader can see the edge of the instrument
before trusting anything inside it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from . import engine

RECORD_VERSION = "1"

ALWAYS_BLIND = [
    "No speech recognition: this engine does not know what words, if any, are spoken. "
    "Use a transcription source for that and cite it separately.",
    "No source separation: in a mix, nothing here can attribute a measurement to an "
    "individual instrument or voice.",
    "No perceptual judgement of quality: measurements say what is present, not whether "
    "it is good, apt, or well-made.",
    "Source identity (violin, synth, door, rain) is not measured. Any such statement in a "
    "reading is inference and must be marked as such.",
    "Octave-band figures are shares of total power, not perceived loudness; they do not "
    "account for equal-loudness weighting.",
]

MONO_BLIND = [
    "Mono downmix: every level and spectrum figure describes the summed signal. Spatial "
    "position and width are not measured; channel correlation is the only spatial fact here.",
]

DECAY_BLIND = [
    "The decay figure is an extrapolation after the loudest onset, not a measured RT60. "
    "Do not quote it as reverb time.",
]


def _get(measurements: dict, path: str):
    node = measurements
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node["value"] if isinstance(node, dict) and "value" in node else node


def _obs(statement: str, refs: list[str], measurements: dict) -> dict:
    return {
        "statement": statement,
        "evidence": "measured",
        "refs": refs,
        "values": {r: _get(measurements, r) for r in refs},
    }


def observations(m: dict) -> list[dict]:
    out = []
    audio = m.get("audio", {})
    lv, sp, tm, sc = m.get("levels"), m.get("spectrum"), m.get("timing"), m.get("space")

    if lv:
        out.append(_obs(
            f"Peak is {_get(m,'levels.peak_dbfs')} dBFS and unweighted RMS is "
            f"{_get(m,'levels.rms_dbfs')} dBFS over {audio.get('duration_s')} s.",
            ["levels.peak_dbfs", "levels.rms_dbfs"], m))
        if _get(m, "levels.clipped_runs"):
            out.append(_obs(
                f"{_get(m,'levels.clipped_runs')} runs of samples reach full scale.",
                ["levels.clipped_runs"], m))
        if abs(_get(m, 'levels.dc_offset') or 0) > 0.001:
            out.append(_obs(
                f"The signal carries a DC offset of {_get(m,'levels.dc_offset')}.",
                ["levels.dc_offset"], m))

    if sp:
        out.append(_obs(
            f"Spectral centroid is {_get(m,'spectrum.centroid_hz')} Hz and 85% of the "
            f"power lies below {_get(m,'spectrum.rolloff85_hz')} Hz.",
            ["spectrum.centroid_hz", "spectrum.rolloff85_hz"], m))
        bands = sp.get("bands", {})
        if bands:
            top = sorted(bands.items(), key=lambda kv: -(kv[1]["value"] or 0))[:2]
            out.append(_obs(
                "The largest octave-band shares are "
                + ", ".join(f"{k} Hz ({v['value']}%)" for k, v in top) + ".",
                [f"spectrum.bands.{k}" for k, _ in top], m))

    if tm:
        out.append(_obs(
            f"{_get(m,'timing.onsets')} onsets ({_get(m,'timing.onset_rate_per_s')} per "
            f"second); {round(100*(_get(m,'timing.silent_fraction') or 0),1)}% of frames "
            f"sit below the silence floor.",
            ["timing.onsets", "timing.onset_rate_per_s", "timing.silent_fraction"], m))

    if sc and _get(m, "space.stereo_correlation") is not None:
        out.append(_obs(
            f"Channel correlation is {_get(m,'space.stereo_correlation')} and L/R balance "
            f"is {_get(m,'space.lr_balance_db')} dB.",
            ["space.stereo_correlation", "space.lr_balance_db"], m))
    return out


def claims(m: dict) -> list[dict]:
    """Interpretations, each tied to the numbers behind it."""
    out: list[dict] = []

    def claim(text: str, basis: list[str], confidence: str = "moderate") -> None:
        present = [b for b in basis if _get(m, b) is not None]
        if present:
            out.append({"statement": text, "evidence": "inferred",
                        "basis": present, "confidence": confidence,
                        "basis_values": {b: _get(m, b) for b in present}})

    flat = _get(m, "spectrum.flatness")
    if flat is not None:
        if flat < 0.15:
            claim("The signal is tonal or harmonic rather than noise-like.", ["spectrum.flatness"])
        elif flat > 0.5:
            claim("The signal is noise-like or broadband rather than pitched.", ["spectrum.flatness"])

    centroid = _get(m, "spectrum.centroid_hz")
    if centroid is not None:
        if centroid < 500:
            claim("Energy sits low: this reads as bass-heavy or dull.", ["spectrum.centroid_hz"])
        elif centroid > 4000:
            claim("Energy sits high: this reads as bright, hissy or cymbal-like.",
                  ["spectrum.centroid_hz"])

    clipped = _get(m, "levels.clipped_runs")
    if clipped:
        claim("There is hard clipping: whatever headroom existed was exceeded.",
              ["levels.clipped_runs", "levels.peak_dbfs"], "high")

    silent = _get(m, "timing.silent_fraction")
    rate = _get(m, "timing.onset_rate_per_s")
    if silent is not None and silent > 0.5:
        claim("The file is mostly silence with isolated events: sparse, gated or cue-like "
              "rather than continuous.", ["timing.silent_fraction"], "moderate")
    if rate is not None and rate > 3:
        claim("Events arrive at a fast rate: this reads as rhythmic or percussive.",
              ["timing.onset_rate_per_s"])

    corr = _get(m, "space.stereo_correlation")
    if corr is not None:
        if corr > 0.95:
            claim("The channels are near-identical: effectively mono or dual-mono.",
                  ["space.stereo_correlation"], "high")
        elif corr < 0.2:
            claim("The channels decorrelate: a wide or out-of-phase stereo image. "
                  "Check mono compatibility before playback.",
                  ["space.stereo_correlation"], "moderate")

    decay = _get(m, "space.decay_estimate")
    if decay:
        claim(f"Energy decays over roughly {decay} s, which reads as a room or a tail "
              f"rather than a dry close recording.", ["space.decay_estimate"], "low")
    return out


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def listen(path: str, modes: list[str] | None = None) -> dict:
    """Measure, then state. Never states more than the measurements carry."""
    measurements = engine.analyse(path, modes)
    record = {
        "record_version": RECORD_VERSION,
        "engine": {"name": "hermes-ears", "version": engine.ENGINE_VERSION},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {"path": path, "sha256": _sha256(path)},
        "audio": measurements.get("audio", {}),
        "measurements": {k: v for k, v in measurements.items() if k != "audio"},
        "observations": observations(measurements),
        "claims": claims(measurements),
        "blind_spots": list(ALWAYS_BLIND)
        + (MONO_BLIND if measurements.get("audio", {}).get("source_channels") == 1 else [])
        + (DECAY_BLIND if "space" in measurements else []),
    }
    return record


def render_markdown(record: dict) -> str:
    """Chat view. Measurements first, interpretation second, blind spots last."""
    lines = []
    audio = record.get("audio", {})
    lines.append(f"**hermes-ears — {record['source']['path']}**")
    lines.append(
        f"*{audio.get('duration_s')} s · {audio.get('source_sample_rate')} Hz source · "
        f"{audio.get('source_channels')} ch · sha256 {record['source']['sha256'][:12]}…*")
    lines.append("")

    lines.append("**Measured**")
    for obs in record["observations"]:
        lines.append(f"- {obs['statement']}")
    lines.append("")

    if record["claims"]:
        lines.append("**Inferred** *(not measurements)*")
        for c in record["claims"]:
            lines.append(f"- {c['statement']} — *{c['confidence']} confidence; "
                         f"from {', '.join(c['basis'])}*")
        lines.append("")

    lines.append("**Blind spots**")
    for spot in record["blind_spots"]:
        lines.append(f"- {spot}")
    return "\n".join(lines)
