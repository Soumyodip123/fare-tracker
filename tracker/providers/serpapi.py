"""Google Flights data via SerpApi (https://serpapi.com). Free plan: 250 successful searches/month."""
import os

import requests

from ..models import Flight
from .base import NoResults, ProviderError

URL = "https://serpapi.com/search.json"
CLASSES = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}


class SerpApiProvider:
    name = "serpapi"
    label = "Google Flights (via SerpApi)"

    def search(self, cfg) -> list[Flight]:
        key = os.environ.get("SERPAPI_KEY", "").strip()
        if not key:
            raise ProviderError("SERPAPI_KEY secret is not set")
        r = cfg["route"]
        params = {
            "engine": "google_flights", "departure_id": r["origin"], "arrival_id": r["destination"],
            "outbound_date": r["date"], "type": 2 if r["trip_type"] == "one_way" else 1,
            "currency": r["currency"], "hl": "en", "gl": "in", "adults": r["passengers"],
            "travel_class": CLASSES.get(r["travel_class"], 1), "api_key": key,
        }
        try:
            resp = requests.get(URL, params=params, timeout=60)
        except requests.RequestException as e:  # message may contain the URL (and key): report type only
            raise ProviderError(f"Network error: {type(e).__name__}") from None
        if resp.status_code != 200:
            detail = ""
            try:
                detail = str(resp.json().get("error", ""))[:150]
            except ValueError:
                pass
            raise ProviderError(f"SerpApi HTTP {resp.status_code} {detail}".strip())
        return self.parse(resp.json(), r["currency"])

    @staticmethod
    def parse(data: dict, currency: str) -> list[Flight]:
        err = data.get("error")
        if err:
            if "hasn't returned any results" in err or "no results" in err.lower():
                raise NoResults(err)
            raise ProviderError(f"SerpApi: {err}"[:200])
        link = (data.get("search_metadata") or {}).get("google_flights_url", "")
        out = []
        for offer in (data.get("best_flights") or []) + (data.get("other_flights") or []):
            legs, price = offer.get("flights") or [], offer.get("price")
            if not legs or not isinstance(price, (int, float)) or price <= 0:
                continue  # an offer without a displayed fare is not a price observation
            bags = [x for leg in legs for x in (leg.get("extensions") or []) if "bag" in x.lower()]
            bags += [x for x in (offer.get("extensions") or []) if "bag" in x.lower()]
            out.append(Flight(
                airline=" + ".join(dict.fromkeys(l.get("airline", "?") for l in legs)),
                flight_number="+".join(l.get("flight_number", "") for l in legs).strip("+"),
                dep_time=(legs[0].get("departure_airport") or {}).get("time", ""),
                arr_time=(legs[-1].get("arrival_airport") or {}).get("time", ""),
                stops=len(legs) - 1, duration_min=offer.get("total_duration"),
                baggage="; ".join(dict.fromkeys(bags)) or "not listed", price=int(round(price)),
                currency=currency, link=link))
        if not out:
            raise NoResults("Response contained no priced flights")
        return out
