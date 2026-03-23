import time
import random
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from xvfbwrapper import Xvfb

def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))

def handle_cookie_popup(page):
    print("🔄 Handling cookie popup...")
    try:
        allow_button = page.locator('button:has-text("Allow All")').first
        if allow_button.is_visible(timeout=3000):
            allow_button.click()
            print("✅ Cookie accepted")
            return
    except:
        pass

    try:
        page.wait_for_selector('button:has-text("Accept All")', timeout=3000)
        page.click('button:has-text("Accept All")')
        print("✅ Cookie accepted")
        return
    except:
        pass

    print("ℹ️ No cookie popup found")


def get_cosco_tracking(container_no: str, headless: bool = False):
    url = "https://elines.coscoshipping.com/ebusiness/cargoTracking"

    with Xvfb(width=1366, height=768, colordepth=24) as xvfb:
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

            print(f"🚢 Opening tracking: {url}")
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")
            human_delay(3, 5)

            handle_cookie_popup(page)
            human_delay(1, 2)

            page.mouse.move(200, 200)
            human_delay(1, 2)

            frame = page.frame_locator('#scctCargoTracking')

            try:
                print("[*] Selecting 'Container No.' from dropdown...")
                dropdown_selector = frame.locator('.ant-select-selector').first
                dropdown_selector.wait_for(state="visible", timeout=10000)
                dropdown_selector.click()
                human_delay(0.5, 1)

                container_option = frame.locator('.ant-select-item-option').filter(has_text="Container No.").first
                container_option.wait_for(state="visible", timeout=5000)
                container_option.click()
                human_delay(0.5, 1)
                print("✅ Selected 'Container No.'")
            except Exception as e:
                print(f"[!] Warning: Could not setup dropdown: {e}")

            print(f"📝 Entering container: {container_no}")
            try:
                input_field = frame.locator('input.ant-input').first
                input_field.wait_for(state="visible", timeout=5000)
                input_field.click()
                input_field.fill("")
                input_field.type(container_no, delay=150)
                human_delay(1, 1.5)

                search_button = frame.locator('button.ant-btn-default').filter(has_text="Search").first
                search_button.wait_for(state="visible", timeout=5000)
                search_button.click()
                print("🔍 Search clicked")
            except Exception as e:
                print("⚠️ Failed to enter container number or click search")
                try:
                    with open("blocked_debug_cosco.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except:
                    pass
                browser.close()
                return {"status": "error", "message": str(e), "container_number": container_no}

            human_delay(4, 6)

            try:
                found = False
                for _ in range(20):
                    if frame.locator(".ant-table-tbody").first.is_visible():
                        time.sleep(2)
                        found = True
                        break
                    if frame.locator("text=No data found").first.is_visible() or frame.locator("text=No results").first.is_visible():
                        found = True
                        break
                    time.sleep(1)

                if not found:
                    print("⚠️ Failed to load expected content — saving debug")
                    with open("blocked_debug_cosco.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    raise Exception("Blocked, DOM changed or NO Results found")
            except Exception as e:
                print(f"⚠️ Exception waiting for results: {str(e)}")
                try:
                    with open("blocked_debug_cosco.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except:
                    pass
                browser.close()
                return {
                    "status": "error",
                    "message": "Results not loaded or tracking not found",
                    "container_number": container_no
                }

            if frame.locator("text=No data found").count() > 0 or frame.locator("text=No results").count() > 0:
                browser.close()
                return {"status": "not_found", "container_number": container_no}

            print("✅ Extracting data...")
            tracking_data = {}
            events = []

            try:
                container_header = frame.locator('div[data-v-b046195d] > div:first-child').first
                if container_header.is_visible():
                    c_num = container_header.locator('div').first.text_content().strip()
                    tracking_data["Container Number"] = c_num

                size_element = frame.locator('span[data-v-b046195d]').filter(has_text="GP").first
                if not size_element.is_visible():
                    size_element = frame.locator('span[data-v-b046195d]').filter(has_text="HQ").first
                if size_element.is_visible():
                    tracking_data["Size Type"] = size_element.text_content().strip()

                rows = frame.locator('.ant-table-tbody tr.ant-table-row')
                for i in range(rows.count()):
                    row = rows.nth(i)
                    cells = row.locator('td')
                    if cells.count() >= 4:
                        events.append({
                            "dynamic_node": cells.nth(0).text_content().strip(),
                            "event_time": cells.nth(1).text_content().strip(),
                            "event_location": cells.nth(2).text_content().strip(),
                            "transport_mode": cells.nth(3).text_content().strip()
                        })

                tracking_data["events"] = events
            except Exception as e:
                print(f"[!] Warning during extraction: {e}")

            browser.close()

            if not tracking_data.get("events"):
                return {"status": "not_found", "container_number": container_no}

            return {
                "status": "success",
                "container_number": container_no,
                "data": tracking_data
            }


# -------------------------------
# 🧪 RUN
# -------------------------------
if __name__ == "__main__":
    from pprint import pprint

    CONTAINER_ID = "CSLU1914180"
    result = get_cosco_tracking(CONTAINER_ID, headless=False)

    pprint(result)
