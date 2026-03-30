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
            "Port of Loading (POL)": None,
            "Sailing Date": None,
            "Port of Discharge (POD)": None,
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
            "Container Number": _safe(data.get("Container Number")) or raw.get("container_number"),
            "Port of Loading (POL)": None,
            "Sailing Date": None,
            "Port of Discharge (POD)": None,
            "Estimated Time of Arrival": None,
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


def normalize_pil(raw: dict) -> dict:
    if raw.get("status") != "success":
        return raw

    # Try to extract POL/POD/ETA from route_summary
    route = raw.get("route_summary", [])
    pol = route[0].get("location") if route else None
    pod = route[-1].get("location") if len(route) > 1 else None
    eta = route[-1].get("arrival_delivery") if len(route) > 1 else None
    vessel_voyage = route[0].get("vessel_voyage") if route else None

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


NORMALIZERS = {
    "maersk": normalize_maersk,
    "msc": normalize_msc,
    "cmacgm": normalize_cmacgm,
    "cosco": normalize_cosco,
    "goldstarline": normalize_goldstarline,
    "pil": normalize_pil,
}


def normalize(carrier: str, raw: dict) -> dict:
    fn = NORMALIZERS.get(carrier)
    if fn:
        return fn(raw)
    return raw
