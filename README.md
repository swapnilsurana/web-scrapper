# Web Scrapper — Shipping Container Tracker

Playwright-based scrapers for tracking shipping containers across multiple carriers.

## Supported Carriers

| Carrier | Script |
|---|---|
| Maersk | `script/maersk_tracker.py` |
| COSCO | `script/cosco_tracker.py` |
| MSC | `script/msc_tracker.py` |
| Gold Star Line | `script/goldstarline_tracker.py` |

## Setup

```bash
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

## Usage

Each tracker exposes a single function you can import or run directly.

```bash
python script/maersk_tracker.py
python script/cosco_tracker.py
python script/goldstarline_tracker.py
python script/msc_tracker.py
```

To use in your own code:

```python
from script.maersk_tracker import get_maersk_tracking
from script.goldstarline_tracker import get_goldstarline_tracking

result = get_maersk_tracking("PONU2003175", headless=True)
print(result)
```

## Return Shape

All trackers return a dict with at minimum:

```json
{
  "status": "success | not_found",
  "container_number": "...",
  ...carrier-specific fields...
}
```

On failure, a `blocked_debug_*.html` file is saved in the project root for inspection.

## Notes

- Set `headless=False` during development to watch the browser
- Debug HTML files (`blocked_debug_*.html`) are git-ignored
- Scrapers include human-like delays to reduce bot detection
