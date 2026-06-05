#!/usr/bin/env python3
"""Generate docs/openapi.json from FastAPI app + docs/state-diagram.md +
docs/packet-states.md from the canonical VALID_TRANSITIONS map.

Run:    python3 scripts/generate_docs.py            # write in place
        python3 scripts/generate_docs.py --check    # CI mode — exit non-zero
                                                  # if generated files differ
                                                  # from what's on disk
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from grace_control.api.main import app  # noqa: E402
from grace_control.core.state_machine import PacketStateMachine  # noqa: E402
from grace_control.db.schema import PacketState  # noqa: E402

VALID_TRANSITIONS = PacketStateMachine.VALID_TRANSITIONS
TERMINAL_STATES = sorted(PacketStateMachine.TERMINAL_STATES, key=lambda s: s.value)

GENERATED_FILES = ("openapi.json", "state-diagram.md", "packet-states.md")


def _render_openapi() -> str:
    return json.dumps(app.openapi(), indent=2, default=str)


def _render_state_diagram() -> str:
    mermaid = ["```mermaid", "stateDiagram-v2"]
    # Iterate transitions sorted by source value for deterministic output.
    for src_state in sorted(VALID_TRANSITIONS.keys(), key=lambda s: s.value):
        for tgt in sorted(VALID_TRANSITIONS[src_state], key=lambda s: s.value):
            mermaid.append(f"    {src_state.value} --> {tgt.value}")
    mermaid.append("")
    mermaid.append("    classDef terminal fill:#fdd,stroke:#900,stroke-width:2px")
    for ts in TERMINAL_STATES:
        mermaid.append(f"    class {ts.value} terminal")
    mermaid.append("```")
    return "\n".join(mermaid) + "\n"


def _render_packet_states() -> str:
    lines = ["# Packet States", ""]
    lines.append("Auto-generated from grace_control.core.state_machine.")
    lines.append("")
    lines.append("| State | Terminal? | Allowed transitions |")
    lines.append("|-------|-----------|---------------------|")
    for state in sorted(VALID_TRANSITIONS.keys(), key=lambda s: s.value):
        targets = VALID_TRANSITIONS[state]
        terminal = "yes" if state in PacketStateMachine.TERMINAL_STATES else "no"
        tgts = ", ".join(t.value for t in targets) or "(none)"
        lines.append(f"| `{state.value}` | {terminal} | {tgts} |")
    return "\n".join(lines) + "\n"


def _generated_contents() -> dict[str, str]:
    return {
        "openapi.json": _render_openapi(),
        "state-diagram.md": _render_state_diagram(),
        "packet-states.md": _render_packet_states(),
    }


def write_in_place(docs_dir: Path) -> dict[str, int]:
    docs_dir.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for name, content in _generated_contents().items():
        target = docs_dir / name
        target.write_text(content)
        sizes[name] = len(content)
        print(f"wrote {target.relative_to(ROOT)} ({len(content)} bytes)")
    return sizes


def check_fresh(docs_dir: Path) -> int:
    """Return 0 if generated files match what's on disk, 1 otherwise.

    Diffs are printed in unified-diff style for human review.
    """
    import difflib

    expected = _generated_contents()
    drift: list[tuple[str, str, str]] = []
    for name, want in expected.items():
        target = docs_dir / name
        got = target.read_text() if target.exists() else ""
        if got != want:
            drift.append((name, got, want))

    if not drift:
        print(f"docs freshness OK — {len(expected)} files in sync")
        return 0

    print(f"docs drift detected in {len(drift)} file(s):", file=sys.stderr)
    for name, got, want in drift:
        diff = difflib.unified_diff(
            got.splitlines(keepends=True),
            want.splitlines(keepends=True),
            fromfile=f"docs/{name} (committed)",
            tofile=f"docs/{name} (would be generated)",
        )
        sys.stderr.writelines(diff)
    print(
        "\nRun: python3 scripts/generate_docs.py   # to refresh",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="CI mode: exit 1 if generated files drift from disk.",
    )
    args = parser.parse_args()

    docs_dir = ROOT / "docs"

    if args.check:
        return check_fresh(docs_dir)

    write_in_place(docs_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
