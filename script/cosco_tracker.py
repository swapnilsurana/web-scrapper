import time
import random
import re
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
                tracking_data["Container Number"] = container_no

                # The header flex row concatenates: container + size + datetime + "Last Pod Eta" + "Print".
                # Grab its full text and regex-extract the ETA if "last pod eta" is present.
                header_flex = frame.locator('div[data-v-b046195d].ant-flex').first
                if header_flex.is_visible():
                    header_text = (header_flex.text_content() or "").strip()
                    if re.search(r"last\s*pod\s*eta", header_text, re.IGNORECASE):
                        m_eta = re.search(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})", header_text)
                        if m_eta:
                            tracking_data["Last POD ETA"] = m_eta.group(1)
                            events.append({
                                "dynamic_node": "Last POD ETA",
                                "event_time": m_eta.group(1),
                                "event_location": None,
                                "transport_mode": None,
                            })

                # Extract Size Type
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
                        dynamic_node = cells.nth(0).text_content().strip()
                        event_time = cells.nth(1).text_content().strip()
                        event_location = cells.nth(2).text_content().strip()
                        transport_mode = cells.nth(3).text_content().strip()
                        events.append({
                            "dynamic_node": dynamic_node,
                            "event_time": event_time,
                            "event_location": event_location,
                            "transport_mode": transport_mode
                        })

                        # In some layouts, "Last Pod Eta" appears as a normal 4-col row.
                        if "last" in dynamic_node.lower() and "pod" in dynamic_node.lower() and "eta" in dynamic_node.lower():
                            tracking_data["Last POD ETA"] = tracking_data.get("Last POD ETA") or event_time
                    elif cells.count() >= 2:
                        # In some layouts, "Last Pod Eta" is rendered as a short row (2 cols).
                        label = (cells.nth(0).text_content() or "").strip()
                        value = (cells.nth(1).text_content() or "").strip()
                        if label and value and ("pod" in label.lower()) and ("eta" in label.lower()):
                            tracking_data["Last POD ETA"] = tracking_data.get("Last POD ETA") or value
                            events.append({
                                "dynamic_node": label,
                                "event_time": value,
                                "event_location": None,
                                "transport_mode": None
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

    CONTAINER_ID = "CSNU2742077"
    result = get_cosco_tracking(CONTAINER_ID, headless=False)

    pprint(result)
