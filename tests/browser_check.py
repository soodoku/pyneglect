"""Smoke test a real rendered report in Chromium, without external requests."""

import functools
import http.server
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    root = Path(sys.argv[1]).resolve()
    screenshots = Path(".cache/browser")
    screenshots.mkdir(parents=True, exist_ok=True)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}/")
            page.wait_for_selector("#count")
            assert page.locator("#rows tr").count() > 0
            page.locator("#search").fill("no-such-project-xyz123")
            assert page.locator("#empty").is_visible()
            page.locator("#reset").click()
            assert not page.locator("#empty").is_visible()
            page.locator("#view").select_option("directory")
            page.locator("#contributors").fill("5")
            for cell in page.locator("#rows tr td:nth-child(3)").all():
                assert "Unknown" not in cell.inner_text()
            page.locator("#reset").click()
            page.locator("#sort").select_option("package")
            names = page.locator("#rows .name").all_text_contents()
            assert names == sorted(names, key=str.lower)
            assert page.locator('a[href="candidates.csv"]').count() == 1
            page.locator("#rows details").first.locator("summary").click()
            page.screenshot(path=str(screenshots / "desktop.png"), full_page=False)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(screenshots / "mobile.png"), full_page=False)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print("Browser checks passed")


if __name__ == "__main__":
    main()
