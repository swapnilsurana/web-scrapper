from seleniumbase import SB
from xvfbwrapper import Xvfb
import json
import os
import time, random

def human_delay(a=1.0, b=2.5):
    time.sleep(random.uniform(a, b))

def _cookies_path() -> str:
    # Stored relative to repo root when invoked from there.
    return os.path.join("script", ".cookies_cmacgm.json")

def _load_cookies_if_present(sb) -> None:
    path = _cookies_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        if isinstance(cookies, list):
            sb.driver.delete_all_cookies()
            for c in cookies:
                if isinstance(c, dict):
                    # Selenium will reject some keys; pass through as-is and ignore failures.
                    try:
                        sb.driver.add_cookie(c)
                    except Exception:
                        pass
    except Exception:
        return

def _save_cookies(sb) -> None:
    path = _cookies_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sb.driver.get_cookies(), f)
    except Exception:
        pass

def _is_datadome_blocked(sb) -> bool:
    try:
        src = sb.get_page_source()
    except Exception:
        return False
    # Typical DataDome interstitial/captcha indicators
    return (
        "captcha-delivery.com" in src
        or "DataDome" in src
        or "geo.captcha-delivery.com" in src
        or "ct.captcha-delivery.com" in src
    )

def get_cmacgm_tracking(container_no: str, headless: bool = False) -> dict:
    with Xvfb(width=1366, height=768, colordepth=24) as xvfb:
        with SB(
            uc=True,
            headless=headless,   # ✅ Works on VPS via Xvfb
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

            # DataDome CAPTCHA (served in an iframe) cannot be bypassed reliably in headless automation.
            # If running headed, allow a manual solve and persist cookies for later runs.
            if _is_datadome_blocked(sb):
                debug_path = "blocked_debug_cmacgm.html"
                try:
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                except Exception:
                    pass

                if headless:
                    return {
                        "status": "blocked",
                        "blocker": "datadome_captcha",
                        "message": "DataDome CAPTCHA detected. Run with headless=False and solve once to generate cookies, or use a proxy/residential IP.",
                        "container_number": container_no,
                        "debug_html": debug_path,
                    }

                print("🧩 DataDome CAPTCHA detected. Please solve it in the browser window.")
                # Try waiting for the real page to render after manual solve
                for _ in range(24):  # ~120s
                    human_delay(4.5, 5.5)
                    if not _is_datadome_blocked(sb):
                        try:
                            _save_cookies(sb)
                        except Exception:
                            pass
                        break
                else:
                    return {
                        "status": "blocked",
                        "blocker": "datadome_captcha",
                        "message": "CAPTCHA still present after waiting. Solve manually or switch IP/proxy.",
                        "container_number": container_no,
                        "debug_html": debug_path,
                    }

            # Wait for page to be ready (and dismiss common consent dialogs)
            try:
                sb.wait_for_ready_state_complete(timeout=20)
            except Exception:
                pass

            # Attempt cookie reuse (only helps if you've solved the CAPTCHA once)
            try:
                _load_cookies_if_present(sb)
                sb.open(url)
            except Exception:
                pass

            # Cookie / consent banners frequently block the input from rendering/clicking
            for sel in (
                "button#onetrust-accept-btn-handler",
                "button:contains('Accept all')",
                "button:contains('Accept All')",
                "button:contains('Accept')",
                "button:contains('I agree')",
                "button:contains('AGREE')",
            ):
                try:
                    sb.click_if_visible(sel)
                except Exception:
                    pass

            # CMA CGM has changed this DOM multiple times; try several stable selectors
            reference_selectors = [
                "#Reference",
                "#reference",
                "input#Reference",
                "input#reference",
                "input[name='Reference']",
                "input[name='reference']",
                "input[placeholder*='Container']",
                "input[placeholder*='container']",
                "input[type='text'][id*='Refer']",
                "input[type='text'][name*='Refer']",
            ]

            reference_selector = None
            for sel in reference_selectors:
                try:
                    sb.wait_for_element_visible(sel, timeout=6)
                    reference_selector = sel
                    break
                except Exception:
                    continue

            if not reference_selector:
                debug_path = "blocked_debug_cmacgm.html"
                try:
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                except Exception:
                    pass
                return {
                    "status": "error",
                    "message": "Failed to locate the container reference input (DOM changed or blocked).",
                    "container_number": container_no,
                    "debug_html": debug_path,
                }

            print(f"📦 Entering container number: {container_no}")
            sb.type(reference_selector, container_no)
            human_delay(0.5, 1.0)

            print("🔍 Clicking Search...")
            # Button selector also changes; try the known id first then fallbacks
            for btn_sel in (
                "#btnTracking",
                "button#btnTracking",
                "button:contains('Search')",
                "button:contains('TRACK')",
                "button:contains('Track')",
            ):
                try:
                    if sb.is_element_visible(btn_sel):
                        sb.click(btn_sel)
                        break
                except Exception:
                    continue

            # Wait for results
            print("⏳ Waiting for results...")
            try:
                sb.wait_for_element("section.tracking-details", timeout=20)
            except Exception:
                if sb.is_text_visible("No results"):
                    return {"status": "not_found", "container_number": container_no}
                debug_path = "blocked_debug_cmacgm.html"
                try:
                    with open(debug_path, "w", encoding="utf-8") as f:
                        f.write(sb.get_page_source())
                except Exception:
                    pass
                return {
                    "status": "error",
                    "message": "Results did not load (possibly blocked or DOM changed).",
                    "container_number": container_no,
                    "debug_html": debug_path,
                }

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