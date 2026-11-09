"""Print a built report page to PDF with headless Chromium (Playwright).

Optional step, not part of the daily pipeline: the GitHub Action has no browser. Charts
are drawn for the window width, so the page is laid out at the PDF's content width before
printing; collapsed lists are opened; the light theme is forced.

Usage:
    python analysis/export_pdf.py analysis/reports/ai_spread_2026-11-06.html
    # -> analysis/reports/ai_spread_2026-11-06.pdf
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

CHROMIUM = "/opt/pw-browsers/chromium"     # preinstalled in the cloud containers
CONTENT_PX = 760                            # A4 (210 mm) minus 2 x 8 mm margins, at 96 dpi ≈ 733 px


async def export(src: Path, out: Path) -> None:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        exe = CHROMIUM if os.path.exists(CHROMIUM) else None
        browser = await p.chromium.launch(executable_path=exe) if exe else await p.chromium.launch()
        page = await browser.new_page(viewport={"width": CONTENT_PX, "height": 1200}, color_scheme="light")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        await page.goto(src.resolve().as_uri())
        await page.wait_for_timeout(1500)
        await page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
        await page.emulate_media(media="print")
        await page.wait_for_timeout(500)
        await page.pdf(path=str(out), format="A4", print_background=True, prefer_css_page_size=False,
                       margin={"top": "10mm", "bottom": "12mm", "left": "8mm", "right": "8mm"},
                       display_header_footer=True, header_template="<span></span>",
                       footer_template="<div style='font-size:8px;width:100%;text-align:center;color:#888'>"
                                       "<span class='title'></span> · <span class='pageNumber'></span> / <span class='totalPages'></span></div>")
        await browser.close()
        if errors:
            raise SystemExit(f"page errors while printing: {errors}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--out")
    args = ap.parse_args()
    src = Path(args.html)
    out = Path(args.out) if args.out else src.with_suffix(".pdf")
    asyncio.run(export(src, out))
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
