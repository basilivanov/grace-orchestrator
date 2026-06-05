# AI_HEADER: command_template_renderer — renders {model}/{effort}/{packet_id}/{worktree_path}/{state_root}
# START_MODULE_CONTRACT
# purpose: Substitutes template variables in agent command templates.
#          No knowledge of specific CLI tools (opencode, codex, agy, etc.).
# inputs: command list with {placeholders}, context dict.
# returns: list[str] with placeholders replaced.
# side_effects: None.
# error_behavior: Returns partial render if unknown keys; never raises.
# END_MODULE_CONTRACT
# START_MODULE_MAP
# mapping:   - class: CommandTemplateRenderer
# END_MODULE_MAP

from __future__ import annotations
from pathlib import Path


class CommandTemplateRenderer:
    KNOWN_KEYS = {"model", "effort", "packet_id", "worktree_path", "state_root", "role", "attempt"}

    def render(self, command: list[str], ctx: dict) -> list[str]:
        result = []
        for part in command:
            rendered = part
            for key in self.KNOWN_KEYS:
                val = ctx.get(key, "")
                if isinstance(val, Path):
                    val = str(val)
                rendered = rendered.replace(f"{{{key}}}", val)
            result.append(rendered)
        return result
