"""Writes data/data.json (read by the dashboard) and data/history.csv."""
import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import store
from .config import route_key


def export(conn, cfg, provider, now, out_dir):
    rk = route_key(cfg)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ser = store.series(conn, rk)
    last_ok = store.last_ok_run(conn, rk)
    flights = store.run_flights(conn, last_ok["id"]) if last_ok else []
    runs = [dict(r) for r in conn.execute("SELECT at,status,message,n_flights,cheapest FROM runs WHERE route_key=? "
                                          "ORDER BY id DESC LIMIT 60", (rk,))]
    last_run = runs[0] if runs else None
    interval = cfg["schedule"]["expected_interval_hours"]
    nxt = (datetime.fromisoformat(last_run["at"]) + timedelta(hours=interval)).isoformat() if last_run else None
    month = now.strftime("%Y-%m")
    prices = [p for _, p in ser]
    data = {
        "generated_at": now.isoformat(timespec="seconds"), "repo": os.environ.get("GITHUB_REPOSITORY", ""),
        "route": cfg["route"], "filters": cfg["filters"], "alerts_config": cfg["alerts"], "channels": cfg["channels"],
        "expected_interval_hours": interval, "source": {"name": provider.label, "type": "live search"},
        "latest": {"at": last_ok["at"], "cheapest": last_ok["cheapest"],
                   "previous": ser[-2][1] if len(ser) > 1 else None, "flights": [f.__dict__ | {"key": f.key} for f in flights]} if last_ok else None,
        "stats": {"lowest": min(prices) if prices else None, "highest": max(prices) if prices else None, "observations": len(prices)},
        "series": [{"t": t, "p": p} for t, p in ser],
        "last_run": last_run, "last_success": last_ok["at"] if last_ok else None, "next_check_approx": nxt,
        "quota": {"used": store.searches_this_month(conn, month), "cap": cfg["schedule"]["monthly_search_cap"]},
        "runs": runs,
        "alerts": [dict(r) for r in conn.execute("SELECT at,kind,price,prev_price,delivered FROM alerts WHERE route_key=? "
                                                 "ORDER BY id DESC LIMIT 20", (rk,))],
    }
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    (out_dir / "data.json").write_text(payload, encoding="utf-8")
    Path("docs").mkdir(exist_ok=True)
    Path("docs/data.json").write_text(payload, encoding="utf-8")   # fallback copy for the dashboard
    with open(out_dir / "history.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["observed_at", "route_key", "provider", "source_type", "airline", "flight_number", "dep_time",
                    "arr_time", "stops", "duration_min", "baggage", "price", "currency"])
        for r in conn.execute("SELECT observed_at,route_key,provider,source_type,airline,flight_number,dep_time,arr_time,"
                              "stops,duration_min,baggage,price,currency FROM observations ORDER BY id"):
            w.writerow(list(r))
    return data
