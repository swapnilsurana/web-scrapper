"""
Visiwise container tracking:
- Public page: https://www.visiwise.co/tracking/container/maersk/ (weekly free limit).
- Dashboard (authenticated): https://app.visiwise.co — login, Track Shipment, carrier dropdown, parse tracking page.

Set credentials in environment (recommended: add to your local .env, never commit):
  VISIWISE_EMAIL=...
  VISIWISE_PASSWORD=...
"""

from __future__ import annotations

import os
import random
import re
import time
from typing import Any, Optional

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

VISIWISE_MAERSK_URL = "https://www.visiwise.co/tracking/container/maersk/"
VISIWISE_APP_ROOT = "https://app.visiwise.co"
VISIWISE_LOGIN_NEXT_SHIPMENT = f"{VISIWISE_APP_ROOT}/login/?next=/shipment/new/"


def human_delay(a: float = 1.5, b: float = 3.5) -> None:
    time.sleep(random.uniform(a, b))


def handle_cookie_popup(page) -> None:
    for text in ("Got it", "Allow all", "Allow All", "Accept All", "Accept"):
        try:
            btn = page.get_by_role("button", name=text).first
            if btn.is_visible(timeout=2500):
                btn.click()
                return
        except Exception:
            pass


def _save_debug(page, path: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(page.content())
    except OSError:
        pass


def _visible_usage_limit_message(soup: BeautifulSoup) -> Optional[str]:
    el = soup.select_one("#tracking-usage-limitation-message")
    if not el:
        return None
    styles = el.get("style") or ""
    if "display:none" in styles.replace(" ", "") or "display: none" in styles:
        return None
    text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
    if not text:
        return None
    if "reached the limitation" in text.lower():
        return text
    return text


def _collect_error_messages(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    for sel in (".ui.message.negative", ".ui.error.message", ".field.error"):
        for el in soup.select(sel):
            t = el.get_text(" ", strip=True)
            if t and t not in out:
                out.append(t)
    return out


def _parse_tracking_blocks(soup: BeautifulSoup) -> dict[str, Any]:
    data: dict[str, Any] = {"tables": [], "sections": []}

    for table in soup.select("table"):
        rows = []
        for tr in table.select("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.select("th, td")]
            if any(cells):
                rows.append(cells)
        if rows:
            data["tables"].append(rows)

    for header in soup.select("h2, h3, .ui.header"):
        title = header.get_text(" ", strip=True)
        if not title or len(title) > 120:
            continue
        parent = header.find_parent("div")
        if not parent:
            continue
        chunk = parent.get_text(" ", strip=True)
        if chunk and title.lower() not in ("maersk container tracking", "container tracking"):
            if len(chunk) > len(title) + 20:
                data["sections"].append({"title": title, "text": chunk[:2000]})

    return data


def _wait_post_login(page, timeout_ms: int = 120_000) -> bool:
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        if "/login" not in page.url:
            return True
        page.wait_for_timeout(500)
    return "/login" not in page.url


def _dismiss_tracking_tips(page) -> None:
    try:
        btn = page.get_by_role("button", name="Got it")
        if btn.is_visible(timeout=2000):
            btn.click()
            page.wait_for_timeout(400)
    except Exception:
        pass


def _parse_movements_table(soup: BeautifulSoup) -> list[dict[str, str]]:
    rows_out: list[dict[str, str]] = []
    table = soup.select_one("table.movements-new-table")
    if not table:
        return rows_out
    for tr in table.select("tbody tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds[1:5]]
        if len(cells) < 4:
            continue
        date_s, loc_s, event_s, mode_s = cells[0], cells[1], cells[2], cells[3]
        if date_s.lower() == "date" and "location" in loc_s.lower():
            continue
        if any([date_s, loc_s, event_s, mode_s]):
            rows_out.append({
                "date": date_s,
                "location": loc_s,
                "event": event_s,
                "transport_mode": mode_s,
            })
    return rows_out


def _soup_label_value(soup: BeautifulSoup, label: str) -> Optional[str]:
    pat = re.compile(r"^\s*" + re.escape(label) + r"\s*$", re.I)
    for el in soup.find_all(string=pat):
        parent = el.parent
        if not parent:
            continue
        chunk = parent.find_parent()
        if chunk:
            text = chunk.get_text(" ", strip=True)
            if text.startswith(label):
                rest = text[len(label) :].strip()
                if rest:
                    one_line = rest.split("  ")[0].split("ETA")[0].strip()
                    return (one_line or rest)[:500]
        nxt = parent.find_next_sibling()
        if nxt:
            v = nxt.get_text(" ", strip=True)
            if v:
                return v[:500]
    return None


def _parse_tracking_overview(soup: BeautifulSoup) -> dict[str, Any]:
    overview: dict[str, Any] = {}
    for key, label in (
        ("last_status", "LAST STATUS"),
        ("eta_pod", "ETA (at POD)"),
        ("pol", "POL"),
        ("pod", "POD"),
        ("atd", "ATD"),
    ):
        v = _soup_label_value(soup, label)
        if v:
            overview[key] = v
    return overview


def get_visiwise_maersk_tracking(
    container_no: str,
    *,
    headless: bool = False,
    carrier: str = "MAERSK",
    debug_html_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Submit container number on the public Visiwise Maersk page.

    ``carrier`` is the internal option value for #id_carrier (e.g. MAERSK, MSC).
    """
    container_no = (container_no or "").strip().upper()
    out: dict[str, Any] = {
        "status": "error",
        "source": "visiwise_public",
        "url": VISIWISE_MAERSK_URL,
        "container_number": container_no,
    }

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

        page.goto(VISIWISE_MAERSK_URL, timeout=90000, wait_until="domcontentloaded")
        page.wait_for_load_state("domcontentloaded")
        human_delay(2, 3)
        handle_cookie_popup(page)
        human_delay(0.5, 1.0)

        try:
            page.locator("#id_specifier").wait_for(state="visible", timeout=20000)
        except Exception as e:
            out["message"] = f"Tracking form not found: {e}"
            if debug_html_path:
                _save_debug(page, debug_html_path)
            browser.close()
            return out

        page.locator("#id_timezone").wait_for(state="attached", timeout=10000)
        try:
            page.wait_for_function(
                "() => document.querySelector('#id_timezone')?.value?.length > 0",
                timeout=15000,
            )
        except Exception:
            page.evaluate(
                """() => {
                const el = document.querySelector('#id_timezone');
                if (el && !el.value) {
                  el.value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
                }
            }"""
            )

        page.locator("#id_specifier").click()
        page.locator("#id_specifier").fill(container_no)
        human_delay(0.3, 0.7)

        try:
            page.locator("#id_carrier").select_option(value=carrier)
        except Exception:
            pass

        human_delay(0.3, 0.6)

        with page.expect_navigation(wait_until="domcontentloaded", timeout=90000):
            page.locator("#containerTrackingForm").locator(
                'input[type="submit"][value="Track Container"]'
            ).click()

        human_delay(2, 3)
        final_url = page.url
        out["final_url"] = final_url

        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        browser.close()

    if "app.visiwise.co" in final_url:
        out["status"] = "redirect"
        out["message"] = "Redirected to Visiwise app; login may be required to view results."
        return out

    limit_msg = _visible_usage_limit_message(soup)
    if limit_msg:
        out["status"] = "rate_limited"
        out["message"] = limit_msg
        return out

    errors = _collect_error_messages(soup)
    if errors:
        joined = " | ".join(errors[:5])
        if any("invalid" in e.lower() or "required" in e.lower() for e in errors):
            out["status"] = "validation_error"
            out["message"] = joined
            return out

    parsed = _parse_tracking_blocks(soup)
    if parsed["tables"] or parsed["sections"]:
        out["status"] = "success"
        out["parsed"] = parsed
        return out

    body_text = soup.body.get_text("\n", strip=True) if soup.body else ""
    lowered = body_text.lower()
    if re.search(r"\bnot found\b|no results|invalid container", lowered):
        out["status"] = "not_found"
        out["message"] = "No tracking result found for this container on the response page."
        return out

    if debug_html_path:
        try:
            with open(debug_html_path, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError:
            pass

    out["status"] = "unknown"
    out["message"] = (
        "Could not infer result layout. Save HTML with debug_html_path or inspect final_url."
    )
    out["page_text_preview"] = body_text[:2500] if body_text else ""
    return out


def track_visiwise_dashboard(
    container_no: str,
    *,
    carrier: str = "Maersk",
    email: Optional[str] = None,
    password: Optional[str] = None,
    headless: bool = True,
    debug_html_path: Optional[str] = None,
) -> dict[str, Any]:
    """
    Log into app.visiwise.co, open Track Shipment (/shipment/new/), set line + container, submit,
    then parse the tracking details page.

    Credentials: pass ``email`` / ``password``, or set env ``VISIWISE_EMAIL`` / ``VISIWISE_PASSWORD``.
    Loads ``.env`` via ``load_dotenv()`` when this function runs.
    """
    load_dotenv()
    email = email or os.getenv("VISIWISE_EMAIL", "").strip()
    password = password or os.getenv("VISIWISE_PASSWORD", "")

    container_no = (container_no or "").strip().upper()
    out: dict[str, Any] = {
        "status": "error",
        "source": "visiwise_dashboard",
        "container_number": container_no,
        "carrier": carrier,
    }

    if not email or not password:
        out["message"] = (
            "Missing credentials: set VISIWISE_EMAIL and VISIWISE_PASSWORD "
            "(e.g. in .env) or pass email= and password=."
        )
        return out

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
            viewport={"width": 1400, "height": 900},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page.goto(VISIWISE_LOGIN_NEXT_SHIPMENT, timeout=120000, wait_until="domcontentloaded")
        page.locator("#email").wait_for(state="visible", timeout=90000)
        human_delay(1.5, 2.5)
        handle_cookie_popup(page)
        page.locator("#email").fill(email)
        page.locator("#password").fill(password)
        page.get_by_role("button", name="Sign in").click()

        if not _wait_post_login(page, timeout_ms=120_000):
            out["status"] = "login_failed"
            out["message"] = "Still on login after sign-in — check credentials or 2FA."
            out["final_url"] = page.url
            if debug_html_path:
                _save_debug(page, debug_html_path)
            browser.close()
            return out

        human_delay(1.0, 2.0)
        page.goto(
            f"{VISIWISE_APP_ROOT}/shipment/new/",
            timeout=120_000,
            wait_until="domcontentloaded",
        )
        page.locator("#containerNumber").wait_for(state="visible", timeout=90_000)
        human_delay(0.5, 1.2)

        try:
            page.locator("#line").click(timeout=10000)
            page.wait_for_timeout(400)
            page.get_by_role("option", name=carrier, exact=True).click(timeout=10000)
        except Exception as e:
            out["status"] = "error"
            out["message"] = f"Could not select carrier “{carrier}”: {e}"
            if debug_html_path:
                _save_debug(page, debug_html_path)
            browser.close()
            return out

        page.locator("#containerNumber").fill(container_no)
        human_delay(0.4, 0.9)
        page.get_by_role("button", name="Track Container").click()

        try:
            page.wait_for_url("**/shipments/*/tracking/", timeout=120_000)
        except Exception as e:
            out["status"] = "error"
            out["message"] = f"Did not reach tracking page: {e}"
            out["final_url"] = page.url
            if debug_html_path:
                _save_debug(page, debug_html_path)
            browser.close()
            return out

        human_delay(2, 3.5)
        _dismiss_tracking_tips(page)

        final_url = page.url
        html = page.content()
        browser.close()

    out["final_url"] = final_url
    soup = BeautifulSoup(html, "html.parser")
    movements = _parse_movements_table(soup)
    overview = _parse_tracking_overview(soup)

    out["status"] = "success"
    out["overview"] = overview
    out["movements"] = movements

    if debug_html_path:
        try:
            with open(debug_html_path, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError:
            pass

    return out


def track_maersk_visiwise(container_no: str, headless: bool = True) -> dict[str, Any]:
    """
    Maersk tracking for the HTTP API: uses Visiwise dashboard (env credentials) and
    returns the same shape as ``script.maersk_tracker.get_maersk_tracking`` on success
    so ``normalize_maersk`` stays unchanged.
    """
    raw = track_visiwise_dashboard(container_no, carrier="Maersk", headless=True)
    if raw.get("status") != "success":
        err_status = raw.get("status", "error")
        if err_status == "not_found":
            out_status = "not_found"
        else:
            out_status = "error"
        return {
            "status": out_status,
            "container_number": raw.get("container_number") or (container_no or "").strip().upper(),
            "message": raw.get("message"),
            "source": raw.get("source"),
            "final_url": raw.get("final_url"),
            "visiwise_status": err_status,
        }

    overview = raw.get("overview") or {}
    movements = raw.get("movements") or []
    events: list[dict[str, Any]] = []
    for m in movements:
        events.append({
            "location_name": m.get("location"),
            "location_terminal": m.get("transport_mode"),
            "event": m.get("event"),
            "date_time": m.get("date"),
        })

    last_evt = None
    if movements:
        last_evt = movements[-1].get("event")

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "container_type": None,
        "last_updated": None,
        "eta": overview.get("eta_pod"),
        "latest_event": overview.get("last_status") or last_evt,
        "Port of Loading (POL)": overview.get("pol"),
        "Port of Discharge (POD)": overview.get("pod"),
        "events": events,
    }


if __name__ == "__main__":
    import argparse
    from pprint import pprint

    parser = argparse.ArgumentParser(description="Visiwise public or dashboard container tracking")
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Use app.visiwise.co (needs VISIWISE_EMAIL + VISIWISE_PASSWORD in env or .env)",
    )
    parser.add_argument("--container", default="MRKU0580031", help="Container number")
    parser.add_argument("--carrier", default="Maersk", help="Shipping line label in the dashboard dropdown")
    parser.add_argument("--headed", action="store_true", help="Run browser with visible window")
    args = parser.parse_args()

    load_dotenv()

    if args.dashboard:
        pprint(
            track_visiwise_dashboard(
                args.container,
                carrier=args.carrier,
                headless=not args.headed,
            )
        )
    elif os.getenv("VISIWISE_EMAIL") and os.getenv("VISIWISE_PASSWORD"):
        pprint(track_visiwise_dashboard(args.container, carrier=args.carrier, headless=not args.headed))
    else:
        pprint(get_visiwise_maersk_tracking(args.container, headless=not args.headed))
