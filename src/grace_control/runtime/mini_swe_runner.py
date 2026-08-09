# ############################################################################
# AI_HEADER: mini_swe_runner -- GRACE wrapper around mini-swe-agent CLI
# ROLE: Runs mini-swe-agent as a lightweight non-interactive agent harness for
#       GRACE profiles, while preserving GRACE stdout JSON contracts.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Build a role-specific task prompt, inject target-worktree AGENTS.md,
#          run the mini-swe-agent CLI, and emit a compact JSON result to stdout.
# inputs: CLI args: role, model, task-file, worktree, optional output-dir.
# returns: Process exit code; stdout contains only the role JSON contract.
# side_effects: Spawns mini-swe-agent CLI; writes trajectory files under /tmp or
#               the requested output directory.
# emitted_logs: mini_swe_start, mini_swe_done, mini_swe_json_missing.
# error_behavior: Non-coder roles fail closed when no JSON can be extracted;
#                 coder returns deterministic status JSON from git status.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: main
#   - function: build_prompt
#   - function: run_mini
#   - function: extract_json
#   - function: extract_json_from_trajectory
#   - function: normalize_reasoning_effort
# END_MODULE_MAP

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("mini_swe_runner")

MAX_AGENTS_MD_CHARS = 24000
MAX_STDERR_CHARS = 1200
MAX_RESULT_JSON_CHARS = 1_000_000
DEFAULT_OPENAI_COMPAT_BASE_URL = "http://127.0.0.1:18317/v1"
DEFAULT_DEEPSEEK_OPENAI_COMPAT_BASE_URL = "https://api.deepseek.com/v1"
RESULT_JSON_FILENAME = "grace-mini-swe-result.json"
REASONING_EFFORT_VALUES = {"minimal", "low", "medium", "high", "xhigh", "max"}


ROLE_CONTRACTS: dict[str, str] = {
    "coder": """You are the GRACE Coder.
- Modify files only inside the current worktree.
- Read the task packet and implement it.
- Follow all project instructions and GRACE canon instructions in the packet.
- After finishing, your final answer should be valid JSON, but the wrapper will
  also compute the changed_files list deterministically from git status.""",
    "architect": """You are the GRACE Architect.
- Do not modify files.
- Read the business task, repository context, and project instructions.
- Produce exactly one valid JSON object as your role result.
- Follow the canonical architect output envelope from the task prompt.
- The top-level object must contain a waves array. Each coder packet inside a
  wave must use the exact packet fields and types from the prompt: title, role,
  scope, frozen_scope, acceptance_profile, depends_on, conflict_keys, description,
  coder_instructions, acceptance_criteria, verification, and expected_evidence.
- Do not flatten a wave plan into a single top-level coder packet.""",
    "reviewer": """You are the GRACE Reviewer.
- Do not modify files.
- Review the task, changed files, acceptance evidence, and verifier report.
- Produce exactly one valid JSON object as your role result.
- Shape: {"verdict":"PASS|REWORK_TO_CODER|RETURN_TO_ARCHITECT","summary":"short",
  "risks":[],"required_changes":[],"architect_questions":[],
  "suggested_next_owner":"coder|architect|reviewer"}.""",
    "verifier": """You are the GRACE Evidence Verifier.
- Do not modify files.
- Check whether the acceptance evidence proves the packet contract.
- Produce exactly one valid JSON object as your role result.
- Shape: {"verdict":"PASS|REWORK_TO_CODER|RETURN_TO_ARCHITECT","summary":"short",
  "missing_evidence":[],"failed_checks":[],"spec_conflicts":[],
  "coder_instructions":[],"architect_questions":[],
  "suggested_next_owner":"coder|architect|verifier"}.""",
    "context_collector": """You are the GRACE read-only context collector.
- Do not create, edit, delete, move, format, or commit files.
- Do not implement, fix, refactor, or update repository code.
- Do not run git checkout, git switch, git reset, git clean, or git worktree mutations.
- Read only the supplied task and repository files needed for that task.
- Produce only the JSON array or JSON object shape explicitly requested by the
  task prompt, with no prose or markdown fences.""",
}


