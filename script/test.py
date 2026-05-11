"""
Maersk container tracking scraper — GCP-safe version
Uses undetected-chromedriver + optional residential proxy.

Install deps:
    pip install undetected-chromedriver selenium

On GCP (headless display):
    sudo apt-get install -y xvfb
    Xvfb :99 -screen 0 1366x768x24 &
    export DISPLAY=:99

Proxy (residential — required on GCP to bypass IP blocks):
    Set PROXY env var:  export PROXY="http://user:pass@host:port"
    Or pass proxy= kwarg directly to get_maersk_tracking().
"""

import os
import time
import random
import logging
from typing import Optional

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    NoSuchElementException,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TRACKING_ROOT_URL = "https://www.maersk.com/tracking/"

# Maersk tracking widgets render inside open shadow roots; Selenium must pierce them.
_BOOKING_SELECT_SHADOW_JS = """
    function findBookingSelect(root) {
      if (!root) return null;
      if (root.querySelectorAll) {
        var sels = root.querySelectorAll("select");
        for (var i = 0; i < sels.length; i++) {
          var s = sels[i], hasO = false, hasA = false;
          for (var j = 0; j < s.options.length; j++) {
            var v = s.options[j].value;
            if (v === "ocean") hasO = true;
            if (v === "air") hasA = true;
          }
          if (hasO && hasA) return s;
        }
      }
      if (root.querySelectorAll) {
        var nodes = root.querySelectorAll("*");
        for (var k = 0; k < nodes.length; k++) {
          var n = nodes[k];
          if (n.shadowRoot) {
            var f = findBookingSelect(n.shadowRoot);
            if (f) return f;
          }
        }
      }
      return null;
    }
    var sel = findBookingSelect(document);
    if (!sel) return false;
    sel.value = "air";
    sel.dispatchEvent(new Event("input", { bubbles: true }));
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    sel.value = "ocean";
    sel.dispatchEvent(new Event("input", { bubbles: true }));
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
"""

_TRACKING_INPUT_SHADOW_JS = """
    function findInput(root) {
      if (!root) return null;
      var patterns = [
        'input[placeholder="BL or container number"]',
        'input[placeholder*="BL or container"]',
        'input[placeholder*="container number"]'
      ];
      for (var p = 0; p < patterns.length; p++) {
        try {
          var el = root.querySelector(patterns[p]);
          if (el) return el;
        } catch (e) {}
      }
      if (root.querySelectorAll) {
        var nodes = root.querySelectorAll("*");
        for (var i = 0; i < nodes.length; i++) {
          if (nodes[i].shadowRoot) {
            var hit = findInput(nodes[i].shadowRoot);
            if (hit) return hit;
          }
        }
      }
      return null;
    }
    return findInput(document);
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _delay(lo: float = 1.5, hi: float = 3.5) -> None:
    time.sleep(random.uniform(lo, hi))


def _build_driver(proxy: Optional[str] = None) -> uc.Chrome:
    """
    Build an undetected Chrome driver.
    proxy format:  "http://user:pass@host:port"
                   "socks5://user:pass@host:port"
    """
    options = uc.ChromeOptions()

    # ── Viewport / locale ──────────────────────────────────────────────────
    options.add_argument("--window-size=1366,768")
    options.add_argument("--lang=en-US")

    # ── Sandbox / shared-mem (required on GCP / Docker) ────────────────────
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    # ── Proxy ──────────────────────────────────────────────────────────────
    # if proxy:
    #     options.add_argument(f"--proxy-server={proxy}")
    #     log.info("🔀 Proxy enabled: %s", proxy.split("@")[-1])  # hide creds in log
    # else:
    #     log.warning(
    #         "⚠️  No proxy configured. GCP datacenter IPs are commonly blocked by "
    #         "Cloudflare. Set PROXY env var or pass proxy= kwarg."
    #     )

    # ── undetected-chromedriver patches Chrome binary automatically ─────────
    driver = uc.Chrome(
        options=options,
        use_subprocess=True,   # isolates each session in its own process
        version_main=146,     # auto-detect installed Chrome version
    )

    # Extra JS stealth patches on top of what uc already does
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
                // Remove leftover automation markers
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            """
        },
    )

    return driver


