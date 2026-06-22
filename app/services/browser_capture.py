from __future__ import annotations

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class CaptureError(RuntimeError):
    pass


def _looks_logged_out(current_url: str) -> bool:
    # NOTE: The exact Skool login pattern may need tuning after the spike.
    lowered = current_url.lower()
    return "/login" in lowered or "/signup" in lowered


async def _read_kpis(page, kpi_selectors: dict[str, str] | None) -> dict[str, str]:
    """Best-effort KPI text extraction. Never raises — partial results are fine."""
    if not kpi_selectors:
        return {}
    results: dict[str, str] = {}
    for name, sel in kpi_selectors.items():
        try:
            text = (await page.locator(sel).inner_text()).strip()
            results[name] = text
        except Exception:
            pass  # skip this key and continue
    return results


async def capture_dashboard(
    url: str,
    *,
    auth_token: str,
    cookie_domain: str = ".skool.com",
    selector: str,
    viewport_width: int,
    viewport_height: int,
    kpi_selectors: dict[str, str] | None = None,
    user_agent: str = _DEFAULT_USER_AGENT,
) -> tuple[bytes, dict[str, str]]:
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": viewport_width, "height": viewport_height},
                    device_scale_factor=2,
                )

                # Inject the session cookie before navigating.
                # Additional cookies (e.g. cf_clearance) can be added here later
                # if the spike shows Skool needs them — cf_clearance is IP/UA-bound
                # and Cloudflare must re-issue it on the runner, so we skip it for now.
                await context.add_cookies([{
                    "name": "auth_token",
                    "value": auth_token,
                    "domain": cookie_domain,
                    "path": "/",
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "Lax",
                }])

                page = await context.new_page()
                await page.goto(url, wait_until="networkidle")

                # Logged-out detection: if we were redirected to a login/signup page,
                # the token is expired or invalid.
                if _looks_logged_out(page.url):
                    raise CaptureError("session expired — refresh SKOOL_AUTH_TOKEN")

                try:
                    await page.wait_for_selector(selector, state="visible", timeout=30000)
                except PlaywrightTimeoutError:
                    # Panel never rendered — almost always an auth/session problem.
                    raise CaptureError("session expired — refresh SKOOL_AUTH_TOKEN")

                kpis = await _read_kpis(page, kpi_selectors)

                element = page.locator(selector)
                if await element.count() == 0:
                    raise CaptureError(f"selector {selector!r} not found")
                png = await element.screenshot(type="png")

                return (png, kpis)
            finally:
                await browser.close()
    except CaptureError:
        raise
    except Exception as exc:
        raise CaptureError(f"Playwright failed to capture dashboard: {exc}") from exc
