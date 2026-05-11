import re
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def handle_cookie_popup(page):
    # Try normal popup
    try:
        page.wait_for_selector('button:has-text("Allow all")', timeout=6000)
        page.click('button:has-text("Allow all")')
        print("✅ Cookie accepted")
        return
    except:
        pass

    # Try iframe popup (fallback)
    for frame in page.frames:
        try:
            btn = frame.locator('button:has-text("Allow all")')
            if btn.count() > 0:
                btn.click()
                print("✅ Cookie accepted (iframe)")
                return
        except:
            pass

    print("ℹ️ No cookie popup found")


TRACKING_PAGE_URL = "https://www.maersk.com/tracking/"


def _normalized_container(container_no: str) -> str:
    s = re.sub(r"\s+", "", (container_no or "").strip().upper())
    if not s:
        raise ValueError("container_no is empty")
    return s


def _direct_tracking_url(container_no: str) -> str:
    return f"https://www.maersk.com/tracking/{_normalized_container(container_no)}"


def _default_user_agent() -> str:
    if sys.platform == "darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    )


def _visible_no_results_message(page) -> bool:
    candidates = [
        "No results found",
        "We couldn't find any Bills of Lading",
        "not available on public track",
    ]
    for msg in candidates:
        loc = page.get_by_text(msg, exact=False)
        for i in range(min(loc.count(), 10)):
            try:
                if loc.nth(i).is_visible():
                    return True
            except Exception:
                continue
    return False


def _container_panel_visible(page) -> bool:
    try:
        if page.locator('[data-test="container"]').first.is_visible():
            return True
        if page.locator('[data-test="transport-plan"]').first.is_visible():
            return True
        if page.locator('[data-test="container-location"]').first.is_visible():
            return True
        if page.locator('[data-test="track-from-value"]').first.is_visible():
            return True
        return False
    except Exception:
        return False


def _retry_sleep(attempt_idx: int) -> None:
    base = 2 + attempt_idx * 4
    jitter = random.uniform(0.5, 1.5)
    secs = base + jitter
    print(f"🔁 Backoff before retry: {secs:.1f}s")
    time.sleep(secs)


def _poll_until_outcome(page, phase: str) -> str:
    """Returns 'container', 'no_results', or 'timeout'."""
    print(f"⏳ [{phase}] waiting up to ~45s for container panel or visible no-results …")
    for i in range(45):
        if _container_panel_visible(page):
            print(f"✅ [{phase}] container panel visible (iteration {i + 1})")
            return "container"
        if _visible_no_results_message(page):
            print(f"ℹ️  [{phase}] visible 'No results found' (iteration {i + 1})")
            return "no_results"
        if (i + 1) % 10 == 0:
            print(f"⏳ [{phase}] still waiting… {i + 1}/45")
        time.sleep(1)
    return "timeout"


def _safe_filename_part(text: str) -> str:
    s = re.sub(r"[^\w.\-]+", "_", text.strip(), flags=re.ASCII)
    return s[:80] if len(s) > 80 else s or "unknown"


