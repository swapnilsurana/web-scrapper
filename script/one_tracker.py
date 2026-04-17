import time
import random
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from xvfbwrapper import Xvfb


def human_delay(a=1.5, b=3.5):
    time.sleep(random.uniform(a, b))


def handle_cookie_popup(page):
    print("🔄 Handling cookie popup...")
    for text in ["Allow All", "Accept All", "Accept"]:
        try:
            btn = page.locator(f'button:has-text("{text}")').first
            if btn.is_visible(timeout=3000):
                btn.click()
                print("✅ Cookie accepted")
                return
        except Exception:
            pass
    print("ℹ️ No cookie popup found")


def get_one_tracking(container_no: str, headless: bool = False) -> dict:
    url = (
        f"https://ecomm.one-line.com/one-ecom/manage-shipment"
        f"/cargo-tracking?trakNoParam={container_no}"
    )

    with Xvfb(width=1366, height=768, colordepth=24) as xvfb:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
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

            print(f"🚢 Opening ONE Line tracking: {container_no}")
            page.goto(url, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_load_state("domcontentloaded")
            human_delay(3, 5)

            handle_cookie_popup(page)
            human_delay(1, 2)

            try:
                page.wait_for_selector(
                    '[data-testid="tnt-cargo-tracking-table"]',
                    timeout=30000,
                )
                print("✅ Tracking table loaded")
            except Exception as e:
                print("⚠️ Failed to load tracking table")
                _save_debug(page, "blocked_debug_one.html")
                browser.close()
                return {
                    "status": "error",
                    "message": str(e),
                    "container_number": container_no,
                }

            human_delay(2, 3)

            try:
                page.wait_for_selector(
                    '[data-testid="tnt-cargo-tracking-table-row"]',
                    timeout=15000,
                )
            except Exception:
                browser.close()
                return {"status": "not_found", "container_number": container_no}

            # Wait for the expanded detail to render
            human_delay(2, 3)

            # Click the row expand arrow if the detail section isn't visible
            try:
                detail_tab = page.locator('[data-testid="tnt-quick-action-tab"]')
                if not detail_tab.is_visible(timeout=3000):
                    expand_arrow = page.locator(
                        '[data-testid="tnt-cargo-tracking-table-row"] '
                        'svg[class*="arrow"]'
                    ).first
                    if expand_arrow.is_visible():
                        expand_arrow.click()
                        human_delay(2, 3)
            except Exception:
                pass

            print("✅ Extracting data...")
            soup = BeautifulSoup(page.content(), "html.parser")
            browser.close()

            return _parse_tracking(soup, container_no)


def _save_debug(page, filename: str):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception:
        pass


def _parse_tracking(soup: BeautifulSoup, container_no: str) -> dict:
    table = soup.find(attrs={"data-testid": "tnt-cargo-tracking-table"})
    if not table:
        return {"status": "not_found", "container_number": container_no}

    row = table.find(attrs={"data-testid": "tnt-cargo-tracking-table-row"})
    if not row:
        return {"status": "not_found", "container_number": container_no}

    summary = _extract_summary(row)
    sailing_info = _extract_sailing_info(soup)
    route_info = _extract_route_info(soup)
    events = _extract_events(soup)

    if not summary and not events:
        return {"status": "not_found", "container_number": container_no}

    return {
        "status": "success",
        "container_number": container_no,
        "summary": summary,
        "route": route_info,
        "sailing_information": sailing_info,
        "events": events,
    }


def _extract_summary(row) -> dict:
    summary = {}

    cells = row.find_all(attrs={"role": "cell"})

    # Cell 0: Booking Ref
    if len(cells) > 0:
        booking_span = cells[0].find("span", class_=lambda c: c and "ds-text-body" in c)
        if booking_span:
            summary["booking_ref"] = booking_span.get_text(strip=True)

    # Cell 1: Container No. + type/weight
    if len(cells) > 1:
        container_cell = cells[1]
        container_span = container_cell.find(
            "span", class_=lambda c: c and "text-underline" in (c or "")
        )
        if container_span:
            summary["container_no"] = container_span.get_text(strip=True)

        detail_div = container_cell.find(
            "div", class_=lambda c: c and "ds-text-body-small" in (c or "")
        )
        if detail_div:
            spans = detail_div.find_all("span")
            if len(spans) >= 1:
                summary["container_type"] = spans[0].get_text(strip=True)
            if len(spans) >= 2:
                summary["weight"] = spans[1].get_text(strip=True)

    # Cell 2: Latest Place
    if len(cells) > 2:
        place_cell = cells[2]
        location_div = place_cell.find(
            attrs={"data-testid": "tnt-place-location-name-0"}
        )
        if location_div:
            summary["latest_place"] = location_div.get_text(strip=True)

        yard_div = place_cell.find(
            attrs={"data-testid": "tnt-place-yard-name-0"}
        )
        if yard_div:
            summary["latest_terminal"] = yard_div.get_text(strip=True)

    # Cell 3: Latest Event Status / Time
    if len(cells) > 3:
        event_cell = cells[3]
        divs = event_cell.find_all(
            "div", class_=lambda c: c and "ds-text-body" in (c or "")
        )
        if divs:
            summary["latest_event"] = divs[0].get_text(strip=True)
        date_container = event_cell.find(
            "div", class_=lambda c: c and "event-date-container" in (c or "")
        )
        if date_container:
            spans = date_container.find_all("span")
            date_parts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
            summary["latest_event_time"] = " ".join(date_parts)

    # Cell 4: POD / Vessel Arrival
    if len(cells) > 4:
        pod_cell = cells[4]
        pod_divs = pod_cell.find_all("div", recursive=False)
        if pod_divs:
            cell_content = pod_cell.find(
                "div", class_=lambda c: c and "cell-default-content" in (c or "")
            )
            if cell_content:
                first_div = cell_content.find("div", recursive=False)
                if first_div:
                    summary["pod_location"] = first_div.get_text(strip=True)

                date_container = cell_content.find(
                    "div",
                    class_=lambda c: c and "event-date-container" in (c or ""),
                )
                if date_container:
                    spans = date_container.find_all("span")
                    date_parts = [
                        s.get_text(strip=True)
                        for s in spans
                        if s.get_text(strip=True) and not s.find("svg")
                    ]
                    summary["pod_vessel_arrival"] = " ".join(date_parts)

    # Cell 5: Seal No.
    if len(cells) > 5:
        seal_div = cells[5].find(attrs={"data-testid": "tnt-seal-no-item-0"})
        if seal_div:
            summary["seal_no"] = seal_div.get_text(strip=True)

    return summary


def _extract_route_info(soup: BeautifulSoup) -> dict:
    route = {}
    place_items = soup.find_all(
        "div", class_=lambda c: c and "place-item" in (c or "")
    )
    for item in place_items:
        title_div = item.find(
            "div", class_=lambda c: c and "title" in (c or "")
        )
        body_div = item.find(
            "div", class_=lambda c: c and "body" in (c or "")
        )
        if title_div and body_div:
            key = title_div.get_text(strip=True)
            val = body_div.get_text(" ", strip=True)
            if "receipt" in key.lower():
                route["place_of_receipt"] = val
            elif "delivery" in key.lower():
                route["place_of_delivery"] = val
    return route


def _extract_sailing_info(soup: BeautifulSoup) -> list:
    sailing_rows = []

    table_body = soup.find(
        "div", class_=lambda c: c and "SailingTable_body" in (c or "")
    )
    if not table_body:
        return sailing_rows

    vessel_td = table_body.find(
        "div", class_=lambda c: c and "SailingTable_vessel-td" in (c or "")
    )
    pol_td = table_body.find(
        "div",
        class_=lambda c: c and "SailingTable_port-of-loading-td" in (c or ""),
    )
    dep_td = table_body.find(
        "div",
        class_=lambda c: c and "SailingTable_departure-date-td" in (c or ""),
    )
    pod_td = table_body.find(
        "div",
        class_=lambda c: c and "SailingTable_port-of-discharge-td" in (c or ""),
    )
    arr_td = table_body.find(
        "div",
        class_=lambda c: c and "SailingTable_arrival-time-td" in (c or ""),
    )

    entry = {}
    if vessel_td:
        link = vessel_td.find("a")
        entry["vessel"] = link.get_text(strip=True) if link else vessel_td.get_text(strip=True)
    if pol_td:
        entry["port_of_loading"] = pol_td.get_text(strip=True)
    if dep_td:
        date_container = dep_td.find(
            "div", class_=lambda c: c and "event-date-container" in (c or "")
        )
        if date_container:
            spans = date_container.find_all("span")
            parts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True) and not s.find("svg")]
            entry["departure_date"] = " ".join(parts)
    if pod_td:
        entry["port_of_discharge"] = pod_td.get_text(strip=True)
    if arr_td:
        date_container = arr_td.find(
            "div", class_=lambda c: c and "event-date-container" in (c or "")
        )
        if date_container:
            spans = date_container.find_all("span")
            parts = [s.get_text(strip=True) for s in spans if s.get_text(strip=True) and not s.find("svg")]
            entry["arrival_time"] = " ".join(parts)

    if entry:
        sailing_rows.append(entry)

    return sailing_rows


