# ############################################################################
# AI_HEADER: telegram_bridge_service
# ROLE: Real Telegram WebApp bridge — ngrok + signed initData for STRICT+real.
#       TZ_FRONTEND_ACCEPTANCE P1.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Provide a real Telegram WebApp bridge for STRICT acceptance.
#          Starts ngrok tunnel, generates signed initData via bot token,
#          and provides URL/script injection for Playwright.
# inputs: worktree_path (Path), dev_port (int), bot_token_env (str).
# returns: BridgeResult with public_url, init_script_path, ngrok_pid.
# side_effects: Spawns ngrok subprocess, writes init-script.html to worktree.
# emitted_logs: ngrok_started, initdata_generated, bridge_ready, bridge_stopped.
# error_behavior: ngrok failure → BridgeResult with error (caller falls back to mock).
#                  Missing bot token → BridgeResult with error.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - class: TelegramBridgeService
#   - dataclass: BridgeResult
# END_MODULE_MAP

from __future__ import annotations

import hashlib
import hmac
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("telegram_bridge")

_NGROK_TIMEOUT = 30


@dataclass
class BridgeResult:
    """Result of starting a Telegram bridge (ngrok + signed initData)."""
    ok: bool = False
    public_url: str = ""
    ngrok_pid: int = 0
    init_script_path: str = ""
    error: str = ""


class TelegramBridgeService:
    """Real Telegram WebApp bridge: ngrok + HMAC-signed initData."""

    def __init__(
        self,
        worktree_path: Path,
        dev_port: int = 3000,
        bot_token_env: str = "",
    ) -> None:
        self._worktree = Path(worktree_path)
        self._dev_port = dev_port
        self._bot_token_env = bot_token_env
        self._ngrok_proc: subprocess.Popen | None = None

    def start(self, bot_token: str = "") -> BridgeResult:
        """Start the bridge: ngrok tunnel + signed initData script."""
        token = bot_token or os.environ.get(self._bot_token_env, "")
        if not token:
            return BridgeResult(error="TELEGRAM_BOT_TOKEN not set — real mode disabled")

        # Start ngrok
        ngrok_ok, public_url = self._start_ngrok()
        if not ngrok_ok or not public_url:
            return BridgeResult(error="ngrok failed to start")

        # Generate signed initData
        init_script = self._generate_init_script(token, public_url)

        result = BridgeResult(
            ok=True,
            public_url=public_url,
            ngrok_pid=self._ngrok_proc.pid if self._ngrok_proc else 0,
            init_script_path=str(init_script),
        )
        _log.info("bridge_ready", public_url=public_url, dev_port=self._dev_port)
        return result

    def stop(self) -> None:
        """Kill ngrok process if running."""
        if self._ngrok_proc and self._ngrok_proc.poll() is None:
            try:
                os.killpg(os.getpgid(self._ngrok_proc.pid), signal.SIGTERM)
                self._ngrok_proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(os.getpgid(self._ngrok_proc.pid), signal.SIGKILL)
                except Exception:
                    pass
            _log.info("bridge_stopped")

    # ── internals ───────────────────────────────────────────────────────

    def _start_ngrok(self) -> tuple[bool, str]:
        """Start ngrok and extract the public HTTPS URL from its API."""
        try:
            self._ngrok_proc = subprocess.Popen(
                ["ngrok", "http", str(self._dev_port), "--log=stdout"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                preexec_fn=os.setsid,
            )
        except FileNotFoundError:
            _log.warn("ngrok_not_found", reason="ngrok not installed")
            return False, ""
        except Exception as e:
            _log.error("ngrok_start_failed", error=str(e)[:200])
            return False, ""

        # Poll ngrok API for public URL
        deadline = time.time() + _NGROK_TIMEOUT
        while time.time() < deadline:
            time.sleep(0.5)
            try:
                import urllib.request
                resp = urllib.request.urlopen(
                    "http://127.0.0.1:4040/api/tunnels", timeout=2
                )
                data = json.loads(resp.read())
                for tunnel in data.get("tunnels", []):
                    if tunnel.get("proto") == "https":
                        url = tunnel.get("public_url", "")
                        if url:
                            _log.info("ngrok_started", url=url)
                            return True, url
            except Exception:
                pass

        return False, ""

    def _generate_init_script(self, bot_token: str, public_url: str) -> Path:
        """Generate HTML init script with signed initData for Playwright injection."""
        # Build initData query string
        auth_date = int(time.time())
        user_data = {
            "id": 123456789,
            "first_name": "Test",
            "last_name": "Bot",
            "username": "test_user",
            "language_code": "en",
        }
        init_data = {
            "query_id": "test_query_123",
            "user": json.dumps(user_data),
            "auth_date": str(auth_date),
            "hash": "",
        }

        # HMAC-SHA256 signing per Telegram spec
        check_string = "&".join(
            f"{k}={v}" for k, v in sorted(init_data.items()) if k != "hash"
        )
        secret = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        init_data["hash"] = hmac.new(
            secret, check_string.encode(), hashlib.sha256
        ).hexdigest()

        init_query = urlencode(init_data)

        script = self._worktree / "telegram-real-init.html"
        script.write_text(f"""<!-- TZ_FRONTEND_ACCEPTANCE P1 — Real Telegram initData -->
<script>
window.Telegram = {{ WebApp: {{
  initData: "{init_query}",
  initDataUnsafe: {{
    query_id: "test_query_123",
    user: {{ id: 123, first_name: "Test", last_name: "Bot" }},
    auth_date: {auth_date},
    hash: "{init_data['hash']}",
  }},
  platform: "web",
  version: "7.0",
  ready: function() {{}},
  expand: function() {{}},
  close: function() {{}},
  viewportHeight: 780,
  isExpanded: true,
  MainButton: {{ setText(){{}}, show(){{}}, hide(){{}}, onClick(){{}}, offClick(){{}} }},
  BackButton: {{ show(){{}}, hide(){{}}, onClick(){{}}, offClick(){{}} }},
  HapticFeedback: {{ impactOccurred(){{}}, notificationOccurred(){{}}, selectionChanged(){{}} }},
}} }};
</script>
""")

        _log.info("initdata_generated", path=str(script))
        return script