# START_BLOCK_PROMPT
# START_FUNCTION_CONTRACT
# name: read_text_limited
# purpose: Read text from disk with a maximum character budget.
# inputs: path -- file path; limit -- maximum returned chars.
# returns: File text or an empty string when unavailable.
# side_effects: Reads a file.
# emitted_logs: None.
# error_behavior: Returns empty string on read failure.
# END_FUNCTION_CONTRACT
def read_text_limited(path: Path, limit: int) -> str:
    try:
        text = path.read_text(errors="replace")
    except Exception:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[TRUNCATED: AGENTS.md exceeded wrapper limit]\n"


# START_FUNCTION_CONTRACT
# name: build_prompt
# purpose: Compose the prompt given to mini-swe-agent, including AGENTS.md.
# inputs: role -- GRACE role; task -- packet/prompt text; worktree -- target repo;
#         result_path -- optional out-of-worktree JSON result file.
# returns: Prompt string.
# side_effects: Reads worktree/AGENTS.md when present.
# emitted_logs: None.
# error_behavior: Missing AGENTS.md is represented explicitly in the prompt.
# END_FUNCTION_CONTRACT
def build_prompt(role: str, task: str, worktree: Path, result_path: Path | None = None) -> str:
    role_key = role.strip().lower()
    role_contract = ROLE_CONTRACTS.get(role_key, ROLE_CONTRACTS["coder"])
    agents_md_path = worktree / "AGENTS.md"
    agents_md = read_text_limited(agents_md_path, MAX_AGENTS_MD_CHARS)
    if agents_md.strip():
        agents_block = (
            "PROJECT INSTRUCTIONS FROM TARGET WORKTREE AGENTS.md:\n"
            f"{agents_md.strip()}\n"
            "END PROJECT INSTRUCTIONS\n"
        )
    else:
        agents_block = "PROJECT INSTRUCTIONS FROM TARGET WORKTREE AGENTS.md: not found.\n"

    sections = [
        "You are running under GRACE Orchestrator through mini-swe-agent.",
        f"GRACE role: {role_key}",
        f"Target worktree: {worktree}",
        agents_block,
        "ROLE CONTRACT:\n" + role_contract,
        "TASK PACKET / LLM PROMPT:\n" + task.strip(),
        "\n".join([
            "EXECUTION BOUNDARY (highest priority):",
            f"The only writable repository for this run is the current worktree: {worktree}",
            "Any target_repo_root or project root elsewhere in the task packet is the read-only merge destination, not your workspace.",
            "Never create, edit, delete, move, format, stage, or commit files in that merge destination.",
            "Run repository-relative commands from the current worktree and change only paths inside it.",
        ]),
    ]
    if role_key != "coder" and result_path is not None:
        sections.append(
            "\n".join([
                "MINI-SWE NON-INTERACTIVE OUTPUT CONTRACT:",
                "Every assistant turn must include a bash tool call.",
                "Do not write role-result files into the target worktree.",
                f"Write the final valid role JSON to this absolute file outside the worktree: {result_path}",
                "After writing that file, finish with this exact command: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT",
            ])
        )

    return "\n\n".join(sections).strip()


# END_BLOCK_PROMPT


