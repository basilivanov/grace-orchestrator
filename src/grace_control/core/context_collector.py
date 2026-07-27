# ############################################################################
# AI_HEADER: context_collector
# ROLE: Smart codebase context collector — cheap LLM determines relevance, reads content, feeds architect.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Collect structured codebase context: scan files, ask cheap LLM which are relevant,
#          read their content, return CodebaseContext with content_previews.
# inputs: task_description (str), target_scope (list[str]), project_root (Path).
# returns: CodebaseContext with files, summary, estimated_scope, complexity, relevant content.
# side_effects: Calls cheap LLM twice (relevance filter + summary).
# emitted_logs: context_collected on success.
# error_behavior: Falls back to full-scope without content on LLM failure.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - dataclass: FileContext
#   - dataclass: CodebaseContext
#   - class: ContextCollector
# END_MODULE_MAP

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("context_collector")
_DEFAULT_TIMEOUT = int(os.environ.get("GRACE_CONTEXT_TIMEOUT", "60"))
_CONTENT_PREVIEW_LINES = 100
_CONTENT_PREVIEW_CHARS = 2500
_MAX_RELEVANT_FILES = 15
_DEFAULT_SCOPE_CANDIDATES = (
    "app/", "src/", "apps/", "packages/", "tests/", "scripts/", "docs/",
    "AGENTS.md", "README.md", "pyproject.toml",
)

#START_BLOCK_DATACLASSES

@dataclass
class FileContext:
    path: str
    module_contract: str | None
    exports: list[str]
    size_lines: int
    content_preview: str = ""
    relevant: bool = False


@dataclass
class CodebaseContext:
    files: list[FileContext] = field(default_factory=list)
    summary: str = ""
    estimated_scope: list[str] = field(default_factory=list)
    affected_contracts: list[str] = field(default_factory=list)
    complexity_score: int = 0
    canon_violations: list[str] = field(default_factory=list)

#END_BLOCK_DATACLASSES

#START_BLOCK_COLLECTOR

class ContextCollector:

    def __init__(self, project_root: Path | None = None,
                 model: str | None = None, cli: str = "opencode",
                 executor_id: str | None = None,
                 stdout_log_path: Path | str | None = None,
                 stderr_log_path: Path | str | None = None):
        self._root = project_root or Path.cwd()
        self._model = model or os.environ.get("GRACE_CONTEXT_MODEL", "deepseek/deepseek-v4-flash")
        # executor_id takes priority over cli for profile lookup in run_llm.
        # This ensures the read-only context-json-flash profile is used instead
        # of the generic coder-like "opencode" profile.
        self._executor_id = executor_id or cli
        self._cli = cli
        self._stdout_log_path = stdout_log_path
        self._stderr_log_path = stderr_log_path

    #START_FUNCTION_CONTRACT
    # name: collect
    # purpose: Collect structured codebase context by scanning files, filtering relevant ones via LLM,
    #          reading their content, and returning a CodebaseContext with analysis.
    # inputs: task_description — task string; target_scope — optional list of path scopes; project_root — optional Path override.
    # returns: CodebaseContext with files, summary, estimated_scope, complexity, relevant content.
    # side_effects: Calls cheap LLM twice (relevance filter + summary).
    # emitted_logs: context_collected on success; context_relevance_failed / context_summarize_failed on errors.
    # error_behavior: Falls back to full-scope without content on LLM failure.
    #END_FUNCTION_CONTRACT
    async def collect(
        self,
        task_description: str,
        target_scope: list[str] | None = None,
        project_root: Path | None = None,
    ) -> CodebaseContext:
        root = project_root or self._root
        scope = target_scope or _default_context_scopes(root)

        files = _scan_files(root, scope)
        _log.debug("context_scan_done", file_count=len(files))

        # Keep explicit offline/test mode deterministic.  The API test and
        # local recovery harnesses set this flag when no LLM subprocess should
        # be started; the static fallback still supplies complete file scope.
        runner = getattr(self._run_llm, "__func__", self._run_llm)
        offline_requested = os.environ.get("GRACE_CONTEXT_DISABLED", "").lower() in {
            "1", "true", "yes", "on"
        }
        if offline_requested and getattr(runner, "__module__", __name__) == __name__:
            context = self._fallback_analysis(task_description, files, scope)
            _log.info("context_collection_disabled", file_count=len(files))
            return context

        relevant_paths = []
        try:
            relevant_paths = await self._filter_relevant(task_description, files)
            _log.info("context_relevance_done", total=len(files), relevant=len(relevant_paths))
        except Exception as e:
            _log.warn("context_relevance_failed", error=str(e)[:120])
            relevant_paths = [f.path for f in files[:_MAX_RELEVANT_FILES]]

        for f in files:
            if f.path in relevant_paths:
                f.relevant = True
                f.content_preview = _read_content(root / f.path)
        _log.debug("context_content_loaded", with_content=sum(1 for f in files if f.content_preview))

        try:
            ctx = await self._summarize(task_description, files)
            _log.info("context_collected",
                file_count=len(files), relevant=len(relevant_paths),
                complexity=ctx.complexity_score)
            return ctx
        except Exception as e:
            _log.warn("context_summarize_failed", error=str(e)[:120])
            return self._fallback_analysis(task_description, files, scope)

    async def _filter_relevant(self, task: str, files: list[FileContext]) -> list[str]:
        if len(files) <= _MAX_RELEVANT_FILES:
            return [f.path for f in files]

        file_list = "\n".join(f"{f.path} ({f.size_lines}L) exports={f.exports[:5]}"
                             for f in files[:80])
        if len(files) > 80:
            file_list += f"\n... ({len(files)} files total)"

        prompt = f"""Task: {task[:500]}

Which of these files are MOST RELEVANT to the task? Pick up to {_MAX_RELEVANT_FILES}.
Respond ONLY with a JSON array of file paths: ["path/to/file1.py", "path/to/file2.html"]

Files:
{file_list}"""

        raw = await self._run_llm(prompt)
        paths = json.loads(raw)
        if isinstance(paths, list):
            return [p for p in paths if isinstance(p, str)][:_MAX_RELEVANT_FILES]
        return [f.path for f in files[:_MAX_RELEVANT_FILES]]

    async def _summarize(self, task: str, files: list[FileContext]) -> CodebaseContext:
        relevant = [f for f in files if f.relevant]
        blocks = []
        for f in relevant[:12]:
            blocks.append(f"### {f.path} ({f.size_lines}L)\n{f.content_preview or '(empty)'}\n")

        file_text = "\n".join(blocks)[:7000]
        prompt = f"""Task: {task[:800]}

Relevant code files with content:
{file_text}

Respond ONLY with valid JSON:
{{
  "summary": "<2-3 sentence summary of what needs to change and how>",
  "estimated_scope": ["path/to/file1.py", "path/to/file2.py"],
  "affected_contracts": ["MODULE_CONTRACT names", "or empty list"],
  "complexity_score": 0-300
}}
Complexity: 0-50 (config), 51-150 (single module), 151-250 (multi-module), 251-300 (architectural)."""

        raw = await self._run_llm(prompt)
        data = json.loads(raw)

        return CodebaseContext(
            files=files,
            summary=data.get("summary", ""),
            estimated_scope=data.get("estimated_scope", []),
            affected_contracts=data.get("affected_contracts", []),
            complexity_score=data.get("complexity_score", 150),
        )

    async def _run_llm(self, prompt: str) -> str:
        from grace_control.core.llm_runner import run_llm
        session_dir = Path(self._stdout_log_path).parent if self._stdout_log_path else None
        return await run_llm(prompt, role="context_collector", model=self._model, cli=self._executor_id, cwd=self._root,
                             session_dir=session_dir,
                             stdout_log_path=self._stdout_log_path, stderr_log_path=self._stderr_log_path)

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
            complexity_score=200,
        )