def _accept_cookies(driver: uc.Chrome) -> None:
    """Dismiss Cookie Information / Maersk cookie UI if present."""
    selectors = [
        "//*[@id='coiOverlay']//button[contains(., 'Allow all')]",
        "//*[@id='coiOverlay']//button[contains(., 'Accept all')]",
        "//*[@id='coiBanner']//button[contains(., 'Allow all')]",
        "//button[contains(., 'Allow all')]",
        "//button[contains(., 'Accept')]",
    ]
    for xpath in selectors:
        try:
            btn = WebDriverWait(driver, 6).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            btn.click()
            log.info("✅ Cookie banner dismissed")
            _delay(0.5, 1.0)
            return
        except TimeoutException:
            continue

    # Check iframes
    for frame in driver.find_elements(By.TAG_NAME, "iframe"):
        try:
            driver.switch_to.frame(frame)
            for xpath in selectors:
                try:
                    btn = driver.find_element(By.XPATH, xpath)
                    btn.click()
                    log.info("✅ Cookie banner dismissed (iframe)")
                    driver.switch_to.default_content()
                    _delay(0.5, 1.0)
                    return
                except NoSuchElementException:
                    continue
        except Exception:
            pass
        finally:
            driver.switch_to.default_content()

    # Cookie Information script sometimes renders buttons Selenium cannot reach
    try:
        clicked = driver.execute_script(
            """
            var ov = document.getElementById('coiOverlay');
            if (!ov) return false;
            var labels = ['Allow all', 'Accept all', 'Accept'];
            var buttons = ov.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
              var t = (buttons[i].innerText || '').trim();
              for (var j = 0; j < labels.length; j++) {
                if (t.indexOf(labels[j]) !== -1) {
                  buttons[i].click();
                  return true;
                }
              }
            }
            return false;
            """
        )
        if clicked:
            log.info("✅ Cookie overlay dismissed (script)")
            _delay(0.5, 1.0)
            return
    except Exception:
        pass

    log.info("ℹ️  No cookie banner found")


def _select_ocean_type(driver: uc.Chrome) -> None:
    """
    The tracking widget has a booking-type selector. Cycle air→ocean to ensure
    the correct search mode is active (mirrors maersk_tracker.py / live DOM).
    """
    wait = WebDriverWait(driver, 20)

    # Try native <select> first (scope to the tracking widget, not lang/footer selects)
    try:
        from selenium.webdriver.support.ui import Select
        sel_el = wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    "//select[.//option[@value='ocean'] and .//option[@value='air']]",
                )
            )
        )
        sel = Select(sel_el)
        sel.select_by_value("air")
        _delay(0.4, 0.8)
        sel.select_by_value("ocean")
        return
    except Exception:
        pass

    # Native <select> inside shadow roots (common for mc-* components)
    try:
        if driver.execute_script(_BOOKING_SELECT_SHADOW_JS):
            return
    except Exception:
        pass

    # Fallback: custom combobox — options are labelled "Air cargo" / "Ocean cargo"
    try:
        combos = driver.find_elements(By.CSS_SELECTOR, "[role='combobox']")
        combo = next((c for c in combos if c.is_displayed()), None)
        if combo is None:
            combo = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "[role='combobox']"))
            )
        combo.click()
        _delay(0.3, 0.6)
        driver.find_element(
            By.XPATH, "//*[@role='option'][contains(.,'Air cargo')]"
        ).click()
        _delay(0.4, 0.8)
        combo.click()
        _delay(0.3, 0.6)
        driver.find_element(
            By.XPATH, "//*[@role='option'][contains(.,'Ocean cargo')]"
        ).click()
    except Exception as exc:
        log.warning("Could not set booking type: %s", exc)
    finally:
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:
            pass
        _delay(0.2, 0.4)


