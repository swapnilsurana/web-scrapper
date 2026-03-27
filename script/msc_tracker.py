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
        page.wait_for_selector("#onetrust-reject-all-handler", timeout=5000)
        page.click("#onetrust-reject-all-handler")
        print("✅ Cookie rejected/handled")
        return
    except:
        pass

    try:
        page.wait_for_selector('button:has-text("Reject All")', timeout=3000)
        page.click('button:has-text("Reject All")')
        print("✅ Cookie rejected/handled (text match)")
        return
    except:
        pass

    print("ℹ️ No cookie popup found")


def get_msc_tracking(container_no: str, headless: bool = False):
    url = "https://www.msc.com/en/track-a-shipment"

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
            page.goto(url, timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            human_delay(3, 5)

            handle_cookie_popup(page)
            human_delay(1, 2)

            page.mouse.move(200, 200)
            human_delay(1, 2)

            print(f"📝 Entering container: {container_no}")
            try:
                page.locator("#trackingNumber").click()
                page.type("#trackingNumber", container_no, delay=150)
                human_delay(1, 1.5)

                page.press("#trackingNumber", "Enter")
                print("🔍 Search submitted via Enter")

                try:
                    page.locator("button.msc-search-autocomplete__search").nth(1).click(timeout=1500)
                    print("🔍 Search clicked explicitly")
                except:
                    pass
                print("🔍 Search clicked")
            except Exception as e:
                print("⚠️ Failed to enter container number or click search")
                browser.close()
                return {"status": "error", "message": str(e), "container_number": container_no}

            human_delay(4, 6)

            try:
                found = False
                for _ in range(20):
                    if page.locator(".msc-flow-tracking__details").first.is_visible():
                        time.sleep(3)
                        found = True
                        break
                    if page.locator("text=No results found").first.is_visible():
                        found = True
                        break
                    time.sleep(1)

                if not found:
                    print("⚠️ Failed to load expected content — saving debug")
                    with open("blocked_debug_msc.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                    raise Exception("Blocked, DOM changed or NO Results found")
            except Exception as e:
                print(f"⚠️ Exception waiting for results: {str(e)}")
                try:
                    with open("blocked_debug_msc.html", "w", encoding="utf-8") as f:
                        f.write(page.content())
                except:
                    pass
                browser.close()
                return {
                    "status": "error",
                    "message": "Results not loaded or tracking not found",
                    "container_number": container_no
                }

            if page.locator("text=No results found").count() > 0:
                browser.close()
                return {"status": "not_found", "container_number": container_no}

            print("✅ Extracting data...")
            page_content = page.content()
            soup = BeautifulSoup(page_content, 'html.parser')

            # --- General tracking info ---
            tracking_data = {}
            tracking_results = soup.find_all('div', class_='msc-flow-tracking__details')
            for tracking_result in tracking_results:
                details_list = tracking_result.find('ul')
                if details_list:
                    for item in details_list.find_all('li'):
                        heading = item.find('span', class_='msc-flow-tracking__details-heading')
                        value = item.find('span', class_='msc-flow-tracking__details-value')
                        if heading and value:
                            key = heading.get_text(strip=True)
                            val = value.get_text(strip=True)
                            if key and val and '{' not in key and '{' not in val:
                                tracking_data[key] = val

            # --- Container summary bar info ---
            container_sections = soup.find_all('div', class_='msc-flow-tracking__container')
            for container_section in container_sections:
                cells = container_section.find_all('div', class_='msc-flow-tracking__cell-flex')
                for cell in cells:
                    heading = cell.find('span', class_='data-heading')
                    value = cell.find('span', class_='data-value')
                    if heading and value:
                        key = heading.get_text(strip=True)
                        val = value.get_text(strip=True)
                        if key and val and '{' not in key and '{' not in val:
                            if key not in tracking_data:
                                tracking_data[key] = val

            # --- Events extraction ---
            events = []
            for container_section in container_sections:
                tracking_div = container_section.find('div', class_='msc-flow-tracking__tracking')
                if not tracking_div:
                    continue
                for port_div in tracking_div.find_all('div', class_='msc-flow-tracking__port'):
                    step = port_div.find('div', class_='msc-flow-tracking__step')
                    if not step:
                        continue

                    def get_cell_value(cell_class):
                        cell = step.find('div', class_=cell_class)
                        if cell:
                            val = cell.find('span', class_='data-value')
                            if val:
                                return val.get_text(strip=True)
                        return None

                    date = get_cell_value('msc-flow-tracking__cell--two')
                    location = get_cell_value('msc-flow-tracking__cell--three')
                    description = get_cell_value('msc-flow-tracking__cell--four')

                    # Detail (vessel/voyage) — cell five, first data-value
                    detail = None
                    cell_five = step.find('div', class_='msc-flow-tracking__cell--five')
                    if cell_five:
                        dv = cell_five.find('span', class_='data-value')
                        if dv:
                            detail = dv.get_text(strip=True)

                    # Equipment handling facility — cell six, first data-value
                    facility = None
                    cell_six = step.find('div', class_='msc-flow-tracking__cell--six')
                    if cell_six:
                        dv = cell_six.find('span', class_='data-value')
                        if dv:
                            txt = dv.get_text(strip=True)
                            if txt and txt != 'N.A' and '{' not in txt:
                                facility = txt

                    if date and description and '{' not in (date + description):
                        event = {
                            "date": date,
                            "location": location,
                            "description": description,
                        }
                        if detail:
                            event["detail"] = detail
                        if facility:
                            event["facility"] = facility
                        events.append(event)

            browser.close()

            if not tracking_data:
                return {"status": "not_found", "container_number": container_no}

            return {
                "status": "success",
                "container_number": container_no,
                "data": tracking_data,
                "events": events
            }


# -------------------------------
# 🧪 RUN
# -------------------------------
if __name__ == "__main__":
    from pprint import pprint

    CONTAINER_ID = "MSDU5514738"
    result = get_msc_tracking(CONTAINER_ID, headless=False)

    pprint(result)