def _extract_events(soup: BeautifulSoup) -> list:
    events = []

    event_table = soup.find(
        "table", class_=lambda c: c and "EventTable_table-container" in (c or "")
    )
    if not event_table:
        return events

    rows = event_table.find_all("tr", class_=lambda c: c and "EventTable_table-row" in (c or ""))

    current_location = None
    current_terminal = None

    for row in rows:
        location_td = row.find(
            "td",
            class_=lambda c: c and "table-col-relative" in (c or ""),
        )
        event_td = row.find(
            "td",
            class_=lambda c: c and "table-col" in (c or "") and "table-col-relative" not in (c or ""),
        )

        if location_td:
            country_div = location_td.find(
                "div", class_=lambda c: c and "country-name" in (c or "")
            )
            terminal_span = location_td.find(
                "span", class_=lambda c: c and "terminal-name" in (c or "")
            )

            if country_div:
                loc_text = country_div.get_text(strip=True)
                if loc_text:
                    current_location = loc_text
            if terminal_span:
                is_hidden = "hidden" in (terminal_span.get("class", []) or [])
                if isinstance(terminal_span.get("class"), str):
                    is_hidden = "hidden" in terminal_span["class"]
                else:
                    is_hidden = any(
                        "hidden" in cls for cls in (terminal_span.get("class") or [])
                    )
                term_text = terminal_span.get_text(strip=True)
                if term_text and not is_hidden:
                    current_terminal = term_text

        if not event_td:
            continue

        event_details = event_td.find(
            "div", class_=lambda c: c and "cop-event-details" in (c or "")
        )
        if not event_details:
            continue

        event_name_div = event_details.find(
            "div", class_=lambda c: c and "event-name-vessel-group" in (c or "")
        )
        event_name = ""
        vessel_name = None
        if event_name_div:
            first_div = event_name_div.find("div", recursive=False)
            if first_div:
                event_name = first_div.get_text(strip=True)

            vessel_link = event_name_div.find("a")
            if vessel_link:
                vessel_name = vessel_link.get_text(strip=True)

        event_time = ""
        date_container = event_details.find(
            "div", class_=lambda c: c and "event-date-container" in (c or "")
        )
        if date_container:
            spans = date_container.find_all("span")
            parts = [
                s.get_text(strip=True)
                for s in spans
                if s.get_text(strip=True) and not s.find("svg")
            ]
            event_time = " ".join(parts)

        is_actual = False
        is_estimate = False
        if date_container:
            svgs = date_container.find_all("svg")
            for svg in svgs:
                rect = svg.find("rect")
                if rect:
                    fill = rect.get("fill", "")
                    if fill == "#00506D":
                        is_actual = True
                    elif fill == "#BD0F72":
                        is_estimate = True

        schedule_type = "actual" if is_actual else "estimate" if is_estimate else "unknown"

        event_entry = {
            "event": event_name,
            "time": event_time,
            "location": current_location,
            "terminal": current_terminal,
            "schedule_type": schedule_type,
        }
        if vessel_name:
            event_entry["vessel"] = vessel_name

        events.append(event_entry)

    return events


if __name__ == "__main__":
    from pprint import pprint

    CONTAINER_ID = "CK6LI0058700"
    result = get_one_tracking(CONTAINER_ID, headless=False)
    pprint(result)
