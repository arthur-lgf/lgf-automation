from __future__ import annotations

from playwright.async_api import async_playwright


class ScreenshotError(RuntimeError):
    pass


async def snapshot_html(
    html: str,
    selector: str = "#report-table",
    viewport_width: int = 1400,
    viewport_height: int = 900,
) -> bytes:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    device_scale_factor=2,
                )
                page = await context.new_page()
                await page.set_content(html, wait_until="networkidle")
                locator = page.locator(selector)
                if await locator.count() == 0:
                    raise ScreenshotError(f"Selector '{selector}' not found in rendered HTML.")
                return await locator.screenshot(type="png", omit_background=False)
            finally:
                await browser.close()
    except ScreenshotError:
        raise
    except Exception as exc:
        raise ScreenshotError(f"Playwright failed to capture snapshot: {exc}") from exc
