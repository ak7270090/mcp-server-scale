"""Render every *.html card in this folder to a 2x PNG of its .capture element."""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

source_directory = Path(__file__).parent
output_directory = Path(sys.argv[1])
only_names = set(sys.argv[2:])

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge")
    page = browser.new_page(viewport={"width": 1040, "height": 900}, device_scale_factor=2)
    for html_file in sorted(source_directory.glob("*.html")):
        if only_names and html_file.stem not in only_names:
            continue
        page.goto(html_file.as_uri())
        page.wait_for_timeout(300)
        target = output_directory / f"{html_file.stem}.png"
        page.locator(".capture").screenshot(path=str(target))
        print("rendered", target.name)
    browser.close()
