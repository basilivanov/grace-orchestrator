# ############################################################################
# AI_HEADER: context_collector
# ROLE: Analyze codebase context for self-evolution — static analysis + cheap LLM fork.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Collect structured codebase context for self-evolution task scoping.
# inputs: task_description (str), target_scope (list[str]), project_root (Path).
# returns: CodebaseContext dataclass with files, summary, estimated_scope, complexity.
# side_effects: May call external LLM CLI (agy/gemini-flash).
# emitted_logs: context_collected on successful analysis.
# error_behavior: Falls back to full-scope heuristic on LLM failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: FileContext
#   - dataclass: CodebaseContext
#   - class: ContextCollector
#   - function: _extract_module_contract
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("context_collector")
_DEFAULT_TIMEOUT = int(os.environ.get("GRACE_CONTEXT_TIMEOUT", "60"))


@dataclass
class FileContext:
    path: str
    module_contract: str | None
    exports: list[str]
    size_lines: int


@dataclass
class CodebaseContext:
    files: list[FileContext] = field(default_factory=list)
    summary: str = ""
    estimated_scope: list[str] = field(default_factory=list)
    affected_contracts: list[str] = field(default_factory=list)
    complexity_score: int = 0
    canon_violations: list[str] = field(default_factory=list)


class ContextCollector:

    def __init__(self, project_root: Path | None = None,
                 model: str | None = None, cli: str = "opencode"):
        self._root = project_root or Path.cwd()
        self._model = model or os.environ.get("GRACE_CONTEXT_MODEL", "deepseek/deepseek-v4-flash")
        self._cli = cli  # "opencode" or "agy"

    async def collect(
        self,
        task_description: str,
        target_scope: list[str] | None = None,
        project_root: Path | None = None,
    ) -> CodebaseContext:
        root = project_root or self._root
        scope = target_scope or ["src/grace_control/"]

        files = _scan_files(root, scope)
        _log.debug("context_scan_done", file_count=len(files))

        summaries = self._build_file_summary(files)

        for attempt in range(2):
            try:
                llm_result = await self._invoke_llm(task_description, summaries, files)
                _log.info("context_collected",
                    file_count=len(files),
                    estimated_scope_count=len(llm_result.estimated_scope),
                    complexity=llm_result.complexity_score)
                return llm_result
            except Exception as e:
                _log.warn("context_llm_failed", attempt=attempt + 1, error=str(e)[:120])
                if attempt == 1:
                    return self._fallback_analysis(task_description, files, scope)

        return self._fallback_analysis(task_description, files, scope)

    def _build_file_summary(self, files: list[FileContext]) -> str:
        lines = []
        for f in files:
            exports = ", ".join(f.exports[:10])
            contract = (f.module_contract or "?")[:80]
            lines.append(f"  {f.path} ({f.size_lines}L exports=[{exports}] contract={contract}")
        return "\n".join(lines)

    async def _invoke_llm(
        self,
        task: str,
        file_manifest: str,
        files: list[FileContext],
    ) -> CodebaseContext:
        max_manifest = 1500 if self._cli == "opencode" else 6000
        manifest_text = file_manifest[:max_manifest]
        if len(file_manifest) > max_manifest:
            manifest_text += f"\n... ({len(files)} files total, truncated)"
        file_list = "\n".join(f.path for f in files[:20])
        if len(files) > 20:
            file_list += f"\n... ({len(files)} files total)"

        prompt = f"""You are a codebase analyzer. Given a task and file manifest, determine the minimal scope of changes needed.

Task: {task}

Available files:
{manifest_text}

All files:
{file_list}

Respond ONLY with valid JSON:
{{
  "summary": "<1-2 sentence summary of what needs to change>",
  "estimated_scope": ["path/to/file1.py", "path/to/file2.py"],
  "affected_contracts": ["MODULE_CONTRACT name or empty list"],
  "complexity_score": 0-300
}}

Where complexity: 0-50 (simple config), 51-150 (single module change), 151-250 (multi-module), 251-300 (architectural)."""

        raw = await self._run_llm(prompt)
        data = json.loads(raw)

        ctx = CodebaseContext(
            files=files,
            summary=data.get("summary", ""),
            estimated_scope=data.get("estimated_scope", []),
            affected_contracts=data.get("affected_contracts", []),
            complexity_score=data.get("complexity_score", 150),
        )
        return ctx

    async def _run_llm(self, prompt: str) -> str:
        import re as _re2

        safe = _re2.sub(r'[^a-zA-Z0-9 ]', '', prompt[:30]).replace(' ', '_')[:40]
        prompt_dir = self._root / ".grace_state" / "ctx_prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        tmp = prompt_dir / f"ctx_{safe}.txt"
        tmp.write_text(prompt)

        if self._cli == "opencode":
            instruction = f"Read the task from .grace_state/ctx_prompts/{tmp.name}. Respond ONLY with the requested JSON dict, no other text."
            cmd = ["opencode", "run", "--model", self._model, instruction]
        else:
            cmd = ["agy", "--model", self._model, "--prompt-file", str(tmp), "--json"]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self._root),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_DEFAULT_TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"LLM timed out after {_DEFAULT_TIMEOUT}s")

        tmp.unlink(missing_ok=True)
        out = stdout.decode("utf-8", errors="replace").strip()
        if not out:
            err = stderr.decode("utf-8", errors="replace")[:200]
            raise RuntimeError(f"LLM returned empty output: {err}")

        return _extract_json_block(out)

    def _fallback_analysis(self, task: str, files: list[FileContext], scope: list[str]) -> CodebaseContext:
        raw_paths = set()
        for s in scope:
            p = self._root / s
            if p.is_file():
                raw_paths.add(s)
            elif p.is_dir():
                for f in p.rglob("*.py"):
                    raw_paths.add(str(f.relative_to(self._root)))

        return CodebaseContext(
            files=files,
            summary=f"Fallback analysis for: {task[:200]}",
            estimated_scope=sorted(raw_paths),
            affected_contracts=[],
            complexity_score=200,
            canon_violations=[],
        )


