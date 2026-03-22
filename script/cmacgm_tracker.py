import time
import random
from playwright.sync_api import sync_playwright


def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def get_cmacgm_tracking(container_no: str, headless: bool = False):
    url = "https://www.cma-cgm.com/ebusiness/tracking/search"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)

        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        # Stealth scripts (replaces playwright_stealth)
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({ query: () => Promise.resolve({ state: 'granted' }) })
            });
        """)

        # -------------------------------
        # Navigate to tracking page
        # -------------------------------
        print("🔄 Opening CMA CGM tracking page...")
        page.goto(url, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        human_delay(2, 4)

        # -------------------------------
        # Enter container number & search
        # -------------------------------
        print(f"📦 Entering container number: {container_no}")
        page.wait_for_selector("#Reference", timeout=10000)
        page.click("#Reference")
        page.fill("#Reference", container_no)
        human_delay(0.5, 1)

        print("🔍 Clicking Search...")
        page.click("#btnTracking")

        # -------------------------------
        # Wait for results
        # -------------------------------
        print("⏳ Waiting for tracking results...")
        try:
            found = False
            for _ in range(20):
                if page.locator("section.tracking-details").first.is_visible():
                    found = True
                    break
                if page.locator("text=No results").first.is_visible():
                    found = True
                    break
                time.sleep(1)

            if not found:
                raise Exception("Results did not load")
        except:
            print("⚠️ Failed to load results — saving debug HTML")
            with open("blocked_debug_cmacgm.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
            raise Exception("Blocked or DOM changed")

        # -------------------------------
        # No result case
        # -------------------------------
        if page.locator("text=No results").count() > 0:
            browser.close()
            return {"status": "not_found", "container_number": container_no}

        # -------------------------------
        # Extract header info
        # -------------------------------
        container_number = None
        container_type = None
        status = None
        pol = None
        pod = None
        eta = None

        try:
            container_number = page.locator(".resume-filter li strong").nth(0).inner_text().strip()
        except:
            pass

        try:
            # e.g. "45G1" and "(40HC)"
            type_parts = page.locator(".resume-filter .ico-container strong")
            if type_parts.count() >= 2:
                container_type = f"{type_parts.nth(0).inner_text().strip()} {type_parts.nth(1).inner_text().strip()}"
            elif type_parts.count() == 1:
                container_type = type_parts.nth(0).inner_text().strip()
        except:
            pass

        try:
            status = page.locator("header .capsule.primary").first.inner_text().strip()
        except:
            pass

        # -------------------------------
        # Extract POL / POD from timeline
        # -------------------------------
        try:
            pol_el = page.locator(".timeline--item .capsule:has-text('POL') + span strong")
            if pol_el.count() > 0:
                pol = pol_el.inner_text().strip()
        except:
            pass

        try:
            pod_el = page.locator(".timeline--item .capsule:has-text('POD') + span strong")
            if pod_el.count() > 0:
                pod = pod_el.inner_text().strip()
        except:
            pass

        try:
            eta_el = page.locator(".timeline--item-eta p span").first
            eta_time_el = page.locator(".timeline--item-eta p span.bg-icon")
            if eta_el.count() > 0:
                eta_date = eta_el.inner_text().strip()
                eta_time = eta_time_el.inner_text().strip() if eta_time_el.count() > 0 else ""
                eta = f"{eta_date} {eta_time}".strip()
        except:
            pass

        # -------------------------------
        # Extract events grid (Kendo grid)
        # The grid rows are loaded via JS — wait for tbody rows
        # -------------------------------
        events = []
        try:
            page.wait_for_selector("#gridTrackingDetails tbody tr", timeout=10000)
            rows = page.locator("#gridTrackingDetails tbody tr[role='row']")

            for i in range(rows.count()):
                row = rows.nth(i)
                cells = row.locator("td")

                date = None
                move = None
                location = None
                vessel_voyage = None

                # Columns: [expand] [icon] [Date] [Moves] [Location] [Vessel (Voyage)]
                try:
                    date = cells.nth(2).inner_text().strip()
                except:
                    pass
                try:
                    move = cells.nth(3).inner_text().strip()
                except:
                    pass
                try:
                    location = cells.nth(4).inner_text().strip()
                except:
                    pass
                try:
                    vessel_voyage = cells.nth(5).inner_text().strip()
                except:
                    pass

                if any([date, move, location]):
                    events.append({
                        "date": date,
                        "move": move,
                        "location": location,
                        "vessel_voyage": vessel_voyage,
                    })
        except:
            pass

        browser.close()

        return {
            "status": "success",
            "container_number": container_number,
            "container_type": container_type,
            "shipment_status": status,
            "pol": pol,
            "pod": pod,
            "eta": eta,
            "events": events,
        }


# -------------------------------
# 🧪 RUN
# -------------------------------
if __name__ == "__main__":
    from pprint import pprint

    container_id = "CMAU8629550"
    result = get_cmacgm_tracking(container_id, headless=False)

    pprint(result)
