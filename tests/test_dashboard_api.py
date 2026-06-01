"""Dashboard smoke tests — validate HTML structure, JS syntax, API data."""
import httpx, re, json

API = "http://localhost:8042"
c = httpx.Client(base_url=API, timeout=5)

# 1. API tests
def test_dashboard_api():
    r = c.get("/api/dashboard")
    assert r.status_code == 200
    d = r.json()
    assert "features" in d
    assert "workers" in d
    assert "stats" in d
    print(f"  OK: {len(d['features'])} features, {len(d['workers'])} workers")

def test_events_api():
    r = c.get("/api/events?limit=5")
    assert r.status_code == 200
    assert "data" in r.json()
    print(f"  OK: events endpoint works")

def test_health():
    r = c.get("/health")
    assert r.status_code == 200
    assert "status" in r.json()
    print(f"  OK: health={r.json()['status']}")

# 2. HTML structure tests
def test_html_served():
    r = c.get("/")
    assert r.status_code == 200
    assert len(r.text) > 1000
    print(f"  OK: {len(r.text)} bytes")

def test_css_classes():
    r = c.get("/")
    html = r.text
    required = ["fcard", "wcard", "pcard", "tl-step", "tabs", "tab", "hdr", "dash", "panel-l", "panel-c", "panel-r", "insp"]
    for cls in required:
        assert f".{cls}" in html or f'"{cls}"' in html or f"class={cls}" in html or f"class=\"{cls}" in html or f"'{cls}'" in html, f"Missing CSS class: {cls}"
    print(f"  OK: all {len(required)} CSS classes found")

def test_mobile_support():
    r = c.get("/")
    html = r.text
    assert "max-width:699px" in html, "Missing mobile breakpoint"
    assert "mnav" in html, "Missing mobile nav"
    assert "navBack" in html, "Missing navBack function"
    print("  OK: mobile support present")

def test_legend():
    r = c.get("/")
    html = r.text
    assert "Status Legend" in html, "Missing legend"
    assert "Ready" in html and "Running" in html and "Merged" in html, "Missing status labels"
    print("  OK: legend with text labels")

# 3. JS validation
def _extract_main_js(html):
    scripts = list(re.finditer(r'<script>(.*?)</script>', html, re.DOTALL))
    if len(scripts) > 1:
        return scripts[-1].group(1)  # main JS is last script tag
    elif scripts:
        return scripts[0].group(1)
    return ""

def test_js_present():
    r = c.get("/")
    js = _extract_main_js(r.text)
    assert len(js) > 1000, f"JS too short: {len(js)} bytes"
    print(f"  OK: {len(js)} bytes of JS")

def test_js_no_obvious_errors():
    r = c.get("/")
    js = _extract_main_js(r.text)
    backticks = js.count('`')
    assert backticks % 2 == 0, f"Odd backticks: {backticks}"
    assert 'style=display:none' not in js, "Has inline style=display:none"
    assert js.count('{') == js.count('}'), f"Unbalanced braces"
    print(f"  OK: backticks={backticks} balanced, no inline styles")

def test_js_key_functions():
    r = c.get("/")
    js = _extract_main_js(r.text)
    funcs = ["function load(", "function renderFeatures(", "function renderWaves(",
             "function renderInspector(", "function selFeature(", "function selPacket(",
             "function connectWS(", "function swTab(", "function navBack(",
             "function loadRunArts(", "function viewArt(",
             "function toggleTheme(", "function toggleSelfEvolve(", "function loadSESessions(",
             "function launchSelfEvolve(", "function cancelSESession("]
    for f in funcs:
        assert f in js, f"Missing function: {f}"
    print(f"  OK: all {len(funcs)} key functions found")

# 4. Feature data integration test
def test_features_have_waves():
    r = c.get("/api/dashboard")
    for f in r.json()["features"]:
        assert "waves" in f, f"Feature {f['id']} missing waves"
        for w in f["waves"]:
            assert "packets" in w, f"Wave {w['id']} missing packets"
            for p in w["packets"]:
                assert "state" in p, f"Packet {p['id']} missing state"
    print(f"  OK: all features have waves with packets")

# Run all
print("=== Dashboard Tests ===\n")
tests = [test_dashboard_api, test_events_api, test_health,
         test_html_served, test_css_classes, test_mobile_support, test_legend,
         test_js_present, test_js_no_obvious_errors, test_js_key_functions,
         test_features_have_waves]
passed = 0
for t in tests:
    try:
        t()
        passed += 1
    except Exception as e:
        print(f"  FAIL: {t.__name__}: {e}")
print(f"\n=== {passed}/{len(tests)} passed ===")
