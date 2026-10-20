import copy
import os
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULTS = {
    "route": {"origin": "DEL", "destination": "CCU", "date": "2026-12-13", "trip_type": "one_way",
              "passengers": 1, "travel_class": "economy", "currency": "INR"},
    "filters": {"airlines": [], "max_stops": None},
    "provider": "serpapi",
    "alerts": {"target_price": 0, "min_change_abs": 300, "min_change_pct": 5, "notify_decrease": True,
               "notify_increase": True, "notify_target": True, "notify_lowest": True, "notify_recovery": True},
    "schedule": {"expected_interval_hours": 3, "monthly_search_cap": 240, "daily_summary_hour_ist": 21},
    "channels": {"email": True, "telegram": False, "whatsapp": False},
    "failure_alert_after": 3,
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path=None) -> dict:
    p = Path(path or os.environ.get("TRACKER_CONFIG") or ROOT / "config.yaml")
    cfg = _merge(DEFAULTS, yaml.safe_load(p.read_text(encoding="utf-8")))
    r = cfg["route"]
    r["origin"], r["destination"] = str(r["origin"]).upper(), str(r["destination"]).upper()
    r["date"] = str(r["date"])
    for k in ("origin", "destination"):
        if not re.fullmatch(r"[A-Z]{3}", r[k]):
            raise ValueError(f"route.{k} must be a 3-letter IATA code, got {r[k]!r}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]):
        raise ValueError("route.date must be YYYY-MM-DD")
    return cfg


def route_key(cfg) -> str:
    r = cfg["route"]
    return f"{r['origin']}-{r['destination']}-{r['date']}-{r['passengers']}pax-{r['travel_class']}-{r['trip_type']}"
