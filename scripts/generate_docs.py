#!/usr/bin/env python3
"""Generate docs/openapi.json from FastAPI app + docs/state-diagram.md from
the canonical VALID_TRANSITIONS map.

Run: python3 scripts/generate_docs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from grace_control.api.main import app  # noqa: E402
from grace_control.core.state_machine import PacketStateMachine  # noqa: E402
from grace_control.db.schema import PacketState  # noqa: E402

VALID_TRANSITIONS = PacketStateMachine.VALID_TRANSITIONS
TERMINAL_STATES = PacketStateMachine.TERMINAL_STATES


def main() -> int:
    docs_dir = ROOT / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    openapi = app.openapi()
    (docs_dir / "openapi.json").write_text(json.dumps(openapi, indent=2, default=str))
    print(f"wrote docs/openapi.json ({len(openapi.get('paths', {}))} paths)")

    mermaid = ["```mermaid", "stateDiagram-v2"]
    for src_state, targets in VALID_TRANSITIONS.items():
        if not targets:
            continue
        for tgt in targets:
            mermaid.append(f"    {src_state.value} --> {tgt.value}")
    mermaid.append("")
    mermaid.append("    classDef terminal fill:#fdd,stroke:#900,stroke-width:2px")
    for ts in TERMINAL_STATES:
        mermaid.append(f"    class {ts.value} terminal")
    mermaid.append("```")
    (docs_dir / "state-diagram.md").write_text("\n".join(mermaid) + "\n")
    print(f"wrote docs/state-diagram.md ({len(VALID_TRANSITIONS)} states, "
          f"{sum(len(t) for t in VALID_TRANSITIONS.values())} transitions)")

    states_md = ["# Packet States", ""]
    states_md.append("Auto-generated from grace_control.core.state_machine.")
    states_md.append("")
    states_md.append("| State | Terminal? | Allowed transitions |")
    states_md.append("|-------|-----------|---------------------|")
    for state, targets in VALID_TRANSITIONS.items():
        terminal = "yes" if state in TERMINAL_STATES else "no"
        tgts = ", ".join(t.value for t in targets) or "(none)"
        states_md.append(f"| `{state.value}` | {terminal} | {tgts} |")
    (docs_dir / "packet-states.md").write_text("\n".join(states_md) + "\n")
    print(f"wrote docs/packet-states.md ({len(VALID_TRANSITIONS)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