# START_BLOCK_MINI
# START_FUNCTION_CONTRACT
# name: configure_openai_compatible_env
# purpose: Configure LiteLLM/OpenAI-compatible env vars for local CPA proxy.
# inputs: model -- resolved LiteLLM model name.
# returns: None.
# side_effects: Sets process env defaults consumed by mini-swe-agent/LiteLLM.
# emitted_logs: None.
# error_behavior: Existing explicit env values win except DeepSeek direct routing,
#                 where the model-specific base/key override generic OPENAI vars.
# END_FUNCTION_CONTRACT
def configure_openai_compatible_env(model: str = "") -> None:
    os.environ.setdefault("LITELLM_MODE", "PRODUCTION")
    if model.startswith("openai/deepseek-"):
        base_url = (
            os.environ.get("GRACE_MINI_SWE_DEEPSEEK_BASE_URL")
            or os.environ.get("DEEPSEEK_BASE_URL")
            or DEFAULT_DEEPSEEK_OPENAI_COMPAT_BASE_URL
        )
        api_key = (
            os.environ.get("GRACE_MINI_SWE_DEEPSEEK_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        )
        os.environ["OPENAI_BASE_URL"] = base_url
        os.environ["OPENAI_API_BASE"] = base_url
        if api_key:
            os.environ["OPENAI_API_KEY"] = api_key
            os.environ.setdefault("DEEPSEEK_API_KEY", api_key)
        os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")
        os.environ.setdefault("MSWEA_CONFIGURED", "true")
        return

    base_url = (
        os.environ.get("GRACE_MINI_SWE_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or DEFAULT_OPENAI_COMPAT_BASE_URL
    )
    api_key = os.environ.get("GRACE_MINI_SWE_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") or "dummy"
    os.environ.setdefault("OPENAI_BASE_URL", base_url)
    os.environ.setdefault("OPENAI_API_BASE", base_url)
    os.environ.setdefault("OPENAI_API_KEY", api_key)
    os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")
    os.environ.setdefault("MSWEA_CONFIGURED", "true")


# START_FUNCTION_CONTRACT
# name: resolve_model_arg
# purpose: Resolve env-style model arguments passed from agent_profiles.yaml.
# inputs: value -- model argument, possibly ${VAR}, ${VAR:-default}, or $VAR.
# returns: Resolved model name.
# side_effects: Reads os.environ.
# emitted_logs: None.
# error_behavior: Returns original value when no env expansion applies.
# END_FUNCTION_CONTRACT
def resolve_model_arg(value: str) -> str:
    raw = value.strip()
    match = re.fullmatch(r"\$\{([A-Z0-9_]+)(?::-([^}]+))?\}", raw)
    if match:
        env_name, default = match.groups()
        return os.environ.get(env_name, default or raw)
    match = re.fullmatch(r"\$([A-Z0-9_]+)", raw)
    if match:
        return os.environ.get(match.group(1), raw)
    return raw


# START_FUNCTION_CONTRACT
# name: normalize_reasoning_effort
# purpose: Normalize optional reasoning effort profile values for GPT models.
# inputs: value -- raw effort string.
# returns: Supported effort string or empty string when unset/unsupported.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unknown values are dropped instead of sent to model APIs.
# END_FUNCTION_CONTRACT
def normalize_reasoning_effort(value: str) -> str:
    effort = value.strip().lower()
    return effort if effort in REASONING_EFFORT_VALUES else ""


# START_FUNCTION_CONTRACT
# name: model_supports_reasoning_effort
# purpose: Decide whether to pass reasoningEffort to the OpenAI-compatible API.
# inputs: model -- resolved LiteLLM model name.
# returns: True for GPT models on the local CPA endpoint.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Conservative false for unknown providers/models.
# END_FUNCTION_CONTRACT
def model_supports_reasoning_effort(model: str) -> bool:
    return model.startswith("openai/gpt-")


# START_FUNCTION_CONTRACT
# name: resolve_mini_binary
# purpose: Resolve mini executable from env, current/source venv, user bin, or PATH.
# inputs: binary -- configured executable name/path.
# returns: Executable path/name to pass to subprocess.
# side_effects: Checks filesystem and PATH.
# emitted_logs: None.
# error_behavior: Returns original binary if no better candidate exists.
# END_FUNCTION_CONTRACT
def resolve_mini_binary(binary: str) -> str:
    configured = binary.strip() or "mini"
    configured_path = Path(configured).expanduser()
    configured_name = configured_path.name if configured_path.is_absolute() else configured
    try:
        if configured_path.is_absolute() and configured_path.is_file() and os.access(configured_path, os.X_OK):
            return str(configured_path)
        if "/" in configured and configured_path.is_file() and os.access(configured_path, os.X_OK):
            return str(configured_path)
    except OSError:
        pass

    candidates = [
        Path(sys.executable).parent / configured_name,
        Path(sys.executable).resolve().parent / configured_name,
        Path(os.environ.get("VIRTUAL_ENV", "/nonexistent")) / "bin" / configured_name,
        Path(os.environ.get("GRACE_SOURCE_DIR", "/nonexistent")) / ".venv" / "bin" / configured_name,
        Path.home() / ".local" / "bin" / configured_name,
        Path("/usr/local/bin") / configured_name,
        Path("/usr/bin") / configured_name,
    ]
    for candidate in candidates:
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue

    found = shutil.which(configured_name)
    return found or configured


# START_FUNCTION_CONTRACT
# name: mini_help
# purpose: Get mini CLI help text for best-effort option detection.
# inputs: binary -- mini executable name/path.
# returns: Help text.
# side_effects: Spawns mini --help.
# emitted_logs: None.
# error_behavior: Returns empty string on failure.
# END_FUNCTION_CONTRACT
def mini_help(binary: str) -> str:
    try:
        result = subprocess.run(
            [binary, "--help"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return ""
    return f"{result.stdout}\n{result.stderr}"


# START_FUNCTION_CONTRACT
# name: build_mini_command
# purpose: Build a mini CLI command compatible with common mini-swe versions.
# inputs: binary, model, prompt, output_path, reasoning_effort.
# returns: argv list.
# side_effects: Reads GRACE_MINI_SWE_EXTRA_ARGS.
# emitted_logs: None.
# error_behavior: Falls back to documented short flags when help is unavailable.
# END_FUNCTION_CONTRACT
def build_mini_command(
    binary: str,
    model: str,
    prompt: str,
    output_path: Path,
    reasoning_effort: str = "",
) -> list[str]:
    help_text = mini_help(binary)
    cmd = [binary]
    cmd.extend(["-m", model] if "-m" in help_text or "--model" not in help_text else ["--model", model])
    cmd.extend(["-t", prompt] if "-t" in help_text or "--task" not in help_text else ["--task", prompt])
    if "-y" in help_text or "--yes" in help_text:
        cmd.append("-y")
    if "--exit-immediately" in help_text:
        cmd.append("--exit-immediately")
    if "-o" in help_text:
        cmd.extend(["-o", str(output_path)])
    elif "--output" in help_text:
        cmd.extend(["--output", str(output_path)])

    effort = normalize_reasoning_effort(reasoning_effort)
    if effort and model_supports_reasoning_effort(model) and ("-c" in help_text or "--config" in help_text):
        cmd.extend(["-c", "mini.yaml", "-c", f"model.model_kwargs.reasoningEffort={effort}"])

    extra_args = os.environ.get("GRACE_MINI_SWE_EXTRA_ARGS", "").strip()
    if extra_args:
        cmd.extend(shlex.split(extra_args))
    return cmd


# START_FUNCTION_CONTRACT
# name: run_mini
# purpose: Run mini-swe-agent in the target worktree.
# inputs: binary, model, prompt, worktree, output_dir, timeout, reasoning_effort.
# returns: CompletedProcess-compatible result from the mini subprocess.
# side_effects: Spawns mini; streams stdout/stderr to run-dir logs; writes trajectory.
# emitted_logs: mini_swe_start, mini_swe_done.
# error_behavior: FileNotFoundError is converted into an exit-127 process shape.
# END_FUNCTION_CONTRACT
def run_mini(
    *,
    binary: str,
    model: str,
    prompt: str,
    worktree: Path,
    output_dir: Path,
    timeout_seconds: int,
    reasoning_effort: str = "",
) -> subprocess.CompletedProcess[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "mini-swe.traj.json"
    binary = resolve_mini_binary(binary)
    command = build_mini_command(binary, model, prompt, output_path, reasoning_effort)
    _log.info("mini_swe_start", binary=binary, model=model, cwd=str(worktree), reasoning_effort=reasoning_effort)
    stdout_path = output_dir / "mini-swe.stdout.log"
    stderr_path = output_dir / "mini-swe.stderr.log"
    try:
        with stdout_path.open("w") as stdout_file, stderr_path.open("w") as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=str(worktree),
                stdout=stdout_file,
                stderr=stderr_file,
                text=True,
            )
            try:
                return_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
                return_code = 124
        result = subprocess.CompletedProcess(
            args=command,
            returncode=return_code,
            stdout=stdout_path.read_text(errors="replace"),
            stderr=stderr_path.read_text(errors="replace"),
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            args=[binary],
            returncode=127,
            stdout="",
            stderr=f"mini-swe binary not found: {binary}",
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=command,
            returncode=124,
            stdout=e.stdout if isinstance(e.stdout, str) else "",
            stderr=e.stderr if isinstance(e.stderr, str) else f"mini-swe timed out after {timeout_seconds}s",
        )
    _log.info("mini_swe_done", exit_code=result.returncode)
    return result


# END_BLOCK_MINI


# START_BLOCK_JSON
# START_FUNCTION_CONTRACT
# name: is_command_only_json
# purpose: Detect mini-swe tool-call examples that are not GRACE role results.
# inputs: value -- parsed JSON candidate.
# returns: True when the candidate is only a bash command envelope.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Non-dict values are treated as role candidates.
# END_FUNCTION_CONTRACT
def is_command_only_json(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {"command"} and isinstance(value.get("command"), str)


# START_FUNCTION_CONTRACT
# name: extract_json
# purpose: Extract the last valid JSON object/array from model output.
# inputs: text -- stdout/stderr text; ignore_command_only -- skip mini command JSON.
# returns: Parsed JSON value or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Ignores malformed JSON candidates.
# END_FUNCTION_CONTRACT
def extract_json(text: str, *, ignore_command_only: bool = False) -> Any | None:
    decoder = json.JSONDecoder()
    found: Any | None = None
    for index, char in enumerate(text):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if ignore_command_only and is_command_only_json(value):
            continue
        found = value
    return found


# START_FUNCTION_CONTRACT
# name: parse_json_text
# purpose: Parse text that should be a single role-result JSON payload.
# inputs: text -- JSON text, optionally wrapped in a markdown code fence.
# returns: Parsed JSON value or None.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Falls back to noisy JSON extraction when whole-text parse fails.
# END_FUNCTION_CONTRACT
def parse_json_text(text: str) -> Any | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
            stripped = "\n".join(lines[1:-1]).strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return extract_json(stripped, ignore_command_only=True)


# START_FUNCTION_CONTRACT
# name: is_role_payload
# purpose: Validate that parsed JSON looks like the expected GRACE role result.
# inputs: role -- GRACE role; value -- parsed JSON candidate.
# returns: True when value should be emitted for the role.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unknown roles are rejected.
# END_FUNCTION_CONTRACT
def is_role_payload(role: str, value: Any) -> bool:
    if is_command_only_json(value):
        return False
    if role == "architect":
        if not isinstance(value, dict):
            return False
        if isinstance(value.get("waves"), list):
            return True
        if isinstance(value.get("packets"), list):
            return True
        required = {"title", "scope", "description", "coder_instructions", "acceptance_criteria"}
        return required.issubset(value)
    if role in ("reviewer", "verifier"):
        return isinstance(value, dict) and isinstance(value.get("verdict"), str) and isinstance(value.get("summary"), str)
    if role == "context_collector":
        return isinstance(value, (dict, list))
    return False


# START_FUNCTION_CONTRACT
# name: read_result_json_file
# purpose: Read the mini-swe role result JSON written outside the worktree.
# inputs: path -- expected result JSON path; role -- GRACE role.
# returns: Parsed JSON value or None.
# side_effects: Reads a file.
# emitted_logs: None.
# error_behavior: Missing, oversized, or invalid files return None.
# END_FUNCTION_CONTRACT
def read_result_json_file(path: Path, role: str) -> Any | None:
    try:
        if not path.exists() or path.stat().st_size > MAX_RESULT_JSON_CHARS:
            return None
        text = path.read_text(errors="replace")
    except Exception:
        return None
    value = parse_json_text(text)
    return value if is_role_payload(role, value) else None


# START_FUNCTION_CONTRACT
# name: wait_for_result_json_file
# purpose: Wait briefly for mini-swe's final shell command to flush result JSON.
# inputs: path -- expected result JSON path; role -- GRACE role.
# returns: Parsed JSON value or None.
# side_effects: Reads a file and sleeps briefly.
# emitted_logs: None.
# error_behavior: Returns None after the short deadline.
# END_FUNCTION_CONTRACT
def wait_for_result_json_file(path: Path, role: str, timeout_seconds: float = 3.0) -> Any | None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        value = read_result_json_file(path, role)
        if value is not None:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.1)


# START_FUNCTION_CONTRACT
# name: message_content_text
# purpose: Convert OpenAI-style message content into plain text safely.
# inputs: content -- message content value from mini-swe trajectory.
# returns: Text content; tool-call arguments are intentionally excluded.
# side_effects: None.
# emitted_logs: None.
# error_behavior: Unknown content shapes return an empty string or string value.
# END_FUNCTION_CONTRACT
def message_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                text = part.get("text") or part.get("content")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks)
    return ""


# START_FUNCTION_CONTRACT
# name: extract_json_from_trajectory
# purpose: Extract role-result JSON only from assistant message text.
# inputs: path -- mini-swe trajectory path; role -- GRACE role.
# returns: Last parsed role JSON candidate or None.
# side_effects: Reads trajectory JSON.
# emitted_logs: None.
# error_behavior: Invalid or missing trajectory returns None.
# END_FUNCTION_CONTRACT
def extract_json_from_trajectory(path: Path, role: str = "") -> Any | None:
    try:
        data = json.loads(path.read_text(errors="replace"))
    except Exception:
        return None
    messages = data.get("messages") if isinstance(data, dict) else None
    if not isinstance(messages, list):
        return None

    found: Any | None = None
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message_content_text(message.get("content"))
        if not content.strip():
            continue
        value = parse_json_text(content)
        if is_role_payload(role, value):
            found = value
    return found


# START_FUNCTION_CONTRACT
# name: changed_files
# purpose: Collect changed files in the worktree after coder execution.
# inputs: worktree -- git worktree path.
# returns: Repo-relative changed paths.
# side_effects: Runs git status.
# emitted_logs: None.
# error_behavior: Returns empty list on git failure.
# END_FUNCTION_CONTRACT
def changed_files(worktree: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return []
    files: list[str] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if path:
            files.append(path)
    return sorted(set(files))


# START_FUNCTION_CONTRACT
# name: fallback_report
# purpose: Produce fail-closed JSON for non-coder roles when mini has no JSON.
# inputs: role, stderr, exit_code.
# returns: JSON-serializable dict.
# side_effects: None.
# emitted_logs: mini_swe_json_missing.
# error_behavior: Always returns a conservative report.
# END_FUNCTION_CONTRACT
def fallback_report(role: str, stderr: str, exit_code: int) -> dict[str, Any]:
    reason = (stderr or f"mini-swe exited with code {exit_code}")[:MAX_STDERR_CHARS]
    _log.warn("mini_swe_json_missing", role=role, exit_code=exit_code, stderr=reason)
    if role == "verifier":
        return {
            "verdict": "REWORK_TO_CODER",
            "summary": "mini-swe verifier did not return parseable JSON",
            "missing_evidence": [],
            "failed_checks": [reason],
            "spec_conflicts": [],
            "coder_instructions": ["Rerun verifier or inspect mini-swe logs."],
            "architect_questions": [],
            "suggested_next_owner": "verifier",
        }
    if role == "reviewer":
        return {
            "verdict": "REWORK_TO_CODER",
            "summary": "mini-swe reviewer did not return parseable JSON",
            "risks": [reason],
            "required_changes": ["Rerun reviewer or inspect mini-swe logs."],
            "architect_questions": [],
            "suggested_next_owner": "reviewer",
        }
    return {
        "status": "blocked",
        "reason": "mini-swe did not return parseable JSON",
        "missing_context": [reason],
    }


# END_BLOCK_JSON


# START_BLOCK_MAIN
# START_FUNCTION_CONTRACT
# name: parse_args
# purpose: Parse command-line arguments.
# inputs: argv -- optional argv list.
# returns: argparse.Namespace.
# side_effects: None.
# emitted_logs: None.
# error_behavior: argparse exits on invalid input.
# END_FUNCTION_CONTRACT
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run mini-swe-agent for GRACE profiles.")
    parser.add_argument("--role", choices=sorted(ROLE_CONTRACTS), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--task-file", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--mini-binary", default=os.environ.get("GRACE_MINI_SWE_BINARY", "mini"))
    parser.add_argument("--reasoning-effort", default="")
    return parser.parse_args(argv)


# START_FUNCTION_CONTRACT
# name: main
# purpose: CLI entry point used by agent_profiles.yaml mini-swe profiles.
# inputs: argv -- optional argv list.
# returns: Process exit code.
# side_effects: Runs mini-swe and writes JSON to stdout.
# emitted_logs: mini_swe_start, mini_swe_done.
# error_behavior: Returns non-zero for missing task/worktree or architect JSON failure.
# END_FUNCTION_CONTRACT
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    role = args.role.lower()
    resolved_model = resolve_model_arg(args.model)
    configure_openai_compatible_env(resolved_model)
    worktree = Path(args.worktree).resolve()
    task_file = Path(args.task_file)
    if not worktree.exists():
        sys.stderr.write(f"worktree does not exist: {worktree}\n")
        return 2
    if not task_file.exists():
        sys.stderr.write(f"task file does not exist: {task_file}\n")
        return 2

    if args.output_dir:
        output_dir = Path(args.output_dir)
    elif os.environ.get("GRACE_AGENT_RUN_DIR"):
        output_dir = Path(os.environ["GRACE_AGENT_RUN_DIR"])
    else:
        output_dir = Path(tempfile.mkdtemp(prefix="grace-mini-swe-"))
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / RESULT_JSON_FILENAME

    task = task_file.read_text(errors="replace")
    prompt = build_prompt(role, task, worktree, result_path=result_path)
    mini_timeout_seconds = args.timeout_seconds
    try:
        configured_max = int(os.environ.get("GRACE_AGENT_MAX_TIMEOUT", "3600"))
    except ValueError:
        configured_max = 0
    if configured_max > 0:
        mini_timeout_seconds = max(mini_timeout_seconds, configured_max)
    result = run_mini(
        binary=args.mini_binary,
        model=resolved_model,
        prompt=prompt,
        worktree=worktree,
        output_dir=output_dir,
        timeout_seconds=mini_timeout_seconds,
        reasoning_effort=args.reasoning_effort,
    )

    if role == "coder":
        if result.returncode == 0:
            payload = {
                "status": "done",
                "changed_files": changed_files(worktree),
                "summary": "mini-swe coder completed",
                "verification": [],
            }
        else:
            payload = {
                "status": "blocked",
                "reason": (result.stderr or "mini-swe coder failed")[:MAX_STDERR_CHARS],
                "missing_context": [],
            }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return result.returncode

    trajectory_path = output_dir / "mini-swe.traj.json"
    parsed = wait_for_result_json_file(result_path, role) or extract_json_from_trajectory(trajectory_path, role)
    if parsed is not None:
        sys.stdout.write(json.dumps(parsed, ensure_ascii=False) + "\n")
        return 0

    payload = fallback_report(role, result.stderr or result.stdout, result.returncode)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    if role in ("reviewer", "verifier"):
        return 0
    return result.returncode if result.returncode else 1


if __name__ == "__main__":
    raise SystemExit(main())

# END_BLOCK_MAIN
