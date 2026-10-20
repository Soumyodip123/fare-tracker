from dataclasses import dataclass


@dataclass(frozen=True)
class Flight:
    airline: str
    flight_number: str
    dep_time: str
    arr_time: str
    stops: int
    duration_min: int | None
    baggage: str
    price: int
    currency: str = "INR"
    link: str = ""

    @property
    def key(self) -> str:
        """Identity used to match the same flight across searches."""
        return f"{(self.flight_number or self.airline).replace(' ', '')}|{self.dep_time}"

    @property
    def label(self) -> str:
        stops = "nonstop" if self.stops == 0 else f"{self.stops} stop(s)"
        return f"{self.airline} {self.flight_number}".strip() + f", {self.dep_time} → {self.arr_time}, {stops}"


def money(n: int | float, cur: str = "INR", signed: bool = False) -> str:
    sign = ("+" if n > 0 else "−" if n < 0 else "") if signed else ("−" if n < 0 else "")
    n = int(round(abs(n)))
    if cur != "INR":
        return f"{sign}{cur} {n:,}"
    s = str(n)
    if len(s) > 3:
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return f"{sign}₹{s}"