#END_BLOCK_COLLECTOR

#START_BLOCK_HELPERS

_CODE_EXTS = {".py", ".html", ".js", ".css", ".json", ".yaml", ".yml", ".md"}
_MAX_CONTENT_LINES = 120
_MAX_CONTENT_CHARS = 3000


#START_FUNCTION_CONTRACT
# name: _default_context_scopes
# purpose: Select existing common project roots for read-only context discovery.
# inputs: root — target repository root.
# returns: Existing repository-relative directory/file scopes.
# side_effects: Checks filesystem paths.
# emitted_logs: None.
# error_behavior: Returns an empty list when no common project roots exist.
#END_FUNCTION_CONTRACT
def _default_context_scopes(root: Path) -> list[str]:
    scopes: list[str] = []
    for candidate in _DEFAULT_SCOPE_CANDIDATES:
        try:
            if (root / candidate).exists():
                scopes.append(candidate)
        except OSError:
            continue
    return scopes


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


def _read_content(filepath: Path) -> str:
    try:
        text = filepath.read_text()
        lines = text.split("\n")
        preview = "\n".join(lines[:_MAX_CONTENT_LINES])
        if len(preview) > _MAX_CONTENT_CHARS:
            preview = preview[:_MAX_CONTENT_CHARS] + "\n... [truncated]"
        if len(lines) > _MAX_CONTENT_LINES:
            preview += f"\n... ({len(lines)} lines total)"
        return preview
    except Exception:
        return ""


def _extract_module_contract(text: str) -> str | None:
    m = re.search(r"# START_MODULE_CONTRACT\s*\n(.*?)\n# END_MODULE_CONTRACT", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_exports(text: str) -> list[str]:
    exports = []
    for m in re.finditer(r"^(?:async )?def (\w+)", text, re.MULTILINE):
        if not m.group(1).startswith("_"):
            exports.append(m.group(1))
    for m in re.finditer(r"^class (\w+)", text, re.MULTILINE):
        exports.append(m.group(1))
    return exports


def _extract_json_block(text: str) -> str:
    m = re.search(r"\{[\s\S]*\}", text)
    return m.group(0) if m else text

#END_BLOCK_HELPERS
