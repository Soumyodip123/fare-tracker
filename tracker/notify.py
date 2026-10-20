import html
import logging
import os
import re
import smtplib
from email.message import EmailMessage

import requests

from .models import money

log = logging.getLogger("tracker")
DISCLAIMER = "Fares can change before you book. This is a price observation, not a booking offer."
TITLES = {"decrease": "Fare dropped", "increase": "Fare rose", "recovery": "Fare recovered from its low",
          "target": "Target price reached", "lowest": "New lowest fare"}


def _ist(iso):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(iso).astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %H:%M IST")


def _route(cfg):
    r = cfg["route"]
    return f"{r['origin']} → {r['destination']}, {r['date']}"


def compose_alerts(alerts, cfg, at, provider_label):
    cur = cfg["route"]["currency"]
    parts = []
    for a in alerts:
        lines = [f"{TITLES[a.kind].upper()}: {_route(cfg)}", f"Flight: {a.flight.label}",
                 f"Baggage: {a.flight.baggage}"]
        if a.base is not None:
            how = "same flight" if a.same_flight else "route-level change (cheapest fare vs cheapest fare; not the same flight)"
            lines += [f"Previous price: {money(a.base.price, cur)}", f"Current price: {money(a.flight.price, cur)}",
                      f"Difference: {money(a.delta, cur, True)} ({a.pct:+.2f}%)", f"Compared as: {how}"]
        else:
            lines.append(f"Current price: {money(a.flight.price, cur)}")
        if a.kind == "target":
            lines.append(f"Your target: {money(cfg['alerts']['target_price'], cur)}")
        parts.append("\n".join(lines))
    first = alerts[0]
    tail = [f"Observed: {_ist(at)}", f"Source: {provider_label} (live search)"]
    if first.flight.link:
        tail.append(f"Search link: {first.flight.link}")
    tail.append(DISCLAIMER)
    text = "\n\n".join(parts) + "\n\n" + "\n".join(tail)
    subject = f"✈ {TITLES[first.kind]}: {cfg['route']['origin']}→{cfg['route']['destination']} " \
              f"{money(first.flight.price, cur)}" + (f" ({money(first.delta, cur, True)})" if first.delta else "")
    return subject, text


def to_html(text):
    body = html.escape(text).replace("\n", "<br>")
    body = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">Open flight search</a>', body)
    return f"<div style='font:15px/1.5 -apple-system,Helvetica,Arial,sans-serif;color:#10233F'>{body}</div>"


def send_email(subject, text):
    user, pw, to = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASSWORD"), os.environ.get("EMAIL_TO") or os.environ.get("SMTP_USER")
    if not (user and pw and to):
        raise RuntimeError("SMTP_USER / SMTP_PASSWORD / EMAIL_TO not set")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text)
    msg.add_alternative(to_html(text), subtype="html")
    with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST") or "smtp.gmail.com", int(os.environ.get("SMTP_PORT") or 465), timeout=30) as s:
        s.login(user, pw)
        s.send_message(msg)


def send_telegram(subject, text):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage", timeout=30,
                      data={"chat_id": chat, "text": f"{subject}\n\n{text}"[:4000], "disable_web_page_preview": "true"})
    if r.status_code != 200:
        raise RuntimeError(f"Telegram HTTP {r.status_code}")


def send_whatsapp(subject, text):
    """Official WhatsApp Cloud API. Proactive alerts need an approved template and are billed per message in India."""
    env = os.environ.get
    tok, pid, to, tpl = env("WHATSAPP_TOKEN"), env("WHATSAPP_PHONE_ID"), env("WHATSAPP_TO"), env("WHATSAPP_TEMPLATE")
    if not all((tok, pid, to, tpl)):
        raise RuntimeError("WHATSAPP_TOKEN / PHONE_ID / TO / TEMPLATE not set")
    flat = re.sub(r"\s+", " ", subject).strip()[:900]   # template params may not contain newlines
    body = {"messaging_product": "whatsapp", "to": to, "type": "template", "template": {
        "name": tpl, "language": {"code": env("WHATSAPP_LANG") or "en"},
        "components": [{"type": "body", "parameters": [{"type": "text", "text": flat}]}]}}
    r = requests.post(f"https://graph.facebook.com/{env('WHATSAPP_API_VERSION') or 'v21.0'}/{pid}/messages",
                      headers={"Authorization": f"Bearer {tok}"}, json=body, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"WhatsApp HTTP {r.status_code}")


SENDERS = {"email": send_email, "telegram": send_telegram, "whatsapp": send_whatsapp}


def make_dispatcher(cfg, dry_run=False):
    """Returns send(subject, text) -> {channel: 'ok' | error}. One failing channel never blocks the others."""
    def send(subject, text):
        res = {}
        for ch, fn in SENDERS.items():
            if not cfg["channels"].get(ch):
                continue
            if dry_run:
                print(f"--- DRY RUN [{ch}] ---\n{subject}\n\n{text}\n")
                res[ch] = "ok"
                continue
            try:
                fn(subject, text)
                res[ch] = "ok"
            except Exception as e:  # never log secrets: type + short message only
                res[ch] = f"{type(e).__name__}: {str(e)[:120]}"
                log.error("Notify via %s failed: %s", ch, res[ch])
        return res
    return send
