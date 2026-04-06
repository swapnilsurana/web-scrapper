import time
import random
from bs4 import BeautifulSoup
from seleniumbase import SB
from xvfbwrapper import Xvfb


def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def get_pil_tracking(container_no: str, headless: bool = False) -> dict:
    url = "https://www.pilship.com/digital-solutions/?tab=customer&id=track-trace&label=containerTandT"

    with Xvfb(width=1366, height=768, colordepth=24) as xvfb:
        with SB(
            uc=True,
            headless=headless,
            locale_code="en",
        ) as sb:

            print(f"🔄 Opening tracking page for: {container_no}")
            sb.uc_open(url)
            human_delay(3, 5)

            if "challenge" in sb.get_current_url() or "Just a moment" in sb.get_page_source():
                print("⚠️ Cloudflare detected, attempting bypass...")
                sb.uc_gui_click_captcha()
                human_delay(3, 5)

            try:
                sb.wait_for_element("#refNo", timeout=20)
            except Exception as e:
                print("⚠️ Failed to find container input")
                with open("blocked_debug_pil.html", "w", encoding="utf-8") as f:
                    f.write(sb.get_page_source())
                return {"status": "error", "message": str(e), "container_number": container_no}

            print(f"📝 Entering container: {container_no}")
            sb.type("#refNo", container_no)
            human_delay(1, 1.5)

            print("🔍 Clicking Search...")
            sb.click("#containerTTSearchDetail")
            human_delay(3, 5)

            print("⏳ Waiting for results...")
            try:
                sb.wait_for_element_visible(".results-wrapper #results", timeout=25)
            except Exception:
                if sb.is_text_visible("No results") or sb.is_text_visible("no record"):
                    return {"status": "not_found", "container_number": container_no}
                print("⚠️ Failed to load expected content — saving debug")
                with open("blocked_debug_pil.html", "w", encoding="utf-8") as f:
                    f.write(sb.get_page_source())
                return {
                    "status": "error",
                    "message": "Blocked or DOM changed",
                    "container_number": container_no,
                }

            print("✅ Extracting data...")
            soup = BeautifulSoup(sb.get_page_source(), "html.parser")

            results_div = soup.find("div", id="results")
            if not results_div:
                return {"status": "not_found", "container_number": container_no}

            route_rows = []
            tables = results_div.find_all("div", class_="mypil-table")

            if tables:
                summary_table = tables[0].find("table")
                if summary_table:
                    tbody = summary_table.find("tbody")
                    if tbody:
                        for row in tbody.find_all("tr", class_="resultrow"):
                            cells = row.find_all("td")
                            if len(cells) == 4:
                                route_rows.append({
                                    "arrival_delivery": cells[0].get_text(" ", strip=True),
                                    "location": cells[1].get_text(" ", strip=True),
                                    "vessel_voyage": cells[2].get_text(" ", strip=True),
                                    "next_location": cells[3].get_text(" ", strip=True),
                                })

            events = []
            if len(tables) > 1:
                event_table = tables[1].find("table")
                if event_table:
                    for tbody in event_table.find_all("tbody"):
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

            if not route_rows and not events:
                return {"status": "not_found", "container_number": container_no}

            return {
                "status": "success",
                "container_number": container_no,
                "route_summary": route_rows,
                "events": events,
            }


if __name__ == "__main__":
    from pprint import pprint

    result = get_pil_tracking("HPCU5091307")
    pprint(result)
