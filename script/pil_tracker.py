import time
import random
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def get_pil_tracking(container_no: str, headless: bool = False):
    url = "https://www.pilship.com/digital-solutions/?tab=customer&id=track-trace&label=containerTandT"

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

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # -------------------------------
        # 🚢 TRACKING PAGE
        # -------------------------------
        print(f"🚢 Opening tracking: {url}")
        page.goto(url, timeout=60000)
        page.wait_for_load_state("domcontentloaded")
        human_delay(3, 5)

        # -------------------------------
        # 📝 ENTER CONTAINER
        # -------------------------------
        print(f"📝 Entering container: {container_no}")
        try:
            page.wait_for_selector("#refNo", timeout=15000)
            page.locator("#refNo").click()
            page.type("#refNo", container_no, delay=150)
            human_delay(1, 1.5)

            page.locator("#containerTTSearchDetail").click()
            print("🔍 Search clicked")
        except Exception as e:
            print("⚠️ Failed to enter container number or click search")
            browser.close()
            return {"status": "error", "message": str(e), "container_number": container_no}

        # -------------------------------
        # ⏳ WAIT FOR RESULTS
        # -------------------------------
        human_delay(3, 5)

        try:
            found = False
            for _ in range(20):
                if page.locator(".results-wrapper #results").first.is_visible():
                    found = True
                    break
                time.sleep(1)

            if not found:
                with open("blocked_debug_pil.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                raise Exception("Results not loaded or container not found")

        except Exception as e:
            print(f"⚠️ Exception waiting for results: {str(e)}")
            try:
                with open("blocked_debug_pil.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            except:
                pass
            browser.close()
            return {
                "status": "error",
                "message": "Results not loaded or tracking not found",
                "container_number": container_no
            }

        # -------------------------------
        # ✅ DATA EXTRACTION
        # -------------------------------
        print("✅ Extracting data...")
        soup = BeautifulSoup(page.content(), "html.parser")

        results_div = soup.find("div", id="results")
        if not results_div:
            browser.close()
            return {"status": "not_found", "container_number": container_no}

        # --- Route summary table ---
        route_rows = []
        tables = results_div.find_all("div", class_="mypil-table")

        if tables:
            summary_table = tables[0].find("table")
            if summary_table:
                for row in summary_table.find("tbody").find_all("tr", class_="resultrow"):
                    cells = row.find_all("td")
                    if len(cells) == 4:
                        route_rows.append({
                            "arrival_delivery": cells[0].get_text(" ", strip=True),
                            "location": cells[1].get_text(" ", strip=True),
                            "vessel_voyage": cells[2].get_text(" ", strip=True),
                            "next_location": cells[3].get_text(" ", strip=True),
                        })

        # --- Container event history ---
        events = []
        if len(tables) > 1:
            event_table = tables[1].find("table")
            if event_table:
                for tbody in event_table.find_all("tbody"):
                    # skip the dark-blue header tbody
                    if "bg-darkblue" in tbody.get("class", []):
                        continue
                    for row in tbody.find_all("tr"):
                        cells = row.find_all("td")
                        if len(cells) == 5:
                            events.append({
                                "vessel": cells[0].get_text(strip=True),
                                "voyage": cells[1].get_text(strip=True),
                                "event_date": cells[2].get_text(strip=True),
                                "event_name": cells[3].get_text(strip=True),
                                "event_place": cells[4].get_text(strip=True),
                            })

        browser.close()

        if not route_rows and not events:
            return {"status": "not_found", "container_number": container_no}

        return {
            "status": "success",
            "container_number": container_no,
            "route_summary": route_rows,
            "events": events,
        }


# -------------------------------
# 🧪 RUN
# -------------------------------
if __name__ == "__main__":
    from pprint import pprint

    CONTAINER_ID = "HPCU5091307"
    result = get_pil_tracking(CONTAINER_ID, headless=False)

    pprint(result)
