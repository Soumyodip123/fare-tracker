"""Pure price-change detection. No I/O, so it is easy to test."""
from dataclasses import dataclass

from .models import Flight


@dataclass
class Alert:
    kind: str                 # decrease | increase | recovery | target | lowest
    flight: Flight            # cheapest matching flight now
    base: Flight | None       # what it is compared with (None on first observation)
    delta: int | None
    pct: float | None
    same_flight: bool         # False => route-level change (cheapest fare vs cheapest fare)


def evaluate(cur: list[Flight], prev: list[Flight] | None, past_mins: list[int], rules: dict, state: dict):
    """Return (alerts, new_state).
    cur: this run's matching flights. prev: previous successful run's flights (same route) or None.
    past_mins: cheapest fare of every earlier successful run. state: {'target_price': int|None}.
    """
    st = {"target_price": state.get("target_price")}
    now = min(cur, key=lambda f: f.price)
    out, base, same, prev_low = [], None, False, None
    if prev:
        by_key = {f.key: f for f in prev}
        prev_low = min(prev, key=lambda f: f.price)
        same = now.key in by_key
        base = by_key[now.key] if same else prev_low

    def mk(kind):
        d = None if base is None else now.price - base.price
        return Alert(kind, now, base, d, None if base is None else d / base.price * 100, same)

    if base is not None:
        d = now.price - base.price
        pct = d / base.price * 100
        significant = abs(d) >= (rules.get("min_change_abs") or 0) or abs(pct) >= (rules.get("min_change_pct") or 0)
        if significant and d < 0 and rules.get("notify_decrease", True):
            out.append(mk("decrease"))
        elif significant and d > 0:
            was_record_low = len(past_mins) >= 2 and prev_low.price <= min(past_mins)
            if was_record_low and rules.get("notify_recovery", True):
                out.append(mk("recovery"))
            elif rules.get("notify_increase", True):
                out.append(mk("increase"))

    target = rules.get("target_price") or 0
    if target:
        if now.price <= target:
            last = st["target_price"]
            if last is None or now.price < last:      # re-alert only on a fresh drop below the last alerted price
                if rules.get("notify_target", True):
                    out.append(mk("target"))
                st["target_price"] = now.price
        else:
            st["target_price"] = None                 # went back above target: re-arm

    if past_mins and now.price < min(past_mins) and rules.get("notify_lowest", True):
        out.append(mk("lowest"))
    return out, st
