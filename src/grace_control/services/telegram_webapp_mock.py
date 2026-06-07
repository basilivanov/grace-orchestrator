# ############################################################################
# AI_HEADER: telegram_webapp_mock
# ROLE: Inject window.Telegram.WebApp mock into a worktree for headless
#       Playwright testing (TZ_FRONTEND_ACCEPTANCE P0).
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Generate and inject a JS mock of window.Telegram.WebApp that
#          prevents "Cannot read properties of undefined" in headless tests.
#          Records SDK calls to telegram_calls.log for evidence.
# inputs: worktree_path (Path).
# returns: Path to the injected mock file.
# side_effects: Writes telegram-mock.js to the worktree root.
# emitted_logs: telegram_mock_injected.
# error_behavior: Returns None on failure, never raises.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: inject_mock_script
# END_MODULE_MAP

from __future__ import annotations

from pathlib import Path

from grace_control.core.structured_logger import GraceLogger

_log = GraceLogger("telegram_webapp_mock")

_TELEGRAM_MOCK_JS = r"""
// TZ_FRONTEND_ACCEPTANCE P0 — TelegramWebAppMock
// Records SDK calls to telegram_calls.log for evidence.

(function() {
  if (window.Telegram && window.Telegram.WebApp) return;

  var _calls = [];
  function _log(call) { _calls.push(call); }

  function _noop() {}
  function _noopSet(v) { return { setText: _noop, show: _noop, hide: _noop, onClick: _noop, offClick: _noop, enable: _noop, disable: _noop }; }

  window.Telegram = { WebApp: {
    initData: "mock_init_data",
    initDataUnsafe: { user: { id: 123, first_name: "Test" }, query_id: "mock_query" },
    version: "7.0",
    platform: "web",
    colorScheme: "light",
    themeParams: {
      bg_color: "#ffffff", text_color: "#000000",
      hint_color: "#707579", link_color: "#3390ec",
      button_color: "#3390ec", button_text_color: "#ffffff",
      secondary_bg_color: "#f0f0f0"
    },
    viewportHeight: 780,
    viewportStableHeight: 780,
    isExpanded: true,
    ready: function() { _log("ready"); },
    expand: function() { _log("expand"); },
    close: function() { _log("close"); },
    enableClosingConfirmation: function() { _log("enableClosingConfirmation"); },
    disableClosingConfirmation: function() { _log("disableClosingConfirmation"); },
    isClosingConfirmationEnabled: false,
    MainButton: _noopSet(),
    BackButton: _noopSet(),
    SettingsButton: _noopSet(),
    HapticFeedback: {
      impactOccurred: function() { _log("impactOccurred"); },
      notificationOccurred: function() { _log("notificationOccurred"); },
      selectionChanged: function() { _log("selectionChanged"); }
    },
    onEvent: function(event, cb) { _log("onEvent:" + event); },
    offEvent: function(event, cb) { _log("offEvent:" + event); },
    sendData: function(data) { _log("sendData:" + data); },
    openLink: function(url) { _log("openLink:" + url); },
    openTelegramLink: function(url) { _log("openTelegramLink:" + url); },
    openInvoice: function(url) { _log("openInvoice:" + url); },
    showPopup: function(params, cb) { _log("showPopup:" + JSON.stringify(params)); if (cb) cb("ok"); },
    showAlert: function(msg, cb) { _log("showAlert:" + msg); if (cb) cb(); },
    showConfirm: function(msg, cb) { _log("showConfirm:" + msg); if (cb) cb(true); },
    switchInlineQuery: function(query, types) { _log("switchInlineQuery"); },
    setHeaderColor: function(color) { _log("setHeaderColor"); },
    setBackgroundColor: function(color) { _log("setBackgroundColor"); },
    setBottomBarColor: function(color) { _log("setBottomBarColor"); },
    isVersionAtLeast: function(v) { return true; },
    // Cloud storage mock
    CloudStorage: {
      setItem: function(k, v, cb) { _log("CloudStorage.setItem:" + k); if (cb) cb(null, true); },
      getItem: function(k, cb) { _log("CloudStorage.getItem:" + k); if (cb) cb(null, ""); },
      getItems: function(keys, cb) { _log("CloudStorage.getItems"); if (cb) cb(null, ""); },
      removeItem: function(k, cb) { _log("CloudStorage.removeItem:" + k); if (cb) cb(null, true); },
      getKeys: function(cb) { _log("CloudStorage.getKeys"); if (cb) cb(null, []); },
    },
    // Biometric manager mock
    BiometricManager: {
      isInited: false,
      isBiometricAvailable: false,
      biometricType: "finger",
      isAccessRequested: false,
      isAccessGranted: false,
      isDeviceSaved: false,
      isTokenSaved: false,
      deviceId: "",
      init: function(cb) { _log("BiometricManager.init"); if (cb) cb(); },
      requestAccess: function(params, cb) { _log("BiometricManager.requestAccess"); if (cb) cb(true); },
      authenticate: function(params, cb) { _log("BiometricManager.authenticate"); if (cb) cb(true); },
      updateToken: function(token, cb) { _log("BiometricManager.updateToken"); if (cb) cb(true); },
      openSettings: function() { _log("BiometricManager.openSettings"); },
    },
    _calls: _calls,
  }};

  // Dump calls on page unload
  window.addEventListener('beforeunload', function() {
    var log = window.Telegram.WebApp._calls.join('\n');
    try { localStorage.setItem('telegram_calls', log); } catch(e) {}
  });
})();
"""


def inject_mock_script(worktree_path: Path) -> Path | None:
    """Write telegram-mock.js to worktree and return its path.

    The mock can be injected via Playwright's page.addInitScript() or
    by including it as a <script> tag in index.html.
    """
    try:
        mock_file = Path(worktree_path) / "telegram-mock.js"
        mock_file.write_text(_TELEGRAM_MOCK_JS)
        _log.info("telegram_mock_injected", path=str(mock_file))
        return mock_file
    except Exception as e:
        _log.warn("telegram_mock_inject_failed", error=str(e)[:200])
        return None
