import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Security
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel
from dotenv import load_dotenv

from script.visiwise_tracking import track_visiwise, track_maersk_visiwise
from script.maersk_tracker import get_maersk_tracking
from script.msc_tracker import get_msc_tracking
from script.cmacgm_tracker import get_cmacgm_tracking
from script.cosco_tracker import get_cosco_tracking
from script.goldstarline_tracker import get_goldstarline_tracking
from script.pil_tracker import get_pil_tracking
from script.one_tracker import get_one_tracking
from script.normalizer import normalize
from script.tracking_queue import tracking_queue


load_dotenv()

API_KEY = os.getenv("API_KEY", "changeme")

CARRIERS = {
    "maersk": get_maersk_tracking,
    "maersk_visiwise": track_maersk_visiwise,
    "msc": get_msc_tracking,
    "cmacgm": get_cmacgm_tracking,
    "cosco": get_cosco_tracking,
    "goldstarline": get_goldstarline_tracking,
    "pil": get_pil_tracking,
    "one": get_one_tracking,
}

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=True)

app = FastAPI(title="Container Tracking API")


class TrackRequest(BaseModel):
    carrier: str
    container_number: str
    source: Optional[str] = None


def _normalize_key(value: str) -> str:
    return value.lower().replace(" ", "").replace("-", "").replace("_", "")


def verify_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key


@app.post("/track")
def track(request: TrackRequest, key: str = Security(verify_api_key)):
    carrier = _normalize_key(request.carrier)
    source = _normalize_key(request.source) if request.source else ""

    if source == "visiwise":
        future = tracking_queue.submit(
            track_visiwise,
            request.container_number,
            request.carrier,
            headless=False,
        )
        result = future.result()
        return normalize("visiwise", result)

    tracker = CARRIERS.get(carrier)

    if not tracker:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported carrier '{request.carrier}'. "
                f"Supported: {list(CARRIERS.keys())}. "
                "Use source='visiwise' for Visiwise dashboard tracking with any supported line."
            ),
        )

    future = tracking_queue.submit(tracker, request.container_number, headless=False)
    result = future.result()
    return normalize(carrier, result)
