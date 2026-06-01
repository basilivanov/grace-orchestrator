# ############################################################################
# AI_HEADER: test_theme_toggle
# ROLE: E2E Playwright test for theme toggle functionality.
# MODULE_CONTRACT:
# - Provide Playwright E2E tests for the theme toggle feature.
# - Do not mutate global environment state outside the test scope.
# ############################################################################

import os

from playwright.sync_api import Page, expect


def test_theme_toggle(page: Page):
    """
    Verify theme-toggle button exists in header, clicking toggles :root[data-theme=light],
    clicking again restores dark (default), localStorage grace-theme persists across page reload.
    """
    server_url = os.environ.get("GRACE_SERVER", "http://localhost:8042")

    page.goto(server_url)

    # Verify the theme-toggle button exists in the header
    toggle_btn = page.locator("#theme-toggle")
    expect(toggle_btn).to_be_visible()

    root = page.locator(":root")

    # Clicking toggles :root[data-theme=light]
    toggle_btn.click()
    expect(root).to_have_attribute("data-theme", "light")

    # Clicking again restores dark (default)
    toggle_btn.click()
    expect(root).not_to_have_attribute("data-theme", "light")

    # localStorage grace-theme persists across page reload
    toggle_btn.click()
    expect(root).to_have_attribute("data-theme", "light")

    local_storage_theme = page.evaluate("localStorage.getItem('grace-theme')")
    assert local_storage_theme == "light"

    page.reload()

    expect(root).to_have_attribute("data-theme", "light")
    local_storage_theme_after = page.evaluate("localStorage.getItem('grace-theme')")
    assert local_storage_theme_after == "light"
