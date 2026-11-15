"""Sign in with Google or GitHub (OAuth 2.0 authorization code flow with PKCE).

Each start of a sign-in gets a random `state` (checked on return, stops forged
callbacks) and a PKCE verifier (stops a stolen code from being exchanged). Both live
in memory for 10 minutes and are bound to the browser by a cookie.

Register the app once and put the IDs in .env:
- Google: console.cloud.google.com > APIs & Services > Credentials > OAuth client ID
  (Web application), redirect URI  {web_public_url}/auth/google/callback
- GitHub: github.com/settings/developers > New OAuth App,
  callback URL  {web_public_url}/auth/github/callback
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlencode

import httpx

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "scope": "openid email profile",
    },
    "github": {
        "authorize": "https://github.com/login/oauth/authorize",
        "token": "https://github.com/login/oauth/access_token",
        "scope": "read:user user:email",
    },
}
FLOW_TTL = 600.0


class OAuthError(RuntimeError):
    """Shown to the user; never contains secrets."""


@dataclass(frozen=True)
class Flow:
    provider: str
    verifier: str
    intent: str  # "login" (log in or sign up) or "link" (add to the current account)
    user_id: int | None
    created: float


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: str
    subject: str  # the provider's stable user id
    email: str | None
    name: str | None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    return verifier, challenge


class FlowStore:
    """Short-lived in-memory state for sign-ins in progress."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._flows: dict[str, Flow] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def start(self, provider: str, intent: str, user_id: int | None) -> tuple[str, str]:
        """Returns (state, code_challenge)."""
        verifier, challenge = pkce_pair()
        state = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            self._flows = {k: f for k, f in self._flows.items() if now - f.created < FLOW_TTL}
            self._flows[state] = Flow(provider, verifier, intent, user_id, now)
        return state, challenge

    def take(self, state: str | None) -> Flow | None:
        """The flow for this state, once; None if unknown or expired."""
        if not state:
            return None
        with self._lock:
            flow = self._flows.pop(state, None)
        if flow is None or self._clock() - flow.created >= FLOW_TTL:
            return None
        return flow


def is_configured(settings: dict, provider: str) -> bool:
    return bool(settings[f"{provider}_client_id"] and settings[f"{provider}_client_secret"])


def redirect_uri(settings: dict, provider: str) -> str:
    return f"{settings['web_public_url'].rstrip('/')}/auth/{provider}/callback"


def authorize_url(settings: dict, provider: str, state: str, challenge: str) -> str:
    p = PROVIDERS[provider]
    params = {
        "client_id": settings[f"{provider}_client_id"],
        "redirect_uri": redirect_uri(settings, provider),
        "response_type": "code",
        "scope": p["scope"],
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if provider == "google":
        params["prompt"] = "select_account"
    else:
        params["allow_signup"] = "true"
    return f"{p['authorize']}?{urlencode(params)}"


async def fetch_identity(settings: dict, flow: Flow, code: str,
                         client: httpx.AsyncClient | None = None) -> VerifiedIdentity:
    """Exchange the code for a token, then read who the user is."""
    provider = flow.provider
    p = PROVIDERS[provider]
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=10)
    try:
        token_resp = await client.post(p["token"], headers={"Accept": "application/json"}, data={
            "client_id": settings[f"{provider}_client_id"],
            "client_secret": settings[f"{provider}_client_secret"],
            "code": code,
            "redirect_uri": redirect_uri(settings, provider),
            "grant_type": "authorization_code",
            "code_verifier": flow.verifier,
        })
        token = token_resp.json().get("access_token") if token_resp.status_code == 200 else None
        if not token:
            raise OAuthError(f"{provider.title()} didn't accept the sign-in. Try again.")
        auth = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

        if provider == "google":
            info = (await client.get("https://openidconnect.googleapis.com/v1/userinfo",
                                     headers=auth)).json()
            if not info.get("sub"):
                raise OAuthError("Google didn't return an account id.")
            email = info.get("email") if info.get("email_verified") else None
            return VerifiedIdentity("google", str(info["sub"]), email, info.get("name"))

        user = (await client.get("https://api.github.com/user", headers=auth)).json()
        if not user.get("id"):
            raise OAuthError("GitHub didn't return an account id.")
        email = None
        emails = await client.get("https://api.github.com/user/emails", headers=auth)
        if emails.status_code == 200:
            primary = [e for e in emails.json() if e.get("primary") and e.get("verified")]
            email = primary[0]["email"] if primary else None
        return VerifiedIdentity("github", str(user["id"]), email,
                                user.get("name") or user.get("login"))
    except httpx.HTTPError as e:
        raise OAuthError(f"Couldn't reach {provider.title()}. Check your connection.") from e
    finally:
        if own_client:
            await client.aclose()
