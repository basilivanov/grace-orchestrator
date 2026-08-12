"""
Playwright E2E test: Admin → New Feature → submit → verify no 405.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests


PORT = 19050
pytestmark = pytest.mark.external


@pytest.fixture(scope="module")
def server(request) -> str:
    db_path = Path("/tmp") / f"grace_e2e_{PORT}.db"
    if db_path.exists():
        db_path.unlink()
    env = os.environ.copy()
    env["GRACE_DB_URL"] = f"sqlite:///{db_path}"
    env["GRACE_CONTEXT_DISABLED"] = "true"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "grace_control.api.main:app",
         "--host", "127.0.0.1", "--port", str(PORT),
         "--log-level", "error"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{PORT}"
    for _ in range(30):
        try:
            r = requests.get(f"{base_url}/health", timeout=2)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.3)
    else:
        proc.kill()
        pytest.fail("Server did not become ready")

    def _stop():
        proc.kill()
        proc.wait(timeout=5)
        if db_path.exists():
            db_path.unlink()
    request.addfinalizer(_stop)
    return base_url


@pytest.mark.usefixtures("server")
def test_admin_submit_auto_mode(page):
    """Default (auto-approve checked) → submit → 200, no error."""
    page.goto(f"http://127.0.0.1:{PORT}/admin.html")
    page.wait_for_load_state("networkidle")

    # Click "New Feature"
    page.locator("text=New Feature").first.click()
    page.wait_for_timeout(300)

    # Verify form elements
    assert page.is_visible("#biz-input"), "textarea missing"
    assert page.is_visible("text=Auto-approve architect plan"), "checkbox label missing"
    cb = page.locator("#biz-auto-approve")
    assert cb.is_checked(), "checkbox should be checked by default"

    with page.expect_response(lambda r: "/api/features" in r.url and r.request.method == "POST") as resp_info:
        page.fill("#biz-input", "Add a dark mode toggle to the admin panel")
        page.click("#biz-btn")
    resp = resp_info.value
    assert resp.status == 200, f"POST returned {resp.status}, body: {resp.text()[:200]}"

    # UI should show success
    page.wait_for_timeout(500)
    status = page.text_content("#biz-status") or ""
    assert "Error" not in status, f"UI error: {status}"


@pytest.mark.usefixtures("server")
def test_admin_submit_manual_mode(page):
    """Uncheck auto-approve → submit → 200, manual mode sent."""
    page.goto(f"http://127.0.0.1:{PORT}/admin.html")
    page.wait_for_load_state("networkidle")

    page.locator("text=New Feature").first.click()
    page.wait_for_timeout(300)

    page.uncheck("#biz-auto-approve")
    assert not page.locator("#biz-auto-approve").is_checked()

    with page.expect_response(lambda r: "/api/features" in r.url and r.request.method == "POST") as resp_info:
        page.fill("#biz-input", "Refactor the notification system")
        page.click("#biz-btn")
    resp = resp_info.value
    assert resp.status == 200, f"POST returned {resp.status}, body: {resp.text()[:200]}"
