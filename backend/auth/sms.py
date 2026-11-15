"""Send phone verification codes.

- "console" (default): writes the code to the server log. For local testing only;
  the sign-in page says so, and it's refused if the server isn't on localhost.
- "twilio": sends a real SMS. Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and
  TWILIO_FROM_NUMBER (in .env, never in settings.json).
"""
from __future__ import annotations

import logging
import re

import httpx

log = logging.getLogger("posture.auth")
PHONE_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> str | None:
    """'+91 98765-43210' -> '+919876543210'. Must include the country code."""
    phone = re.sub(r"[\s().-]", "", raw or "")
    return phone if PHONE_RE.fullmatch(phone) else None


def mask_phone(phone: str) -> str:
    return phone[:3] + "•" * max(0, len(phone) - 5) + phone[-2:]


class SmsError(RuntimeError):
    pass


class ConsoleSms:
    dev_only = True

    def send(self, phone: str, text: str) -> None:
        log.warning("[DEV SMS to %s] %s", phone, text)


class TwilioSms:
    dev_only = False

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

    def send(self, phone: str, text: str) -> None:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        try:
            r = httpx.post(url, auth=(self.account_sid, self.auth_token), timeout=10,
                           data={"To": phone, "From": self.from_number, "Body": text})
        except httpx.HTTPError as e:
            raise SmsError(f"SMS service unreachable: {e}") from e
        if r.status_code >= 300:
            log.error("Twilio error %s: %s", r.status_code, r.text[:300])
            raise SmsError("The SMS service refused the message.")


def make_sender(settings: dict) -> ConsoleSms | TwilioSms | None:
    """The configured sender, or None if phone sign-in is turned off."""
    provider = settings["sms_provider"]
    if provider == "twilio":
        sid, token, sender = (settings["twilio_account_sid"], settings["twilio_auth_token"],
                              settings["twilio_from_number"])
        if sid and token and sender:
            return TwilioSms(sid, token, sender)
        log.warning("sms_provider is twilio but its credentials are missing; phone sign-in off")
        return None
    if provider == "console":
        return ConsoleSms()
    return None
