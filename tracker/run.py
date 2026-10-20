import argparse
import json
import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from . import config as C, report, store
from .alerts import evaluate
from .models import money
from .notify import DISCLAIMER, _ist, compose_alerts, make_dispatcher
from .providers import get_provider
from .providers.base import NoResults, ProviderError

IST = ZoneInfo("Asia/Kolkata")
FAIL = {"error", "no_results", "no_matching"}
log = logging.getLogger("tracker")


def apply_filters(flights, cfg):
    f = cfg["filters"]
    names = [a.lower() for a in (f.get("airlines") or [])]
    out = [x for x in flights if (not names or any(n in x.airline.lower() for n in names))
           and (f.get("max_stops") is None or x.stops <= f["max_stops"])]
    return out


def _delivered(res):
    return any(v == "ok" for v in res.values())


def run_once(cfg, conn, provider, send, now=None):
    now = now or datetime.now(timezone.utc)
    at, rk, cur = now.isoformat(timespec="seconds"), C.route_key(cfg), cfg["route"]["currency"]
    ist = now.astimezone(IST)
    if date.fromisoformat(cfg["route"]["date"]) < ist.date():
        log.warning("Travel date %s has passed; nothing to track.", cfg["route"]["date"])
        return "expired"
    if store.searches_this_month(conn, at[:7]) >= cfg["schedule"]["monthly_search_cap"]:
        store.add_run(conn, rk, at, provider.name, "quota_skipped", "Monthly search cap reached; no search made")
        return "quota_skipped"

    status, msg, flights = "ok", "", []
    try:
        flights = provider.search(cfg)
    except NoResults as e:
        status, msg = "no_results", str(e)
    except ProviderError as e:
        status, msg = "error", str(e)
    except Exception as e:
        status, msg = "error", f"Unexpected {type(e).__name__}"
    if status == "ok":
        flights = apply_filters(flights, cfg)
        if not flights:
            status, msg = "no_matching", "No flights matched your airline/stops filters"

    prev_run = store.last_ok_run(conn, rk) if status == "ok" else None
    prev = store.run_flights(conn, prev_run["id"]) if prev_run else None
    pmins = store.past_mins(conn, rk) if status == "ok" else []
    store.add_run(conn, rk, at, provider.name, status, msg, flights if status == "ok" else [])
    log.info("Run status=%s %s", status, msg)

    # failure tracking: one email after N consecutive failures, re-armed by the next success
    if status in FAIL:
        n = int(store.meta_get(conn, "consec_fail", 0)) + 1
        store.meta_set(conn, "consec_fail", n)
        if n >= cfg["failure_alert_after"] and store.meta_get(conn, "fail_notified") != "1":
            res = send("⚠ Flight tracker: searches are failing",
                       f"{n} consecutive runs produced no usable price.\nLatest reason: {msg}\n\n"
                       "No prices were recorded for these runs. Monitoring will keep retrying; "
                       "you will not get another failure email until it recovers.")
            if _delivered(res):
                store.meta_set(conn, "fail_notified", "1")
    elif status == "ok":
        store.meta_set(conn, "consec_fail", 0)
        store.meta_set(conn, "fail_notified", "0")

    sent_start = False
    if status == "ok":
        state = json.loads(store.meta_get(conn, f"state:{rk}", "{}"))
        alerts, st = evaluate(flights, prev, pmins, cfg["alerts"], state)
        store.meta_set(conn, f"state:{rk}", json.dumps(st))
        if alerts:
            subject, text = compose_alerts(alerts, cfg, at, provider.label)
            res = send(subject, text)
            for a in alerts:
                store.add_alert(conn, rk, at, a.kind, a.flight.price, a.base.price if a.base else None,
                                json.dumps(res), subject)

    if not store.meta_get(conn, f"started:{rk}"):
        r = cfg["route"]
        body = [f"Monitoring started for {r['origin']} → {r['destination']} on {r['date']} "
                f"({r['passengers']} passenger, {r['travel_class']}, {cur}).",
                f"Checks run about every {cfg['schedule']['expected_interval_hours']} hours via GitHub Actions "
                "(scheduled runs can be delayed)."]
        if status == "ok":
            c = min(flights, key=lambda f: f.price)
            body += [f"First observed fare: {money(c.price, cur)} — {c.label}", f"Observed {_ist(at)} via {provider.label}",
                     f"Search link: {c.link}" if c.link else ""]
        else:
            body.append(f"First check did not return a price: {msg}")
        res = send("✈ Flight tracker is on", "\n".join(body) + "\n\n" + DISCLAIMER)
        if _delivered(res):
            store.meta_set(conn, f"started:{rk}", at)
            sent_start = True

    ser = store.series(conn, rk)
    today = ist.date().isoformat()
    if (ser and not sent_start and ist.hour >= cfg["schedule"]["daily_summary_hour_ist"]
            and store.meta_get(conn, f"summary:{rk}") != today):
        prices = [p for _, p in ser]
        latest = prices[-1]
        day_ago = [p for t, p in ser if (now - datetime.fromisoformat(t)).total_seconds() >= 86400]
        ref = day_ago[-1] if day_ago else prices[0]
        ref_label = "24h ago" if day_ago else "first observation"
        chg = latest - ref
        body = (f"Daily summary: {cfg['route']['origin']} → {cfg['route']['destination']}, {cfg['route']['date']}\n"
                f"Latest cheapest fare: {money(latest, cur)}\nLowest observed: {money(min(prices), cur)}\n"
                f"Highest observed: {money(max(prices), cur)}\n"
                f"Change vs {ref_label}: {money(chg, cur, True)} ({chg / ref * 100:+.2f}%)\n"
                f"Observations: {len(prices)}\nLast successful check: {_ist(ser[-1][0])}\n\n{DISCLAIMER}")
        if _delivered(send("✈ Daily fare summary", body)):
            store.meta_set(conn, f"summary:{rk}", today)
    return status


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print notifications instead of sending")
    ap.add_argument("--config")
    ap.add_argument("--db", default="data/tracker.db")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = C.load(args.config)
    provider = get_provider(cfg["provider"])
    conn = store.connect(args.db)
    try:
        status = run_once(cfg, conn, provider, make_dispatcher(cfg, args.dry_run))
    finally:
        report.export(conn, cfg, provider, datetime.now(timezone.utc), "data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
