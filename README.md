# Web Scrapper — Shipping Container Tracker

Playwright-based scrapers for tracking shipping containers across multiple carriers, exposed via a FastAPI wrapper.

## Supported Carriers

| Carrier | Script | API value |
|---|---|---|
| Maersk | `script/maersk_tracker.py` | `maersk` |
| COSCO | `script/cosco_tracker.py` | `cosco` |
| MSC | `script/msc_tracker.py` | `msc` |
| Gold Star Line | `script/goldstarline_tracker.py` | `goldstarline` |
| CMA CGM | `script/cmacgm_tracker.py` | `cmacgm` |
| PIL | `script/pil_tracker.py` | `pil` |
| ONE (Ocean Network Express) | `script/one_tracker.py` | `one` |

## Setup

```bash
python -m venv venv
source venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

Set your API key in `.env`:

```
API_KEY=your-secret-key-here
```

Optional: limit how many tracking jobs can run at once (additional requests will wait in a queue):

```
MAX_CONCURRENT_TRACKING_JOBS=3
```

## API

Start the server:

```bash
uvicorn main:app --reload
```

### POST /track

Tracks a container for a given carrier. Requires an `X-API-Key` header.

**Request**

```json
{
  "carrier": "pil",
  "container_number": "HPCU5091307"
}
```

**Headers**

```
X-API-Key: your-secret-key-here
```

**Example**

```bash
curl -X POST http://localhost:8000/track \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-secret-key-here" \
  -d '{"carrier": "pil", "container_number": "HPCU5091307"}'
```

**Response**

```json
{
  "status": "success | not_found | error",
  "container_number": "...",
  "...": "carrier-specific fields"
}
```

Supported `carrier` values: `maersk`, `msc`, `cmacgm`, `cosco`, `goldstarline`, `pil`, `one`

## Direct Script Usage

Each tracker can also be run or imported directly:

```bash
python script/maersk_tracker.py
python script/pil_tracker.py
```

```python
from script.pil_tracker import get_pil_tracking

result = get_pil_tracking("HPCU5091307", headless=True)
print(result)
```

## Notes

- Set `headless=False` during development to watch the browser
- Debug HTML files (`blocked_debug_*.html`) are saved on failure and git-ignored
- Scrapers include human-like delays to reduce bot detection