def _find_tracking_input(driver: uc.Chrome, wait: WebDriverWait):
    """Resolve the BL/container field (light DOM or open shadow roots)."""
    locators = [
        (By.XPATH, "//*[@placeholder='BL or container number']"),
        (By.CSS_SELECTOR, 'input[placeholder*="BL or container"]'),
        (By.CSS_SELECTOR, 'input[placeholder*="container number"]'),
    ]
    last_exc: Optional[Exception] = None
    for by, selector in locators:
        try:
            return wait.until(EC.presence_of_element_located((by, selector)))
        except TimeoutException as exc:
            last_exc = exc
            continue
    try:
        return wait.until(lambda d: d.execute_script(_TRACKING_INPUT_SHADOW_JS))
    except TimeoutException as exc:
        raise TimeoutException("Could not find tracking input") from exc


def _wait_for_results(driver: uc.Chrome, timeout: int = 25) -> bool:
    """
    Poll until container card OR 'No results found' appears.
    Returns True if something loaded, False if timed out.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.find_elements(By.CSS_SELECTOR, '[data-test="container"]'):
            return True
        if driver.find_elements(By.XPATH, "//*[contains(text(),'No results found')]"):
            return True
        time.sleep(1)
    return False


def _safe_text(driver: uc.Chrome, css: str, index: int = 0) -> Optional[str]:
    els = driver.find_elements(By.CSS_SELECTOR, css)
    if len(els) > index:
        txt = els[index].get_attribute("innerText") or els[index].text
        return txt.strip() or None
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_maersk_tracking(
    container_no: str,
    proxy: Optional[str] = None,
) -> dict:
    """
    Fetch Maersk tracking data for a container / BL number.

    Args:
        container_no:  e.g. "MRKU0580031"
        proxy:         Residential proxy URI — strongly recommended on cloud VMs.
                       Falls back to PROXY env var if not provided.
                       Format: "http://user:pass@host:port"
    Returns:
        dict with status, container info, POL/POD, events list.
    """
    proxy = proxy or os.getenv("PROXY")

    driver = _build_driver(proxy=proxy)

    try:
        # ── Warm-up: visit homepage first to look organic ───────────────────
        log.info("🔄 Session warm-up: maersk.com")
        driver.get("https://www.maersk.com/")
        WebDriverWait(driver, 60).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        _delay(3, 5)
        _accept_cookies(driver)
        _delay(1, 2)

        # Subtle mouse-like scroll
        driver.execute_script("window.scrollBy(0, 300)")
        _delay(1, 2)

        # ── Navigate to tracking ────────────────────────────────────────────
        log.info("🚢 Opening tracking page")
        driver.get(TRACKING_ROOT_URL)
        WebDriverWait(driver, 60).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        _delay(2, 4)
        _accept_cookies(driver)
        _delay(1, 2)

        # ── Set booking type ────────────────────────────────────────────────
        _select_ocean_type(driver)
        _delay(0.8, 1.5)

        # ── Type container number ───────────────────────────────────────────
        wait = WebDriverWait(driver, 20)
        inp = _find_tracking_input(driver, wait)
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", inp)
        _delay(0.2, 0.5)
        try:
            inp.click()
        except Exception:
            driver.execute_script("arguments[0].click();", inp)
        _delay(0.3, 0.7)
        # Type character-by-character to mimic human input
        for ch in container_no:
            inp.send_keys(ch)
            time.sleep(random.uniform(0.05, 0.15))
        _delay(0.5, 1.0)

        # ── Click Track ─────────────────────────────────────────────────────
        track_btn = wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, '[data-test="track-button"]'))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", track_btn)
        _delay(0.2, 0.5)
        _accept_cookies(driver)
        _delay(0.3, 0.6)
        try:
            track_btn.click()
        except ElementClickInterceptedException:
            _accept_cookies(driver)
            _delay(0.3, 0.6)
            try:
                track_btn.click()
            except ElementClickInterceptedException:
                driver.execute_script(
                    """
                    var o = document.getElementById('coiOverlay');
                    if (o) { o.style.display = 'none'; }
                    """,
                )
                driver.execute_script("arguments[0].click();", track_btn)
        log.info("🔍 Tracking %s …", container_no)

        # ── Wait for results ─────────────────────────────────────────────────
        loaded = _wait_for_results(driver)
        if not loaded:
            with open("blocked_debug.html", "w", encoding="utf-8") as fh:
                fh.write(driver.page_source)
            raise RuntimeError(
                "Timed out waiting for results — page saved to blocked_debug.html. "
                "Most likely cause: IP blocked. Try a residential proxy."
            )

        # ── No results ───────────────────────────────────────────────────────
        if driver.find_elements(By.XPATH, "//*[contains(text(),'No results found')]"):
            return {"status": "not_found", "container_number": container_no}

        # ── Parse results ────────────────────────────────────────────────────
        result: dict = {"status": "success"}

        result["Port of Loading (POL)"]  = _safe_text(driver, '[data-test="track-from-value"]')
        result["Port of Discharge (POD)"] = _safe_text(driver, '[data-test="track-to-value"]')

        # Container number + type from header spans
        try:
            spans = driver.find_elements(
                By.CSS_SELECTOR,
                '[data-test="container"] header mc-text-and-icon:first-child span',
            )
            result["container_number"] = spans[0].text.strip() if len(spans) > 0 else None
            result["container_type"]   = spans[2].text.strip() if len(spans) > 2 else None
        except Exception:
            result["container_number"] = None
            result["container_type"]   = None

        # Last updated
        try:
            lu = driver.find_element(By.CSS_SELECTOR, '[data-test="last-updated"]')
            result["last_updated"] = lu.text.strip() or None
        except NoSuchElementException:
            result["last_updated"] = None

        # ETA
        result["eta"] = _safe_text(driver, '[data-test="container-eta"] span.labels slot', index=1)

        # Latest event / location
        result["latest_event"] = _safe_text(
            driver, '[data-test="container-location"] [slot="sublabel"]'
        )

        # Transport plan events
        events = []
        try:
            items = driver.find_elements(
                By.CSS_SELECTOR,
                '[data-test="transport-plan"] li.transport-plan__list__item',
            )
            for item in items:
                location_name = location_terminal = milestone_name = milestone_date = None

                try:
                    strong = item.find_element(By.CSS_SELECTOR, ".location strong")
                    location_name = strong.text.strip()
                    full_text = item.find_element(By.CSS_SELECTOR, ".location").text.strip()
                    location_terminal = full_text.replace(location_name, "").strip() or None
                except NoSuchElementException:
                    pass

                try:
                    ms = item.find_element(By.CSS_SELECTOR, '[data-test="milestone"]')
                    spans = ms.find_elements(By.TAG_NAME, "span")
                    if spans:
                        milestone_name = spans[0].text.strip()
                    date_el = ms.find_elements(By.CSS_SELECTOR, '[data-test="milestone-date"]')
                    if date_el:
                        milestone_date = date_el[0].text.strip()
                except NoSuchElementException:
                    pass

                events.append({
                    "location_name":     location_name,
                    "location_terminal": location_terminal,
                    "event":             milestone_name,
                    "date_time":         milestone_date,
                })
        except Exception as exc:
            log.warning("Event parsing error: %s", exc)

        result["events"] = events
        return result

    finally:
        driver.quit()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pprint import pprint

    # Set your residential proxy here or via env:  export PROXY="http://user:pass@host:port"
    result = get_maersk_tracking("MSKU1236969")
    pprint(result)