_CODE_EXTS = {".py", ".html", ".js", ".css", ".json", ".yaml", ".yml", ".md"}


def _scan_files(root: Path, scopes: list[str]) -> list[FileContext]:
    results = []
    seen = set()
    for scope in scopes:
        p = root / scope
        if p.is_file() and p.suffix in _CODE_EXTS and str(p) not in seen:
            seen.add(str(p))
            results.append(_analyze_file(p, root))
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.suffix not in _CODE_EXTS:
                    continue
                if str(f) not in seen and "__pycache__" not in str(f):
                    seen.add(str(f))
                    results.append(_analyze_file(f, root))
    return results


def _analyze_file(filepath: Path, root: Path) -> FileContext:
    try:
        content = filepath.read_text()
    except Exception:
        return FileContext(path=str(filepath.relative_to(root)), module_contract=None, exports=[], size_lines=0)

    lines = content.split("\n")
    contract = _extract_module_contract(content)
    exports = _extract_exports(content)
    return FileContext(
        path=str(filepath.relative_to(root)),
        module_contract=contract,
        exports=exports,
        size_lines=len(lines),
    )


def _extract_module_contract(text: str) -> str | None:
    m = re.search(r"# START_MODULE_CONTRACT\s*\n(.*?)\n# END_MODULE_CONTRACT", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_exports(text: str) -> list[str]:
    exports = []
    for m in re.finditer(r"^(?:async )?def (\w+)", text, re.MULTILINE):
        name = m.group(1)
        if not name.startswith("_"):
            exports.append(name)
    for m in re.finditer(r"^class (\w+)", text, re.MULTILINE):
        exports.append(m.group(1))
    return exports


def _extract_json_block(text: str) -> str:
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        return m.group(0)
    return text
