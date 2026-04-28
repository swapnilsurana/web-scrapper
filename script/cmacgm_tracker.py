from seleniumbase import SB
from xvfbwrapper import Xvfb
import json
import os
import time, random
import re
import html as _html

def human_delay(a=1.0, b=2.5):
    time.sleep(random.uniform(a, b))

_WS_RE = re.compile(r"\s+")

def _clean_text(s: str | None) -> str | None:
    if not s:
        return None
    s = _html.unescape(s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s or None

def _extract_eta_from_html(page_html: str) -> dict:
    """
    Extract ETA from the first `.timeline--item-eta` block.
    Expected structure:
      <div class="timeline--item-eta">
        ...
        <p>
          <span>Tue 28-APR-2026</span>
          <span class="... ico-time">07:35 AM</span>
        </p>
      </div>
    """
    out = {"eta": None, "eta_time": None, "eta_remaining": None}
    if not page_html:
        return out

    m = re.search(r'<div class="timeline--item-eta"[\s\S]*?</div>', page_html)
    if not m:
        return out
    block = m.group(0)

    # First <p> that is not ".remaining"
    pm = re.search(r"<p(?![^>]*\bremaining\b)[^>]*>([\s\S]*?)</p>", block)
    if pm:
        p_html = pm.group(1)
        spans = re.findall(r"<span[^>]*>([\s\S]*?)</span>", p_html)
        parts = [_clean_text(x) for x in spans]
        parts = [p for p in parts if p]
        if parts:
            out["eta"] = " ".join(parts)
            if len(parts) >= 2:
                out["eta_time"] = parts[-1]

    rm = re.search(r'<p[^>]*\bremaining\b[^>]*>([\s\S]*?)</p>', block)
    if rm:
        out["eta_remaining"] = _clean_text(rm.group(1))

    return out

def _extract_events_from_html(page_html: str) -> list[dict]:
    """
    Extract all kendo grid master rows under `gridTrackingDetails`.
    Works even when inner/outer grids have different column counts.
    """
    if not page_html:
        return []

    def g1(pattern: str, text: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    # CMA uses nested kendo grids (outer current + inner previous moves).
    # A "first grid block" slice is brittle; instead, scan all master rows in the full HTML
    # and keep only rows that look like real events.
    rows = re.findall(r'<tr[^>]*\bk-master-row\b[^>]*>([\s\S]*?)</tr>', page_html)
    events: list[dict] = []
    seen: set[tuple] = set()

    for row_html in rows:
        date_only = _clean_text(g1(r'<span[^>]*\bcalendar\b[^>]*>([\s\S]*?)</span>', row_html))
        time_txt = _clean_text(g1(r'<span[^>]*\btime\b[^>]*>([\s\S]*?)</span>', row_html))

        move_txt = _clean_text(g1(r'<span[^>]*\bcapsule\b[^>]*>([\s\S]*?)</span>', row_html))
        if not (date_only and move_txt):
            continue

        loc_cell = re.search(r'<td[^>]*\blocation\b[^>]*>([\s\S]*?)</td>', row_html)
        location_txt = None
        if loc_cell:
            # take the first visible label span in the cell
            loc_inner = loc_cell.group(1)
            location_txt = _clean_text(g1(r"<span[^>]*>([\s\S]*?)</span>", loc_inner) or loc_inner)

        vv_cell = re.search(r'<td[^>]*\bvesselVoyage\b[^>]*>([\s\S]*?)</td>', row_html)
        vessel_voyage_txt = _clean_text(vv_cell.group(1) if vv_cell else None)

        date_combined = None
        if date_only and time_txt:
            date_combined = f"{date_only} {time_txt}"
        elif date_only:
            date_combined = date_only

        event = {
            "date": date_combined,
            "date_only": date_only,
            "time": time_txt,
            "move": move_txt,
            "location": location_txt,
            "vessel_voyage": vessel_voyage_txt,
        }
        if any(v for v in event.values()):
            key = (date_only, time_txt, move_txt, location_txt, vessel_voyage_txt)
            if key not in seen:
                seen.add(key)
                events.append(event)

    return events

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
    # with Xvfb(width=1366, height=768, colordepth=24) as xvfb:
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

            # Expand "Previous Moves" in the tracking grid (often lazy-loaded on click)
            try:
                sb.wait_for_element("#gridTrackingDetails", timeout=12)
                expanders = sb.find_elements("#gridTrackingDetails a[aria-label*='Previous Moves'], #gridTrackingDetails a[aria-label*='Display Previous Moves']")
                for exp in expanders:
                    try:
                        sb.js_click(exp)
                        human_delay(0.4, 0.8)
                    except Exception:
                        try:
                            exp.click()
                            human_delay(0.4, 0.8)
                        except Exception:
                            pass
                # Give kendo time to fetch/render detail rows if needed
                human_delay(1.0, 2.0)
            except Exception:
                pass

            # Save a snapshot for debugging selector drift (best-effort)
            page_html = None
            try:
                page_html = sb.get_page_source()
                with open("script/last_cmacgm_result.html", "w", encoding="utf-8") as f:
                    f.write(page_html)
            except Exception:
                pass

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

            # ETA (robust): CMA sometimes renders ETA outside the POD timeline item.
            # Grab the first visible `.timeline--item-eta` block and read its date+time from the <p> spans.
            try:
                eta_src = page_html or sb.get_page_source()
                eta_extracted = _extract_eta_from_html(eta_src)
                result["eta"] = eta_extracted.get("eta") or result["eta"]
                result["eta_time"] = eta_extracted.get("eta_time") or result["eta_time"]
                result["eta_remaining"] = eta_extracted.get("eta_remaining") or result["eta_remaining"]
            except Exception:
                pass

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
                                eta_parts = [s.text.strip() for s in p_spans if s.text and s.text.strip()]
                                result["eta"] = " ".join(eta_parts) or None
                                # Time specifically (the span with ico-time class)
                                try:
                                    result["eta_time"] = eta_el.find_element("css selector", "span.ico-time").text.strip() or None
                                except:
                                    # fallback (some variants render time without the icon class)
                                    try:
                                        result["eta_time"] = eta_el.find_element("css selector", "p:not(.remaining) .time").text.strip() or None
                                    except:
                                        pass
                                # Remaining days
                                try:
                                    result["eta_remaining"] = eta_el.find_element("css selector", "p.remaining").text.strip()
                                except: pass
                            except: pass
                    except: pass
            except: pass

            # Events grid
            try:
                # CMA CGM renders an outer grid (current) + an inner grid (previous moves) that can be hidden
                # and can have a different column count. Scrape all master rows from all kendo grid tables.
                events_src = page_html or sb.get_page_source()
                result["events"] = _extract_events_from_html(events_src)
            except Exception:
                pass

            return result


if __name__ == "__main__":
    from pprint import pprint
    result = get_cmacgm_tracking("GESU1396924")
    pprint(result)