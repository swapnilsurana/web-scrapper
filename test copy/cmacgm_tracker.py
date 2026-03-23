from seleniumbase import SB
from xvfbwrapper import Xvfb
import time, random

def human_delay(a=1.0, b=2.5):
    time.sleep(random.uniform(a, b))

def get_cmacgm_tracking(container_no: str, headless: bool = False) -> dict:
    with Xvfb(width=1366, height=768, colordepth=24) as xvfb:
        with SB(
            uc=True,
            headless=False,   # ✅ Works on VPS via Xvfb
            locale_code="en",
        ) as sb:

            url = "https://www.cma-cgm.com/ebusiness/tracking/search"
            print(f"🔄 Opening tracking page for: {container_no}")

            # ✅ Use uc_open instead of uc_open_with_reconnect
            sb.uc_open(url)
            human_delay(3, 5)

            # ✅ Handle Cloudflare challenge if present
            if "challenge" in sb.get_current_url() or "Just a moment" in sb.get_page_source():
                print("⚠️ Cloudflare detected, attempting bypass...")
                sb.uc_gui_click_captcha()
                human_delay(3, 5)

            # Wait for page to be ready
            sb.wait_for_element("#Reference", timeout=20)
            print(f"📦 Entering container number: {container_no}")

            sb.type("#Reference", container_no)
            human_delay(0.5, 1.0)

            print("🔍 Clicking Search...")
            sb.click("#btnTracking")

            # Wait for results
            print("⏳ Waiting for results...")
            try:
                sb.wait_for_element("section.tracking-details", timeout=20)
            except Exception:
                if sb.is_text_visible("No results"):
                    return {"status": "not_found", "container_number": container_no}
                raise Exception("Results did not load — possible block")

            result = {
                "status": "success",
                "container_number": container_no,
                "container_type": None,
                "shipment_status": None,
                "pol": None,
                "pod": None,
                "eta": None,
                "eta_time": None,
                "eta_remaining": None,
                "events": [],
            }

            try:
                result["container_number"] = sb.get_text(".resume-filter li strong")
            except: pass

            try:
                # e.g. "45G1" + "(40HC)" → "45G1 (40HC)"
                strongs = sb.find_elements(".ico-container strong")
                result["container_type"] = " ".join(s.text.strip() for s in strongs if s.text.strip())
            except: pass

            try:
                result["shipment_status"] = sb.get_text("header .capsule.primary")
            except: pass

            try:
                pol_item = sb.find_element(".timeline--items .timeline--item .capsule")
                # Walk timeline items to find POL and POD
                items = sb.find_elements(".timeline--items .timeline--item")
                for item in items:
                    try:
                        capsule = item.find_element("css selector", ".capsule")
                        label = capsule.text.strip()
                        location = item.find_element("css selector", ".timeline--item-description span strong").text.strip()
                        if label == "POL":
                            result["pol"] = location
                        elif label == "POD":
                            result["pod"] = location
                            try:
                                eta_el = item.find_element("css selector", ".timeline--item-eta")
                                # Date + time from the <p> spans (excludes .remaining)
                                p_spans = eta_el.find_elements("css selector", "p:not(.remaining) span")
                                result["eta"] = " ".join(s.text.strip() for s in p_spans if s.text.strip())
                                # Time specifically (the span with ico-time class)
                                try:
                                    result["eta_time"] = eta_el.find_element("css selector", "span.ico-time").text.strip()
                                except: pass
                                # Remaining days
                                try:
                                    result["eta_remaining"] = eta_el.find_element("css selector", "p.remaining").text.strip()
                                except: pass
                            except: pass
                    except: pass
            except: pass

            # Events grid
            try:
                sb.wait_for_element("#gridTrackingDetails tbody tr", timeout=10)
                rows = sb.find_elements("#gridTrackingDetails tbody tr[role='row']")

                for row in rows:
                    cells = row.find_elements("tag name", "td")
                    if len(cells) >= 6:
                        event = {
                            "date": cells[2].text.strip() or None,
                            "move": cells[3].text.strip() or None,
                            "location": cells[4].text.strip() or None,
                            "vessel_voyage": cells[5].text.strip() or None,
                        }
                        if any(event.values()):
                            result["events"].append(event)
            except: pass

            return result


if __name__ == "__main__":
    from pprint import pprint
    result = get_cmacgm_tracking("CMAU8629550")
    pprint(result)