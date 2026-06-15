# ############################################################################
# AI_HEADER: packet_materializer
# ROLE: Convert a packet's spec_json into an EXECUTION_PACKET.md the legacy
#       codex_launcher can consume.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Pure transformation packet_data + state_root → Path. No DB, no I/O
#          outside the target file. Safe to test in isolation.
# inputs: packet_data dict (id, spec_json, ...), state_root Path.
# returns: Path to EXECUTION_PACKET.md.
# side_effects: Creates state_root/packets/{id}/EXECUTION_PACKET.md.
# emitted_logs: None.
# error_behavior: Raises on filesystem error.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: PacketMaterializer
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

import yaml


# Legacy branch format for agent worktrees. The canonical home moved to
# `grace_control.agent.legacy_backend.LEGACY_BRANCH_FORMAT` (P2#8) and
# that module was deleted in W8. The constant lives here for tests that
# still check the format string.
BRANCH_FORMAT = "agent/default/{packet_id}/{attempt_slug}"


class PacketMaterializer:
    """Renders EXECUTION_PACKET.md from a packet DB row.

    W02: No DEFAULT_SCOPE — executable packets must have explicit scope.
    Missing scope raises ValueError instead of falling back to 'src/'.
    W04: Enriched with all 17 required sections for coder context bundle.

    The 17 sections:
      1. Objective
      2. Business requirement
      3. Role and non-goals
      4. Allowed write scope
      5. Frozen scope
      6. Relevant file tree
      7. Selected file previews
      8. Nearby tests
      9. Config/build files available
     10. Import/dependency hints
     11. Coder instructions
     12. Acceptance criteria
     13. Verification commands by T0/T1/T2
     14. Full expected evidence fields
     15. Workspace mode and limitations
     16. Target repo root diagnostics
     17. Full spec JSON dump
    """

    # W02: DEFAULT_SCOPE removed — no silent fallback for executable packets.
    # The plan compiler enforces non-empty scope for coder packets.
    DEFAULT_FROZEN: list[str] = []
    DEFAULT_VERIFICATION = "pytest -v\npython3 scripts/grace_lint.py"

    CONFIG_ALLOWLIST = [
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
        "tox.ini",
        "mypy.ini",
        "ruff.toml",
        ".ruff.toml",
        "package.json",
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "tsconfig.json",
        "tsconfig.*.json",
        "vite.config.*",
        "vitest.config.*",
        "playwright.config.*",
        "conftest.py",
        ".env.example",
    ]

    def materialize(
        self,
        packet_data: dict,
        state_root: Path,
        target_root: Path | None = None,
    ) -> Path:
        packet_id = packet_data["id"]
        packet_dir = state_root / "packets" / packet_id
        packet_dir.mkdir(parents=True, exist_ok=True)

        spec_json = packet_data["spec_json"] if isinstance(packet_data["spec_json"], dict) else {}
        spec_str = yaml.dump(spec_json, default_flow_style=False, allow_unicode=True)

        scope = spec_json.get("scope", [])
        if isinstance(scope, str):
            scope = [scope]

        # W02: Fail-closed — refuse to materialize executable packet without scope
        if not scope:
            raise ValueError(
                f"Packet {packet_id} has no write scope — "
                f"every executable packet must have explicit scope. "
                f"The plan compiler should have caught this."
            )

        scope_lines = "\n".join(f"- {s}" for s in scope)

        frozen = spec_json.get("frozen_scope", [])
        if isinstance(frozen, str):
            frozen = [frozen]
        frozen_lines = "\n".join(f"- {s}" for s in frozen) if frozen else "- (none)"

        verification_text = self._render_verification(spec_json.get("verification", {}))

        expected_raw = spec_json.get("expected_evidence", [])

        # Section 6: Relevant file tree
        file_tree = self._render_file_tree(scope, target_root)

        # Section 7: Selected file previews
        file_previews = self._render_file_previews(scope, target_root)

        # Section 8: Nearby tests
        nearby_tests = self._render_nearby_tests(scope, target_root)

        # Section 9: Config/build files available
        config_available = self._render_config_available(target_root)

        # Section 10: Import/dependency hints
        import_hints = self._render_import_hints(scope, target_root)

        # Section 14: Full expected evidence fields
        expected_lines = self._render_expected_evidence(expected_raw)

        # Section 12: Acceptance criteria
        acceptance_criteria = spec_json.get("acceptance_criteria", [])
        if isinstance(acceptance_criteria, str):
            acceptance_criteria = [acceptance_criteria]
        ac_lines = "\n".join(f"- {c}" for c in acceptance_criteria) if acceptance_criteria else "- (none specified)"

        # Section 11: Coder instructions
        coder_instructions = spec_json.get("coder_instructions", [])
        if isinstance(coder_instructions, str):
            coder_instructions = [coder_instructions]
        ci_lines = "\n".join(f"- {c}" for c in coder_instructions) if coder_instructions else "- (none)"

        # Section 15: Workspace mode
        workspace_mode = spec_json.get("workspace_mode", "full_git_worktree")
        workspace_limitations = []
        if workspace_mode == "scoped_copy":
            workspace_limitations.append("Only scope files + config allowlist are available")
            workspace_limitations.append("Cannot run tests requiring full repo context")
        elif workspace_mode == "target_repo_worktree":
            workspace_limitations.append("Full target repo available via git worktree")
        else:
            workspace_limitations.append("Full orchestrator repo available via git worktree")
        ws_lim_lines = "\n".join(f"- {l}" for l in workspace_limitations)

        # Section 16: Target repo root diagnostics
        target_repo = spec_json.get("target_repo_root", "") or ""
        if target_root:
            target_repo = str(target_root.resolve())
        target_diagnostics = self._render_target_diagnostics(target_repo, target_root)

        pd = packet_data
        content = f"""# Execution Packet: {pd['id']}

## 1. Objective
{pd.get('objective') or pd.get('title') or pd['id']}

## 2. Business Requirement
{pd.get('description') or pd.get('title', '')}

## 3. Role and Non-Goals
- Role: coder
- Non-goals: Do not modify frozen scope paths. Do not redesign architecture. Do not refactor unrelated code. Do not change tests unless explicitly required.

## 4. Allowed Write Scope
{scope_lines}

## 5. Frozen Scope (do not modify)
{frozen_lines}

## 6. Relevant File Tree
{file_tree}

## 7. Selected File Previews
{file_previews}

## 8. Nearby Tests
{nearby_tests}

## 9. Config / Build Files Available
{config_available}

## 10. Import / Dependency Hints
{import_hints}

## 11. Coder Instructions
{ci_lines}

## 12. Acceptance Criteria
{ac_lines}

## 13. Verification Commands
{verification_text}

## 14. Full Expected Evidence Fields
{expected_lines}

## 15. Workspace Mode and Limitations
Mode: {workspace_mode}
{ws_lim_lines}

## 16. Target Repo Root Diagnostics
{target_diagnostics}

## 17. Full Spec JSON
```yaml
{spec_str}
```
"""
        packet_file = packet_dir / "EXECUTION_PACKET.md"
        packet_file.write_text(content)
        return packet_file

    # ── W04: Context section helpers ─────────────────────────────────────

    def _render_file_tree(self, scope: list[str], target_root: Path | None) -> str:
        """Section 6: list scope files with sizes and structure."""
        if not target_root or not target_root.exists():
            return "- (target root unavailable)"
        parts = []
        for sp in scope:
            p = target_root / sp
            if p.exists():
                rel = str(p.relative_to(target_root))
                if p.is_dir():
                    children = list(p.rglob("*"))
                    parts.append(f"- {rel}/ ({len(children)} items)")
                    for c in children[:20]:
                        if c.is_file():
                            size = c.stat().st_size
                            parts.append(f"    - {c.relative_to(target_root)} ({size}B)")
                    if len(children) > 20:
                        parts.append(f"    - ... ({len(children) - 20} more)")
                else:
                    size = p.stat().st_size
                    parts.append(f"- {rel} ({size}B)")
            else:
                parts.append(f"- {sp} (not found)")
        return "\n".join(parts) if parts else "- (empty scope)"

    def _render_file_previews(self, scope: list[str], target_root: Path | None) -> str:
        """Section 7: first 20 lines of each scope file."""
        if not target_root or not target_root.exists():
            return "- (target root unavailable)"
        parts = []
        for sp in scope:
            p = target_root / sp
            if p.exists() and p.is_file():
                try:
                    lines = p.read_text().split("\n")
                    preview = "\n".join(lines[:20])
                    if len(lines) > 20:
                        preview += f"\n    ... ({len(lines)} lines total)"
                    parts.append(f"### {sp}\n```\n{preview}\n```")
                except Exception:
                    parts.append(f"### {sp}\n- (could not read)")
        return "\n".join(parts) if parts else "- (no files to preview)"

    def _render_nearby_tests(self, scope: list[str], target_root: Path | None) -> str:
        """Section 8: find test files related to scope paths."""
        if not target_root or not target_root.exists():
            return "- (target root unavailable)"
        seen = set()
        results = []
        for sp in scope:
            p = target_root / sp
            if not p.exists():
                continue
            if p.is_file():
                parent = p.parent
            else:
                parent = p
            # Look for test files in parent directory
            test_dir_candidates = [
                parent / "tests",
                parent.parent / "tests",
                target_root / "tests",
            ]
            for td in test_dir_candidates:
                if td.exists() and td.is_dir():
                    for f in sorted(td.iterdir()):
                        if f.suffix in (".py", ".js", ".ts", ".jsx", ".tsx") and str(f) not in seen:
                            seen.add(str(f))
                            results.append(str(f.relative_to(target_root)))
        if not results:
            # Broader search
            test_root = target_root / "tests"
            if test_root.exists():
                for f in sorted(test_root.rglob("test_*")):
                    if f.is_file() and str(f) not in seen:
                        seen.add(str(f))
                        results.append(str(f.relative_to(target_root)))
        return "\n".join(f"- {r}" for r in results) if results else "- (no nearby tests found)"

    def _render_config_available(self, target_root: Path | None) -> str:
        """Section 9: check which config/build files exist."""
        if not target_root or not target_root.exists():
            return "- (target root unavailable)"
        found = []
        for cf in self.CONFIG_ALLOWLIST:
            if any(c in cf for c in ("*", "?", "[")):
                matches = list(target_root.glob(cf))
                if matches:
                    for m in matches:
                        found.append(f"- {m.name} (available)")
                else:
                    found.append(f"- {cf} (no match)")
            else:
                p = target_root / cf
                if p.exists():
                    found.append(f"- {cf} (available)")
                else:
                    found.append(f"- {cf} (not found)")
        return "\n".join(found)

    def _render_import_hints(self, scope: list[str], target_root: Path | None) -> str:
        """Section 10: extract imports from scope files."""
        if not target_root or not target_root.exists():
            return "- (target root unavailable)"
        all_imports: dict[str, set[str]] = {}
        for sp in scope:
            p = target_root / sp
            if p.exists() and p.is_file():
                try:
                    text = p.read_text()
                    for line in text.split("\n"):
                        line = line.strip()
                        if line.startswith("import ") or line.startswith("from "):
                            module = line.split()[1] if line.startswith("import ") else line.split()[1]
                            if sp not in all_imports:
                                all_imports[sp] = set()
                            all_imports[sp].add(line)
                except Exception:
                    pass
        if not all_imports:
            return "- (no import hints extracted)"
        parts = []
        for filepath, imports in all_imports.items():
            parts.append(f"### {filepath}")
            for imp in sorted(imports):
                parts.append(f"- `{imp}`")
        return "\n".join(parts) if parts else "- (no imports found)"

    def _render_expected_evidence(self, expected_raw: list) -> str:
        """Section 14: full structured evidence fields (not just IDs).

        W05: Render all evidence fields (id, kind, stage, owner, producer,
        profile, required, coder_blocking, artifact_patterns, description,
        validation_hint) — not only IDs.
        """
        if not expected_raw:
            return """- test_results (list of {command, exit_code, stdout, stderr, duration_ms})
- lint_output (list of {tool, passed, errors, warnings})
- changed_files (list of repo-relative paths)
"""

        lines = []
        for e in expected_raw:
            if isinstance(e, dict):
                eid = e.get("id", "unknown")
                kind = e.get("kind", "command")
                stage = e.get("stage", "")
                owner = e.get("owner", "coder")
                producer = e.get("producer", "")
                profile = e.get("profile", "")
                required = e.get("required", True)
                coder_blocking = e.get("coder_blocking", True)
                artifact_patterns = e.get("artifact_patterns", e.get("pattern", []))
                if isinstance(artifact_patterns, str):
                    artifact_patterns = [artifact_patterns]
                desc = e.get("description", "")
                validation_hint = e.get("validation_hint", "")

                parts = [f"- **{eid}**"]
                parts.append(f"  kind: {kind}")
                if stage:
                    parts.append(f"  stage: {stage}")
                parts.append(f"  owner: {owner}")
                if producer:
                    parts.append(f"  producer: {producer}")
                if profile:
                    parts.append(f"  profile: {profile}")
                parts.append(f"  required: {required}")
                parts.append(f"  coder_blocking: {coder_blocking}")
                if artifact_patterns:
                    parts.append(f"  artifact_patterns: {artifact_patterns}")
                if desc:
                    parts.append(f"  description: {desc}")
                if validation_hint:
                    parts.append(f"  validation_hint: {validation_hint}")
                # W05: legacy pattern warning
                if e.get("pattern") and not e.get("artifact_patterns"):
                    parts.append(f"  ⚠ legacy 'pattern' field — use 'artifact_patterns'")
                lines.append("\n".join(parts))
            else:
                lines.append(f"- {e}  ⚠ string evidence (legacy — use structured dict)")
        return "\n".join(lines) if lines else "- (none)"

    def _render_target_diagnostics(self, target_repo: str, target_root: Path | None) -> str:
        """Section 16: diagnostics about the target repo root."""
        if not target_root or not target_root.exists():
            return f"- target_repo: {target_repo or '(not set)'}\n- status: NOT FOUND"
        lines = [f"- target_repo: {target_repo}"]
        lines.append(f"- resolved: {target_root.resolve()}")
        lines.append(f"- exists: {target_root.exists()}")
        lines.append(f"- is_git: {(target_root / '.git').exists()}")
        try:
            total = sum(f.stat().st_size for f in target_root.rglob("*") if f.is_file())
            file_count = len(list(target_root.rglob("*")))
            lines.append(f"- file_count: {file_count}")
            lines.append(f"- total_size: {total} bytes")
        except Exception:
            lines.append("- file_count: (error reading)")
        return "\n".join(lines)

    # ── End W04 helpers ──────────────────────────────────────────────────

    @staticmethod
    def _render_verification(verification_raw) -> str:
        if isinstance(verification_raw, list):
            return "\n".join(
                f"- {v}" if isinstance(v, str) else f"- {' '.join(v)}"
                for v in verification_raw
            )
        if isinstance(verification_raw, dict):
            parts = []
            for stage in ("t0", "t1", "t2"):
                cmds = verification_raw.get(stage, [])
                for c in cmds:
                    c_str = " ".join(c) if isinstance(c, list) else c
                    parts.append(f"- [{stage}] {c_str}")
            return "\n".join(parts) if parts else PacketMaterializer.DEFAULT_VERIFICATION
        return PacketMaterializer.DEFAULT_VERIFICATION
