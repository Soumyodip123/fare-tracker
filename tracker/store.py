"""SQLite storage. The DB file lives in the repo (data/tracker.db) and is committed back after each run,
which is how history persists between ephemeral GitHub Actions runners."""
import os
import sqlite3

from .models import Flight

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY, route_key TEXT NOT NULL, at TEXT NOT NULL, provider TEXT NOT NULL,
  status TEXT NOT NULL, message TEXT DEFAULT '', n_flights INTEGER DEFAULT 0, cheapest INTEGER);
CREATE TABLE IF NOT EXISTS observations(
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id), route_key TEXT NOT NULL,
  observed_at TEXT NOT NULL, provider TEXT NOT NULL, source_type TEXT NOT NULL DEFAULT 'live',
  airline TEXT, flight_number TEXT, dep_time TEXT, arr_time TEXT, stops INTEGER, duration_min INTEGER,
  baggage TEXT, price INTEGER NOT NULL, currency TEXT NOT NULL, link TEXT);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY, route_key TEXT, at TEXT, kind TEXT, price INTEGER, prev_price INTEGER,
  delivered TEXT, summary TEXT);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_runs_route ON runs(route_key, id);
"""
# Only runs with status 'ok' ever have observations; failures are logged in `runs` but never become prices.


def connect(path) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def meta_get(conn, key, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def meta_set(conn, key, value):
    conn.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
    conn.commit()


def add_run(conn, route_key, at, provider, status, message, flights=()):
    cheapest = min((f.price for f in flights), default=None)
    cur = conn.execute("INSERT INTO runs(route_key,at,provider,status,message,n_flights,cheapest) VALUES(?,?,?,?,?,?,?)",
                       (route_key, at, provider, status, message, len(flights), cheapest))
    rid = cur.lastrowid
    conn.executemany(
        "INSERT INTO observations(run_id,route_key,observed_at,provider,airline,flight_number,dep_time,arr_time,"
        "stops,duration_min,baggage,price,currency,link) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(rid, route_key, at, provider, f.airline, f.flight_number, f.dep_time, f.arr_time, f.stops,
          f.duration_min, f.baggage, f.price, f.currency, f.link) for f in flights])
    conn.commit()
    return rid


def _flights(rows):
    return [Flight(r["airline"], r["flight_number"], r["dep_time"], r["arr_time"], r["stops"], r["duration_min"],
                   r["baggage"], r["price"], r["currency"], r["link"]) for r in rows]


def last_ok_run(conn, route_key):
    return conn.execute("SELECT * FROM runs WHERE route_key=? AND status='ok' ORDER BY id DESC LIMIT 1",
                        (route_key,)).fetchone()


def run_flights(conn, run_id):
    return _flights(conn.execute("SELECT * FROM observations WHERE run_id=? ORDER BY price", (run_id,)).fetchall())


def past_mins(conn, route_key):
    return [r["cheapest"] for r in conn.execute(
        "SELECT cheapest FROM runs WHERE route_key=? AND status='ok' ORDER BY id", (route_key,))]


def series(conn, route_key):
    return [(r["at"], r["cheapest"]) for r in conn.execute(
        "SELECT at, cheapest FROM runs WHERE route_key=? AND status='ok' ORDER BY id", (route_key,))]


def searches_this_month(conn, month):
    """Searches that SerpApi counts as successful (ok / empty result) in this UTC month, across all routes."""
    return conn.execute("SELECT COUNT(*) c FROM runs WHERE at LIKE ? AND status IN ('ok','no_results','no_matching')",
                        (month + "%",)).fetchone()["c"]


def add_alert(conn, route_key, at, kind, price, prev, delivered, summary):
    conn.execute("INSERT INTO alerts(route_key,at,kind,price,prev_price,delivered,summary) VALUES(?,?,?,?,?,?,?)",
                 (route_key, at, kind, price, prev, delivered, summary))
    conn.commit()
