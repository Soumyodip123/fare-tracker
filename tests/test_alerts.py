from tracker.alerts import evaluate
from tracker.models import Flight, money

RULES = {"min_change_abs": 300, "min_change_pct": 5, "notify_decrease": True, "notify_increase": True,
         "notify_target": True, "notify_lowest": True, "notify_recovery": True, "target_price": 0}


def F(price, num="6E 2001", dep="2026-12-13 06:00", airline="IndiGo"):
    return Flight(airline, num, dep, "2026-12-13 08:15", 0, 135, "not listed", price)


def kinds(alerts):
    return [a.kind for a in alerts]


def test_decrease_example_from_brief():
    alerts, _ = evaluate([F(5900)], [F(6500)], [6500], RULES, {})
    a = alerts[0]
    assert a.kind == "decrease" and a.delta == -600 and round(a.pct, 2) == -9.23 and a.same_flight
    assert money(a.delta, signed=True) == "−₹600"


def test_unchanged_price_sends_nothing():
    assert evaluate([F(6500)], [F(6500)], [6500, 6500], RULES, {})[0] == []


def test_small_move_below_both_thresholds_is_ignored():
    assert evaluate([F(6400)], [F(6500)], [6500], dict(RULES, notify_lowest=False), {})[0] == []   # 100 and 1.5%


def test_percent_threshold_alone_triggers():
    assert kinds(evaluate([F(1000)], [F(1100)], [1100], dict(RULES, notify_lowest=False), {})[0]) == ["decrease"]   # 100 but 9%


def test_increase_and_toggle():
    assert kinds(evaluate([F(7000)], [F(6500)], [6500], RULES, {})[0]) == ["increase"]
    off = dict(RULES, notify_increase=False)
    assert evaluate([F(7000)], [F(6500)], [6500], off, {})[0] == []


def test_recovery_after_record_low():
    alerts, _ = evaluate([F(6500)], [F(5900)], [6500, 5900], RULES, {})
    assert kinds(alerts) == ["recovery"]


def test_route_level_when_flight_differs():
    alerts, _ = evaluate([F(5900, "AI 101", "2026-12-13 09:00", "Air India")], [F(6500)], [6500], RULES, {})
    assert alerts[0].same_flight is False


def test_matched_flight_preferred_over_cheapest():
    prev = [F(6500), F(6000, "AI 101", "2026-12-13 09:00", "Air India")]
    alerts, _ = evaluate([F(5900), F(7000, "AI 101", "2026-12-13 09:00", "Air India")], prev, [6000], RULES, {})
    assert alerts[0].same_flight and alerts[0].base.price == 6500


def test_target_fires_once_then_rearms():
    rules = dict(RULES, target_price=5500)
    a1, st = evaluate([F(5400)], [F(6000)], [6000], rules, {})
    assert "target" in kinds(a1)
    a2, st = evaluate([F(5400)], [F(5400)], [6000, 5400], rules, st)      # same price: no duplicate
    assert a2 == []
    a3, st = evaluate([F(5300)], [F(5400)], [6000, 5400, 5400], dict(rules, min_change_abs=999), st)
    assert kinds(a3) == ["target", "lowest"]                              # fresh drop below last alerted price
    a4, st = evaluate([F(6200)], [F(5300)], [6000, 5400, 5400, 5300], rules, st)
    assert st["target_price"] is None                                     # above target: re-armed
    a5, st = evaluate([F(5400)], [F(6200)], [6000, 5400, 5400, 5300, 6200], rules, st)
    assert "target" in kinds(a5)


def test_lowest_only_on_strict_new_low():
    assert "lowest" in kinds(evaluate([F(5000)], [F(5200)], [6000, 5200], RULES, {})[0])
    assert "lowest" not in kinds(evaluate([F(5200)], [F(5200)], [6000, 5200], RULES, {})[0])


def test_first_observation_has_no_change_alert():
    assert evaluate([F(6000)], None, [], RULES, {})[0] == []
