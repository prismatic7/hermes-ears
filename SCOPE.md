# hermes-ears — scope

A listening engine for Hermes. You point it at an audio file; it measures, then states. Every
statement is tagged as a measurement or as an inference, every inference names the measurements
behind it, and the record always ends with what the instrument cannot establish.

## The one idea

Audio tools usually answer in prose, and agent tools usually answer in guesses. This one refuses
both. The record has three layers, and they are not allowed to blur:

1. **Measurements** — each value carries the method that produced it
   (`"rms_dbfs": {"value": -21.885, "unit": "dBFS", "method": "unweighted RMS over the whole file (not LUFS: no K-weighting applied)"}`).
2. **Observations** — restatements of measurements, naming the keys they restate.
3. **Claims** — interpretations, tagged `inferred`, carrying the measurement keys they rest on and
   a confidence. A claim with no basis is not emitted; the test suite asserts that.

Then **blind spots**, every time: no speech recognition, no source separation, no quality
judgement, no source identity, no equal-loudness weighting, and a decay figure that is not RT60.

The discipline is the product. A sound designer who needs to justify a cue to a director, or a
researcher who needs to defend a claim about a recording, gets a document where the measurement
and the interpretation are visibly different things.

## What exists now (v0.1.0)

| Pass | What it measures | Method notes |
|---|---|---|
| `levels` | peak dBFS, unweighted RMS dBFS, crest factor, DC offset, clipping runs, signal presence | Sample peak of the mono downmix. **Not** LUFS — no K-weighting, and it says so in the record. |
| `spectrum` | centroid, 85% rolloff, spectral flatness, ten octave-band power shares, frames analysed | Hann-windowed 4096-point FFT, 50% overlap, power-weighted. |
| `timing` | onset count and rate, silence windows, silent fraction | 20 ms frame energy, mean+1.5 sd rising-edge detector with a 50 ms refractory; configurable floor. |
| `space` | decay estimate, stereo correlation, L/R balance | Decay is an extrapolation after the loudest onset, labelled as an estimate. Correlation is the only spatial fact. |

Interface: the `ears_listen` tool (`path`, `modes?`, `format?`) and the `/listen` command.

## Deliberate non-goals

- **No transcription.** Words are not this engine's business; pair it with a real STT and cite it.
- **No source separation.** A measurement of a mix is a measurement of the mix.
- **No aesthetic verdict.** It will tell you the file is mostly low-mid energy; it will not tell
  you that is wrong for the scene.
- **No LUFS/true-peak compliance claims** until K-weighting and oversampled peak detection are
  actually implemented. Naming an unweighted RMS "LUFS" would be exactly the failure this engine
  exists to avoid.

## Next passes, in order

1. **`speech`** — optional STT lane (whisper-docker), timecoded transcript in the record, so
   "what is said" becomes a *measurement with a source* rather than a guess.
2. **`compare`** — two files, one record: level-matched A/B with the differences that survive
   matching, and an explicit list of what the comparison cannot hold constant.
3. **`cue`** — theatre-shaped view: tail length, seamless-loop viability, head/tail headroom for
   a QLab cue, intelligibility risk over dialogue beds.
4. **Mode registry** — modes as data (a small declarative file per pass), so a new measurement
   pass does not mean editing the engine.
5. **Renderers** — markdown (done), JSON (done), a self-contained HTML report, and a Desktop pane.

## Licensing and provenance

Our code, MIT. AKOÚŌ — the listening framework by **emeisazam (eme)** at **Sonic Field Labs** —
is the method lineage: the discipline of separating claim from evidence, and the insistence that
an instrument states its own limits, both come from that work. It is credited in `NOTICE`. None
of its files, text, schemas or mode definitions are redistributed here; the passes above are named
after the measurement they perform, not borrowed from its seventeen modes. That keeps the licence
position clean (MIT to MIT, no vendored material) while saying plainly where the thinking came from.

`ffmpeg` and `ffprobe` are called as separate executables through `subprocess`, with fixed argv
and no shell. Executing a binary is not linking it, so their GPL/LGPL terms do not reach this
plugin; they are listed as system dependencies and disclosed.

## What would make this a competition entry

The judges favour plugins that do more than a prompt or a skill could. This qualifies on the
mechanical side already — real DSP, a typed record, a test suite that calibrates against known
inputs. What it needs before a 90-second demo:

- one convincing real-world run on a file the audience can hear;
- the `compare` pass, because "these two cues differ by X after level matching" is the moment the
  instrument becomes useful rather than interesting;
- a public repo, a LICENSE, and a README with the record shown inline;
- an honest demo that includes the blind spots — the refusal is the differentiator, and hiding it
  in the small print would undercut the whole premise.
