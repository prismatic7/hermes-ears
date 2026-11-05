"""hermes-ears — a listening engine for Hermes.

Two tools and a command. The engine measures audio and states what it measured;
interpretation is a separate layer whose statements must name their evidence, and
the record always lists what the instrument cannot establish.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ears import engine, modes  # noqa: E402

PLUGIN_NAME = "hermes-ears"
PLUGIN_VERSION = engine.ENGINE_VERSION

_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute path to an audio file (wav, aiff, mp3, flac, m4a…)"},
        "modes": {
            "type": "array",
            "items": {"type": "string", "enum": ["levels", "spectrum", "timing", "space"]},
            "description": "Which measurement passes to run. Omit for all of them.",
        },
        "format": {
            "type": "string",
            "enum": ["markdown", "json"],
            "description": "markdown (default) for a reading, json for the record.",
        },
    },
    "required": ["path"],
    "additionalProperties": False,
}


def _tool(args=None, **kwargs):
    args = args or {}
    path = str(args.get("path") or "").strip()
    if not path:
        return json.dumps({"error": "path is required"})
    if not Path(path).expanduser().exists():
        return json.dumps({"error": f"no such file: {path}"})
    fmt = args.get("format") or "markdown"
    try:
        record = modes.listen(str(Path(path).expanduser()), args.get("modes"))
    except Exception as exc:  # noqa: BLE001 - surfaced to the model, not swallowed
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    if fmt == "json":
        return json.dumps(record, indent=2, ensure_ascii=False)
    return modes.render_markdown(record)


def _command(raw_args: str = "", **kwargs):
    parts = (raw_args or "").split()
    if not parts:
        return "Usage: /listen <path> [levels|spectrum|timing|space]"
    path = parts[0]
    result = _tool({"path": path, "modes": parts[1:] or None})
    try:
        return json.loads(result).get("error") or result
    except ValueError:
        return result


def register(ctx) -> None:
    ctx.register_tool(
        name="ears_listen",
        toolset="ears",
        schema=_SCHEMA,
        handler=_tool,
        description=(
            "Measure an audio file and report what was measured, what is inferred, and what "
            "cannot be established. Observations restate measurements; claims name the "
            "measurements they rest on; blind spots are always listed."),
        emoji="👂",
    )
    ctx.register_command(
        "listen",
        _command,
        description="Measure an audio file (hermes-ears)",
        args_hint="<path> [levels|spectrum|timing|space]",
    )


__all__ = ["register", "engine", "modes"]
