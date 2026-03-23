import time
import random
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


def get_maersk_tracking(container_no: str, headless: bool = False):
    url = f"https://www.maersk.com/tracking/{container_no}"

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
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            ),
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
        print("🔄 Session warm-up...")
        page.goto("https://www.maersk.com/", timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        human_delay(3, 5)

        handle_cookie_popup(page)
        human_delay(2, 3)

        # Simulate user interaction
        page.mouse.move(200, 200)
        human_delay(1, 2)

        # -------------------------------
        # 🚢 TRACKING PAGE
        # -------------------------------
        print(f"🚢 Opening tracking: {url}")
        page.goto(url, timeout=60000)

        # Let React + API load
        time.sleep(5)

        # Wait for either success OR no result
        try:
            found = False

            for _ in range(20):  # ~20 seconds
                if page.locator('[data-test="container"]').first.is_visible():
                    found = True
                    break

                if page.locator("text=No results found").first.is_visible():
                    found = True
                    break

                time.sleep(1)

            if not found:
                print("⚠️ Failed to load expected content — saving debug")
                with open("blocked_debug.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                raise Exception("Blocked or DOM changed")
        except:
            print("⚠️ Failed to load expected content — saving debug")
            with open("blocked_debug.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
            raise Exception("Blocked or DOM changed")

        # -------------------------------
        # ❌ NO RESULT CASE
        # -------------------------------
        if page.locator("text=No results found").count() > 0:
            browser.close()
            return {
                "status": "not_found",
                "container_number": container_no
            }

        # -------------------------------
        # ✅ DATA EXTRACTION
        # -------------------------------
        container_number = None
        container_type = None
        last_updated = None
        eta = None
        latest_event = None
        events = []

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

        browser.close()

        return {
            "status": "success",
            "container_number": container_number,
            "container_type": container_type,
            "last_updated": last_updated,
            "eta": eta,
            "latest_event": latest_event,
            "events": events,
        }


# -------------------------------
# 🧪 RUN
# -------------------------------
if __name__ == "__main__":
    from pprint import pprint

    container_id = "PONU2003175"
    result = get_maersk_tracking(container_id, headless=False)

    pprint(result)