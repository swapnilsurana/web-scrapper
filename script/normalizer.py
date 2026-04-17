"""
Normalizes raw tracker outputs into a unified response structure:
{
    "status": "success" | "not_found" | "error",
    "container_number": str,
    "basic_info": {
        "Container Number": str,
        "Port of Loading (POL)": str,
        "Sailing Date": str,
        "Port of Discharge (POD)": str,
        "Estimated Time of Arrival": str,
        "Container Type": str,
        "shipment_status": str
    },
    "activities/events": [
        {
            "Description": str,
            "Location": str,
            "Date": str,
            "Vessel / Voyage": str
        }
    ]
}
"""


def _safe(val):
    return val.strip() if isinstance(val, str) else (val or None)


def normalize_maersk(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    events = []
    for e in raw.get("events", []):
        events.append({
            "Description": _safe(e.get("event")),
            "Location": _safe(e.get("location_name")),
            "Date": _safe(e.get("date_time")),
            "Vessel / Voyage": _safe(e.get("location_terminal")),
        })

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "basic_info": {
            "Container Number": raw.get("container_number"),
            "Port of Loading (POL)": _safe(raw.get("Port of Loading (POL)")),
            "Sailing Date": None,
            "Port of Discharge (POD)": _safe(raw.get("Port of Discharge (POD)")),
            "Estimated Time of Arrival": _safe(raw.get("eta")),
            "Container Type": _safe(raw.get("container_type")),
            "shipment_status": _safe(raw.get("latest_event")),
        },
        "activities/events": events,
    }


def normalize_msc(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    data = raw.get("data", {})

    events = []
    for e in raw.get("events", []):
        events.append({
            "Description": _safe(e.get("description")),
            "Location": _safe(e.get("location")),
            "Date": _safe(e.get("date")),
            "Vessel / Voyage": _safe(e.get("detail")),
        })

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "basic_info": {
            "Container Number": data.get("Container Number") or raw.get("container_number"),
            "Port of Loading (POL)": _safe(data.get("Port of Load") or data.get("Shipped From")),
            "Sailing Date": None,
            "Port of Discharge (POD)": _safe(data.get("Port of Discharge") or data.get("Shipped To")),
            "Estimated Time of Arrival": _safe(data.get("POD ETA")),
            "Container Type": _safe(data.get("Type")),
            "shipment_status": _safe(data.get("Latest move")),
        },
        "activities/events": events,
    }


def normalize_cmacgm(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    events = []
    for e in raw.get("events", []):
        events.append({
            "Description": _safe(e.get("move")),
            "Location": _safe(e.get("location")),
            "Date": _safe(e.get("date")),
            "Vessel / Voyage": _safe(e.get("vessel_voyage")),
        })

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "basic_info": {
            "Container Number": raw.get("container_number"),
            "Port of Loading (POL)": _safe(raw.get("pol")),
            "Sailing Date": None,
            "Port of Discharge (POD)": _safe(raw.get("pod")),
            "Estimated Time of Arrival": _safe(raw.get("eta")),
            "Container Type": _safe(raw.get("container_type")),
            "shipment_status": _safe(raw.get("shipment_status")),
        },
        "activities/events": events,
    }


def normalize_cosco(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    data = raw.get("data", {})
    raw_events = data.get("events", [])

    # COSCO exposes ETA-like values as rows in the events table (e.g. "Last POD ETA").
    # We derive ETA by scanning event "dynamic_node" labels from newest to oldest.
    eta = None
    for e in reversed(raw_events or []):
        node = (e.get("dynamic_node") or "").strip().lower()
        if not node:
            continue
        if "eta" in node and ("pod" in node or "discharge" in node or "arrival" in node):
            eta = _safe(e.get("event_time")) or _safe(e.get("event_location")) or _safe(e.get("transport_mode"))
            if eta:
                break
        if node in {"eta", "estimated time of arrival"}:
            eta = _safe(e.get("event_time")) or _safe(e.get("event_location")) or _safe(e.get("transport_mode"))
            if eta:
                break
    eta = eta or _safe(data.get("Last POD ETA"))

    events = []
    for e in raw_events:
        events.append({
            "Description": _safe(e.get("dynamic_node")),
            "Location": _safe(e.get("event_location")),
            "Date": _safe(e.get("event_time")),
            "Vessel / Voyage": _safe(e.get("transport_mode")),
        })

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "basic_info": {
            "Container Number": raw.get("container_number"),
            "Port of Loading (POL)": None,
            "Sailing Date": None,
            "Port of Discharge (POD)": None,
            "Estimated Time of Arrival": eta,
            "Container Type": _safe(data.get("Size Type")),
            "shipment_status": None,
        },
        "activities/events": events,
    }


