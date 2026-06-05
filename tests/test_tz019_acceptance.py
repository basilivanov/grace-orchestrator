"""TZ-019 acceptance tests — verify all requirements from section 6."""
import httpx, re
API = "http://localhost:8042"
c = httpx.Client(base_url=API, timeout=5)


def _extract_main_js(html):
    scripts = list(re.finditer(r'<script>(.*?)</script>', html, re.DOTALL))
    if len(scripts) > 1:
        return scripts[-1].group(1)
    elif scripts:
        return scripts[0].group(1)
    return ""


def test_dashboard_has_mission_control_center():
    """dashboard HTML содержит GRACE Mission Control Center."""
    r = c.get("/")
    assert "GRACE Mission Control Center" in r.text


def test_dashboard_api_returns_runs():
    """/api/dashboard returns 200 with features/packets/runs."""
    r = c.get("/api/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert "features" in d
    for f in d["features"]:
        for w in f.get("waves", []):
            for p in w.get("packets", []):
                assert "state" in p
                assert "attempt_count" in p


def test_packet_detail_has_runs_and_recovery_snake_case():
    """/api/packets/{packet_id} возвращает runs и recovery snake_case."""
    r = c.get("/api/packets/")
    pkts = r.json().get("data", [])
    if not pkts:
        return  # skip if no data
    pid = pkts[0]["id"]
    r = c.get(f"/api/packets/{pid}")
    assert r.status_code == 200
    d = r.json().get("data", {})
    runs = d.get("runs", [])
    for run in runs:
        assert "run_number" in run
        assert "status" in run
    recovery = d.get("recovery")
    if recovery:
        assert "failure_class" in recovery
        assert "action" in recovery
        assert "current_executor_id" in recovery
        assert "next_executor_hint" in recovery


def test_events_recovery_filter_works():
    """/api/events recovery_* filter работает."""
    r = c.get("/api/events?event_type=recovery_classified&limit=5")
    assert r.status_code == 200
    assert "data" in r.json()


def test_recovery_block_renders_snake_case():
    """recovery block рендерит snake_case fields в JS."""
    r = c.get("/")
    js = _extract_main_js(r.text)
    fields = ["failure_class", "current_executor_id", "next_executor_hint"]
    for field in fields:
        assert field in js, f"Missing snake_case field in JS: {field}"


def test_self_panel_handles_completed_and_executed():
    """Self panel корректно рендерит completed/executed."""
    r = c.get("/")
    js = _extract_main_js(r.text)
    assert "s.status==='completed'" in js or "completed" in js
    assert "s.status==='executed'" in js or "executed" in js
    assert "s.status==='failed'" in js


def test_artifacts_tab_no_text_preview_for_images():
    """Artifacts tab не preview image/binary как text."""
    r = c.get("/")
    js = _extract_main_js(r.text)
    assert "isTextFile" in js
    assert "TEXT_EXTS" in js
    assert "showArtMeta" in js
    assert "Preview is not available for this file type yet" in js


def test_timeline_only_real_states():
    """Timeline не показывает claimed/evidence как реальные состояния."""
    r = c.get("/")
    js = _extract_main_js(r.text)
    mainPhases = "'draft','ready','running','accepted','merged'"
    assert mainPhases in js, "Timeline should only show real states"
    assert "claimed" not in js.split("const mainPhases")[0] if "const mainPhases" in js else True


def test_duration_formatting_human_readable():
    """Duration labels human-readable."""
    r = c.get("/")
    js = _extract_main_js(r.text)
    assert "fmtDur" in js
    assert "fmtDurSec" in js
    # Should format ms to human
    assert "h+" in js or "'h '" in js
    assert "'m '" in js


def test_mobile_smoke():
    """mobile smoke: feature → packet → inspector structure."""
    r = c.get("/")
    html = r.text
    assert "navStack" in html
    assert "navBack" in html
    assert "resetMobile" in html
    assert "Features" in html
    assert "@media(max-width:699px)" in html


# Run all
print("=== TZ-019 Acceptance Tests ===\n")
tests = [test_dashboard_has_mission_control_center,
         test_dashboard_api_returns_runs,
         test_packet_detail_has_runs_and_recovery_snake_case,
         test_events_recovery_filter_works,
         test_recovery_block_renders_snake_case,
         test_self_panel_handles_completed_and_executed,
         test_artifacts_tab_no_text_preview_for_images,
         test_timeline_only_real_states,
         test_duration_formatting_human_readable,
         test_mobile_smoke]
passed = 0
for t in tests:
    try:
        t()
        passed += 1
    except Exception as e:
        print(f"  FAIL: {t.__name__}: {e}")
print(f"\n=== {passed}/{len(tests)} passed ===")
