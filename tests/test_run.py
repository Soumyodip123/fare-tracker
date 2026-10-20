import json
from datetime import datetime, timedelta, timezone

import pytest

from tracker import config as C, store
from tracker.models import Flight
from tracker.providers.base import NoResults, ProviderError
from tracker.providers.serpapi import SerpApiProvider
from tracker.run import run_once

T0 = datetime(2026, 10, 20, 6, 0, tzinfo=timezone.utc)   # 11:30 IST, before the summary hour


class Fake:
    name, label = "fake", "Fake (test)"

    def __init__(self, *results):
        self.results = list(results)

    def search(self, cfg):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return [Flight("IndiGo", "6E 2001", "2026-12-13 06:00", "2026-12-13 08:15", 0, 135, "n/a", p, link="https://x") for p in r]


@pytest.fixture
def env(tmp_path):
    cfg = C.load()
    cfg["alerts"]["target_price"] = 0
    sent = []
    conn = store.connect(tmp_path / "t.db")
    return cfg, conn, sent, (lambda s, t: (sent.append((s, t)) or {"email": "ok"}))


def step(env, provider, minutes):
    cfg, conn, sent, send = env
    return run_once(cfg, conn, provider, send, T0 + timedelta(minutes=minutes))


def subjects(sent):
    return [s for s, _ in sent]


def test_confirmation_then_decrease_then_no_duplicate(env):
    cfg, conn, sent, _ = env
    p = Fake([6500], [5900], [5900])
    step(env, p, 0)
    assert subjects(sent) == ["✈ Flight tracker is on"]
    step(env, p, 180)
    assert len(sent) == 2 and "dropped" in sent[1][0].lower() and "−₹600" in sent[1][1] and "-9.23%" in sent[1][1].replace("−", "-")
    assert "fares can change" in sent[1][1].lower() or "Fares can change" in sent[1][1]
    step(env, p, 360)                      # unchanged price: no repeat alert
    assert len(sent) == 2


def test_failed_search_is_never_recorded_as_price(env):
    cfg, conn, sent, _ = env
    step(env, Fake(ProviderError("boom"), NoResults("none")), 0)
    step(env, Fake(NoResults("none")), 180)
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0
    assert store.series(conn, C.route_key(cfg)) == []


def test_failure_email_sent_once_after_threshold(env):
    cfg, conn, sent, _ = env
    p = Fake(*[ProviderError("down")] * 6)
    for i in range(6):
        step(env, p, i * 180)
    assert sum("failing" in s for s in subjects(sent)) == 1


def test_recovery_after_failure_resumes_and_compares_to_last_good_price(env):
    cfg, conn, sent, _ = env
    p = Fake([6500], ProviderError("x"), [5900])
    for i in range(3):
        step(env, p, i * 180)
    assert any("dropped" in s.lower() for s in subjects(sent))


def test_quota_cap_blocks_search(env):
    cfg, conn, sent, _ = env
    cfg["schedule"]["monthly_search_cap"] = 1
    p = Fake([6500], [5900])
    assert step(env, p, 0) == "ok"
    assert step(env, p, 180) == "quota_skipped" and len(p.results) == 1


def test_airline_filter(env):
    cfg, conn, sent, _ = env
    cfg["filters"]["airlines"] = ["Air India"]
    assert step(env, Fake([6500]), 0) == "no_matching"


def test_daily_summary_once_per_day(env):
    cfg, conn, sent, _ = env
    p = Fake([6500], [6500], [6500])
    step(env, p, 0)
    step(env, p, 600)    # 16:30 IST+ -> 21:30 IST? 06:00Z+10h = 16:00Z = 21:30 IST
    step(env, p, 660)
    assert sum("Daily" in s for s in subjects(sent)) == 1


def test_serpapi_parse_documented_shape():
    data = {"search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?q=x"},
            "best_flights": [{"flights": [{"departure_airport": {"time": "2026-12-13 06:10"}, "arrival_airport": {"time": "2026-12-13 08:25"},
                                           "airline": "IndiGo", "flight_number": "6E 2345", "extensions": ["Carry-on bag included"]}],
                              "total_duration": 135, "price": 5900}],
            "other_flights": [{"flights": [{"airline": "X"}], "price": None}]}
    fl = SerpApiProvider.parse(data, "INR")
    assert len(fl) == 1 and fl[0].price == 5900 and fl[0].stops == 0 and "Carry-on" in fl[0].baggage and fl[0].link
    with pytest.raises(NoResults):
        SerpApiProvider.parse({"error": "Google Flights hasn't returned any results for this query."}, "INR")
    with pytest.raises(ProviderError):
        SerpApiProvider.parse({"error": "Invalid API key."}, "INR")
