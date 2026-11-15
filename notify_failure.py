#!/usr/bin/env python3
"""
Pošle e-mail (cez Gmail SMTP), keď sa epizóda nevygenerovala.

Spúšťa ho GitHub Actions v kroku `if: failure()`.

Env premenné:
    GMAIL_USER          – Gmail adresa odosielateľa (napr. meno@gmail.com)
    GMAIL_APP_PASSWORD  – 16-znakové heslo aplikácie (Google účet → Zabezpečenie → Heslá aplikácií)
    NOTIFY_EMAIL        – príjemca (nepovinné, predvolene GMAIL_USER)
    RUN_URL             – odkaz na beh workflow (nepovinné)
    LOG_FILE            – súbor s logom generátora, posledné riadky pôjdu do mailu (nepovinné)

Ak prihlasovacie údaje chýbajú, len vypíše varovanie a skončí s kódom 0,
aby nezakryl pôvodnú chybu.
"""

import os
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

LOG_TAIL_LINES = 60


def read_log_tail(path: str | None, n: int = LOG_TAIL_LINES) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


def build_message(sender: str, recipient: str, run_url: str, log_tail: str,
                  date_str: str | None = None) -> EmailMessage:
    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    msg = EmailMessage()
    msg["Subject"] = f"❌ Kolby AI Podcast: epizóda {date_str} sa nevygenerovala"
    msg["From"] = sender
    msg["To"] = recipient

    body = [
        f"Generovanie epizódy {date_str} zlyhalo.",
        "",
        f"Beh workflow: {run_url or '(neznámy)'}",
        "",
        "Workflow môžeš po oprave spustiť znova ručne: Actions → Týždenný AI Podcast → Run workflow.",
    ]
    if log_tail:
        body += ["", f"Posledné riadky logu:", "-" * 40, log_tail]
    msg.set_content("\n".join(body))
    return msg


def send(msg: EmailMessage, user: str, password: str,
         host: str = "smtp.gmail.com", port: int = 465) -> None:
    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)


def main() -> int:
    user = os.environ.get("GMAIL_USER", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    if not user or not password:
        print("⚠️  GMAIL_USER / GMAIL_APP_PASSWORD nie sú nastavené – e-mail neodoslaný.")
        return 0

    recipient = os.environ.get("NOTIFY_EMAIL", "").strip() or user
    msg = build_message(
        sender=user,
        recipient=recipient,
        run_url=os.environ.get("RUN_URL", ""),
        log_tail=read_log_tail(os.environ.get("LOG_FILE")),
    )
    try:
        send(msg, user, password)
    except Exception as e:
        print(f"❌ Odoslanie e-mailu zlyhalo: {e}")
        return 1
    print(f"📧 Upozornenie odoslané na {recipient}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