def save_final_screenshot(page, container_no: str, label: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    name = f"maersk_tracking_{_safe_filename_part(container_no)}_{label}_{ts}.png"
    path = Path.cwd() / name
    page.screenshot(path=str(path), full_page=True)
    print(f"📷 Final page screenshot: {path}")
    return str(path)


def _tracking_booking_combobox(page):
    return page.get_by_role("combobox").first


def _set_booking_type(page, value: str, display_name: str) -> None:
    combo = _tracking_booking_combobox(page)
    combo.wait_for(state="visible", timeout=20000)
    combo.scroll_into_view_if_needed()
    human_delay(0.15, 0.35)
    print(f"📋 Booking type → {display_name!r} (value={value!r})")
    try:
        combo.select_option(value=value, timeout=8000)
    except Exception:
        combo.click()
        human_delay(0.25, 0.45)
        lb = page.get_by_role("listbox")
        if lb.count() > 0:
            opt = lb.first.get_by_role("option", name=display_name)
        else:
            opt = page.get_by_role("option", name=display_name)
        if opt.count() == 0:
            opt = page.get_by_text(display_name, exact=True)
        opt.first.click()
    human_delay(0.35, 0.65)


def cycle_air_then_ocean_booking_type(page) -> None:
    """Maersk UI: briefly switch to Air cargo, then back to Ocean before container search."""
    print("📋 Cycling booking dropdown: Air cargo → Ocean cargo")
    _set_booking_type(page, "air", "Air cargo")
    _set_booking_type(page, "ocean", "Ocean cargo")


def submit_container_search(page, container_no: str):
    cn = _normalized_container(container_no)
    cycle_air_then_ocean_booking_type(page)
    print("⌨️  Focusing search field (container will be entered next)")
    search = page.get_by_placeholder("BL or container number")
    search.wait_for(state="visible", timeout=20000)
    search.scroll_into_view_if_needed()
    human_delay(0.2, 0.5)
    search.click()
    human_delay(0.1, 0.3)
    search.clear()
    human_delay(0.1, 0.2)
    print(f"⌨️  Typing container number (normalized): {cn!r}")
    search.press_sequentially(cn, delay=random.uniform(25, 55))
    human_delay(0.3, 0.6)
    print("🖱️  Clicking Track")
    page.get_by_role("button", name="Track").first.click()
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
        print("⏳ Network idle after Track (within timeout)")
    except Exception:
        print("⏳ Network idle wait ended (timeout or still active — continuing)")


def get_maersk_tracking(container_no: str, headless: bool = False):
    cn = _normalized_container(container_no)
    print(f"🚀 Maersk tracking start container={container_no!r} normalized={cn!r} headless={headless}")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ]
        )

        context = browser.new_context(
            user_agent=_default_user_agent(),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        # 🛡️ Stealth
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # -------------------------------
        # 🔄 SESSION WARM-UP
        # -------------------------------
        print("🔄 Session warm-up: navigating to maersk.com …")
        page.goto("https://www.maersk.com/", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        print(f"📄 Warm-up URL: {page.url}")
        human_delay(3, 5)

        handle_cookie_popup(page)
        human_delay(2, 3)

        # Simulate user interaction
        page.mouse.move(200, 200)
        human_delay(1, 2)

        # -------------------------------
        # 🚢 TRACKING PAGE
        # -------------------------------
        print(f"🚢 Opening tracking page: {TRACKING_PAGE_URL}")
        page.goto(TRACKING_PAGE_URL, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        print(f"📄 Tracking page URL: {page.url}")
        human_delay(1, 2)
        handle_cookie_popup(page)
        human_delay(0.5, 1)
        last_not_found_shot = None
        for attempt in range(3):
            if attempt > 0:
                _retry_sleep(attempt - 1)
                try:
                    context.clear_cookies()
                except Exception:
                    pass
                page.goto(TRACKING_PAGE_URL, timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                human_delay(1, 2)
                handle_cookie_popup(page)
                human_delay(0.5, 1)

            print(f"🔎 Attempt {attempt + 1}/3: submit via form")
            submit_container_search(page, cn)

            print("⏳ Initial settle after submit (3s) …")
            time.sleep(3)

            try:
                outcome = _poll_until_outcome(page, f"form submit attempt {attempt + 1}")
                if outcome == "timeout":
                    print("⚠️ Failed to load expected content — saving debug")
                    with open("blocked_debug.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    raise Exception("Blocked or DOM changed")
            except Exception:
                print("⚠️ Failed to load expected content — saving debug")
                with open("blocked_debug.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                save_final_screenshot(page, cn, f"blocked_timeout_a{attempt + 1}")
                browser.close()
                raise Exception("Blocked or DOM changed")

            if _container_panel_visible(page):
                print("📦 Result: tracking data present — parsing DOM …")
                break

            if _visible_no_results_message(page):
                direct = _direct_tracking_url(cn)
                print(f"↪️ Form returned no results — retrying direct URL: {direct}")
                page.goto(direct, timeout=60000)
                page.wait_for_load_state("domcontentloaded")
                human_delay(2, 3)
                handle_cookie_popup(page)
                human_delay(1, 2)
                outcome2 = _poll_until_outcome(page, f"direct URL attempt {attempt + 1}")
                if outcome2 == "timeout":
                    print("⚠️ Direct URL: timed out — saving debug")
                    with open("blocked_debug.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    save_final_screenshot(page, cn, f"blocked_timeout_direct_a{attempt + 1}")
                    browser.close()
                    raise Exception("Blocked or DOM changed")

                if _container_panel_visible(page):
                    print("📦 Direct URL: tracking data present — parsing DOM …")
                    break

                if _visible_no_results_message(page):
                    last_not_found_shot = save_final_screenshot(page, cn, f"not_found_a{attempt + 1}")
                    print("ℹ️ Still not found after direct URL")
                    continue

                print("⚠️ Unexpected state after direct URL — saving debug")
                with open("blocked_debug.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                save_final_screenshot(page, cn, f"unexpected_state_direct_a{attempt + 1}")
                browser.close()
                raise Exception("Blocked or DOM changed")

            print("⚠️ Unexpected state — saving debug")
            with open("blocked_debug.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            save_final_screenshot(page, cn, f"unexpected_state_a{attempt + 1}")
            browser.close()
            raise Exception("Blocked or DOM changed")

        if not _container_panel_visible(page):
            browser.close()
            return {
                "status": "not_found",
                "container_number": cn,
                "screenshot": last_not_found_shot,
            }

        # -------------------------------
        # ✅ DATA EXTRACTION
        # -------------------------------
        container_number = None
        container_type = None
        last_updated = None
        eta = None
        latest_event = None
        pol = None
        pod = None
        events = []

        try:
            from_el = page.locator('[data-test="track-from-value"]').first
            if from_el.count() > 0:
                pol = from_el.inner_text().strip() or None
        except:
            pass

        try:
            to_el = page.locator('[data-test="track-to-value"]').first
            if to_el.count() > 0:
                pod = to_el.inner_text().strip() or None
        except:
            pass

        try:
            header = page.locator('[data-test="container"] header')
            txt_icons = header.locator("mc-text-and-icon")

            if txt_icons.count() > 0:
                spans = txt_icons.nth(0).locator("span")
                if spans.count() >= 3:
                    container_number = spans.nth(0).inner_text().strip()
                    container_type = spans.nth(2).inner_text().strip()

            if txt_icons.count() > 1:
                last_updated_el = txt_icons.nth(1).locator('[data-test="last-updated"]')
                if last_updated_el.count() > 0:
                    last_updated = last_updated_el.inner_text().strip()
        except:
            pass

        try:
            eta_el = page.locator('[data-test="container-eta"] span.labels slot').nth(1)
            if eta_el.count() > 0:
                eta = eta_el.inner_text().strip()
        except:
            pass

        try:
            latest_event_el = page.locator('[data-test="container-location"] [slot="sublabel"]')
            if latest_event_el.count() > 0:
                latest_event = latest_event_el.inner_text().strip()
        except:
            pass

        try:
            items = page.locator('[data-test="transport-plan"] li.transport-plan__list__item')

            for i in range(items.count()):
                item = items.nth(i)

                location_name = None
                location_terminal = None
                milestone_name = None
                milestone_date = None

                try:
                    strong = item.locator(".location strong")
                    if strong.count() > 0:
                        location_name = strong.inner_text().strip()
                        full_text = item.locator(".location").inner_text().strip()
                        location_terminal = full_text.replace(location_name, "").strip()
                except:
                    pass

                try:
                    milestone = item.locator('[data-test="milestone"]')
                    if milestone.count() > 0:
                        spans = milestone.locator("span")

                        if spans.count() > 0:
                            milestone_name = spans.nth(0).inner_text().strip()

                        date_el = milestone.locator('[data-test="milestone-date"]')
                        if date_el.count() > 0:
                            milestone_date = date_el.inner_text().strip()
                except:
                    pass

                events.append({
                    "location_name": location_name,
                    "location_terminal": location_terminal,
                    "event": milestone_name,
                    "date_time": milestone_date,
                })

        except:
            pass

        shot = save_final_screenshot(page, cn, "success")
        browser.close()
        print("✅ Maersk tracking finished (success)")

        return {
            "status": "success",
            "container_number": container_number,
            "container_type": container_type,
            "last_updated": last_updated,
            "eta": eta,
            "latest_event": latest_event,
            "Port of Loading (POL)": pol,
            "Port of Discharge (POD)": pod,
            "events": events,
            "screenshot": shot,
        }


# -------------------------------
# 🧪 RUN
# -------------------------------
if __name__ == "__main__":
    from pprint import pprint

    container_id = "MRKU0580031"
    result = get_maersk_tracking(container_id, headless=False)

    pprint(result)