def normalize_goldstarline(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    basic = raw.get("basic_info", {})
    detailed = raw.get("detailed_info", {})
    container_data = raw.get("container_data", {})

    # Merge all info dicts for flexible key lookup
    merged = {**basic, **detailed, **container_data}

    def find(keys):
        for k in keys:
            for mk in merged:
                if k.lower() in mk.lower():
                    return _safe(merged[mk])
        return None

    events = []
    for a in raw.get("activities", []):
        events.append({
            "Description": _safe(a.get("Description") or a.get("Activity") or a.get("Event") or next(iter(a.values()), None)),
            "Location": _safe(a.get("Location") or a.get("Place") or a.get("Port")),
            "Date": _safe(a.get("Date") or a.get("Time") or a.get("Event Date")),
            "Vessel / Voyage": _safe(a.get("Vessel / Voyage") or a.get("Vessel") or a.get("Voyage")),
        })

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "basic_info": {
            "Container Number": find(["container number", "container no"]) or raw.get("container_number"),
            "Port of Loading (POL)": find(["port of loading", "pol", "origin"]),
            "Sailing Date": find(["sailing date", "etd", "departure"]),
            "Port of Discharge (POD)": find(["port of discharge", "pod", "destination"]),
            "Estimated Time of Arrival": find(["eta", "arrival", "estimated time"]),
            "Container Type": find(["container type", "size", "type"]),
            "shipment_status": find(["status", "shipment status", "latest"]),
        },
        "activities/events": events,
    }


def _extract_date(text):
    """Extract a date (DD-Mon-YYYY) from a string like 'TGLFW 23-Apr-2026'."""
    if not text:
        return None
    import re
    m = re.search(r'\d{1,2}-[A-Za-z]{3}-\d{4}', text)
    return m.group(0) if m else None


def normalize_pil(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    route = raw.get("route_summary", [])
    pol = route[0].get("location") if route else None
    pod = route[-1].get("location") if len(route) > 1 else None
    vessel_voyage = route[0].get("vessel_voyage") if route else None

    # ETA from the next_location date of the last route row
    eta = _extract_date(route[-1].get("next_location")) if route else None

    events = []
    for e in raw.get("events", []):
        vv = " / ".join(filter(None, [_safe(e.get("vessel")), _safe(e.get("voyage"))]))
        events.append({
            "Description": _safe(e.get("event_name")),
            "Location": _safe(e.get("event_place")),
            "Date": _safe(e.get("event_date")),
            "Vessel / Voyage": vv or None,
        })

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "basic_info": {
            "Container Number": raw.get("container_number"),
            "Port of Loading (POL)": _safe(pol),
            "Sailing Date": None,
            "Port of Discharge (POD)": _safe(pod),
            "Estimated Time of Arrival": _safe(eta),
            "Container Type": None,
            "shipment_status": None,
        },
        "activities/events": events,
    }


def normalize_one(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    summary = raw.get("summary", {})
    route = raw.get("route", {})
    sailing = raw.get("sailing_information", [])
    sail = sailing[0] if sailing else {}

    pol = _safe(sail.get("port_of_loading")) or _safe(route.get("place_of_receipt"))
    pod = _safe(sail.get("port_of_discharge")) or _safe(summary.get("pod_location")) or _safe(route.get("place_of_delivery"))
    eta = _safe(sail.get("arrival_time")) or _safe(summary.get("pod_vessel_arrival"))
    sailing_date = _safe(sail.get("departure_date"))
    vessel = _safe(sail.get("vessel"))

    events = []
    for e in raw.get("events", []):
        vv = _safe(e.get("vessel")) or vessel
        events.append({
            "Description": _safe(e.get("event")),
            "Location": _safe(e.get("location")),
            "Date": _safe(e.get("time")),
            "Vessel / Voyage": vv,
        })

    return {
        "status": "success",
        "container_number": raw.get("container_number"),
        "basic_info": {
            "Container Number": summary.get("container_no") or raw.get("container_number"),
            "Port of Loading (POL)": pol,
            "Sailing Date": sailing_date,
            "Port of Discharge (POD)": pod,
            "Estimated Time of Arrival": eta,
            "Container Type": _safe(summary.get("container_type")),
            "shipment_status": _safe(summary.get("latest_event")),
        },
        "activities/events": events,
    }


NORMALIZERS = {
    "maersk": normalize_maersk,
    "msc": normalize_msc,
    "cmacgm": normalize_cmacgm,
    "cosco": normalize_cosco,
    "goldstarline": normalize_goldstarline,
    "pil": normalize_pil,
    "one": normalize_one,
}


def normalize(carrier: str, raw: dict) -> dict:
    fn = NORMALIZERS.get(carrier)
    if fn:
        return fn(raw)
    return raw
