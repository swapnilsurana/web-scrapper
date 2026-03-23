import time
import random
from playwright.sync_api import sync_playwright
from xvfbwrapper import Xvfb


def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def get_goldstarline_tracking(container_no: str, headless: bool = False):
    url = "https://www.goldstarline.com/tools/track_shipment"

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

            # Stealth
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            print(f"🔄 Opening Gold Star Line tracking page...")
            page.goto(url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            human_delay(2, 3)

            print(f"📦 Entering container number: {container_no}")
            input_field = page.locator("textarea, input[type='text']").first
            input_field.click()
            input_field.fill(container_no)
            human_delay(0.5, 1)

            print("🔍 Clicking Track Shipment...")
            page.click("#submitDetails")
            human_delay(2, 4)

            try:
                page.wait_for_selector(".trackShipmentResultRow", timeout=15000)
            except:
                print("⚠️ Results not found — saving debug HTML")
                with open("blocked_debug_goldstar.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                browser.close()
                raise Exception("No results loaded or page blocked")

            if page.locator("text=No results found").count() > 0:
                browser.close()
                return {"status": "not_found", "container_number": container_no}

            basic_info = {}
            try:
                cart_items = page.locator(".trackShipmentResultRow .cartItem")
                for i in range(cart_items.count()):
                    item = cart_items.nth(i)
                    label = item.locator("label")
                    value = item.locator("h3")
                    if label.count() > 0 and value.count() > 0:
                        basic_info[label.inner_text().strip()] = value.inner_text().strip()
            except:
                pass

            detailed_info = {}
            try:
                tables = page.locator(".main-cargo-head-container table")
                for i in range(tables.count()):
                    rows = tables.nth(i).locator("tr")
                    for j in range(rows.count()):
                        cells = rows.nth(j).locator("td")
                        if cells.count() >= 2:
                            key = cells.nth(0).inner_text().strip()
                            val = cells.nth(1).inner_text().strip()
                            if key:
                                detailed_info[key] = val
            except:
                pass

            container_data = {}
            try:
                grid_items = page.locator(".accordion-button .card-header .grid-item")
                for i in range(grid_items.count()):
                    title = grid_items.nth(i).locator(".card-tittle")
                    data = grid_items.nth(i).locator(".card-data")
                    if title.count() > 0 and data.count() > 0:
                        container_data[title.inner_text().strip()] = data.inner_text().strip()
            except:
                pass

            activities = []
            try:
                accordion_btn = page.locator(".accordion-button").first
                if accordion_btn.count() > 0:
                    aria = accordion_btn.get_attribute("aria-expanded")
                    if aria == "false":
                        accordion_btn.click()
                        human_delay(0.5, 1)

                grid_containers = page.locator(".accordion-body .grid-container")
                for i in range(grid_containers.count()):
                    activity = {}
                    items = grid_containers.nth(i).locator(".grid-item")
                    for j in range(items.count()):
                        header = items.nth(j).locator(".grid-header")
                        if header.count() > 0:
                            header_text = header.inner_text().strip()
                            all_text = items.nth(j).inner_text().strip()
                            value_text = all_text.replace(header_text, "").strip()
                            if header_text and value_text:
                                activity[header_text] = value_text
                    if activity:
                        activities.append(activity)
            except:
                pass

            browser.close()

            return {
                "status": "success",
                "container_number": container_no,
                "basic_info": basic_info,
                "detailed_info": detailed_info,
                "container_data": container_data,
                "activities": activities,
            }


# -------------------------------
# 🧪 RUN
# -------------------------------
if __name__ == "__main__":
    from pprint import pprint

    container_id = "JXLU4428595"
    result = get_goldstarline_tracking(container_id, headless=False)

    pprint(result)
