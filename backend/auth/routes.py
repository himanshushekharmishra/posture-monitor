"""HTTP routes for accounts: log in/out, sign up (verified or guest), phone codes,
Google/GitHub sign-in, and "who am I".

Every account has a username and password. Google, GitHub and phone prove who you
are when signing up (and can log you in afterwards); a guest account skips that and
gets a free trial, and can be upgraded later by connecting one of them.
"""
from __future__ import annotations

import ipaddress
import logging
import re
from datetime import timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from backend.auth.oauth import (
    PROVIDERS, FlowStore, OAuthError, VerifiedIdentity, authorize_url, fetch_identity,
    is_configured,
)
from backend.auth.passwords import (
    DUMMY_HASH, hash_password, password_problem, username_problem, verify_password,
)
from backend.auth.ratelimit import RateLimiter
from backend.auth.sms import SmsError, mask_phone, normalize_phone
from backend.auth.store import AuthStore, PendingIdentity, User

log = logging.getLogger("posture.auth")

SESSION_COOKIE = "pm_session"
PENDING_COOKIE = "pm_pending"
OAUTH_COOKIE = "pm_oauth"
PENDING_TTL = timedelta(minutes=15)


class LoginBody(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class SignupBody(LoginBody):
    display_name: str | None = Field(default=None, max_length=60)
    guest: bool = False


class ProfileBody(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=254)


class PasswordChangeBody(BaseModel):
    new_password: str = Field(max_length=256)


EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class PhoneSendBody(BaseModel):
    phone: str = Field(max_length=32)


class PhoneVerifyBody(BaseModel):
    phone: str = Field(max_length=32)
    code: str = Field(pattern=r"^\d{6}$")
    intent: Literal["login", "link"] = "login"


def _is_loopback(host: str | None) -> bool:
    try:
        return ipaddress.ip_address((host or "").split("%")[0]).is_loopback
    except ValueError:
        return host == "localhost"


class Auth:
    """Builds the router and exposes `current_user` for the rest of the app."""

    def __init__(self, settings: dict, store: AuthStore, sms, flows: FlowStore | None = None,
                 clock=None) -> None:
        self.settings = settings
        self.store = store
        self.sms = sms
        self.flows = flows or FlowStore()
        self.secure_cookies = settings["web_public_url"].startswith("https://")
        self.session_ttl = timedelta(days=int(settings["auth_session_days"]))
        self.trial_days = int(settings["guest_trial_days"])
        self.otp_ttl = timedelta(minutes=int(settings["otp_ttl_minutes"]))
        kw = {"clock": clock} if clock else {}
        self.login_ip = RateLimiter(30, 900, **kw)
        self.signup_ip = RateLimiter(10, 3600, **kw)
        self.otp_phone = RateLimiter(3, 900, **kw)
        self.otp_ip = RateLimiter(10, 3600, **kw)
        self.verify_ip = RateLimiter(20, 900, **kw)
        self.router = self._build_router()

    # ---------- helpers ----------
    def current_user(self, request: Request) -> User | None:
        return self.store.session_user(request.cookies.get(SESSION_COOKIE))

    def active_user(self, request: Request) -> User | None:
        """Logged in and not a guest whose trial has ended."""
        user = self.current_user(request)
        if user is None or user.trial_expired(self.store.now()):
            return None
        return user

    def me(self, user: User) -> dict:
        now = self.store.now()
        return {
            "id": user.id, "username": user.username, "display_name": user.display_name,
            "email": user.email, "phone": user.phone, "is_guest": user.is_guest,
            "trial_days_left": user.trial_days_left(now),
            "trial_expired": user.trial_expired(now),
            "linked": self.store.linked_providers(user.id),
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }

    def _set_cookie(self, response: Response, name: str, value: str, max_age: int) -> None:
        response.set_cookie(name, value, max_age=max_age, httponly=True, samesite="lax",
                            secure=self.secure_cookies, path="/")

    def _log_in(self, response: Response, request: Request, user: User) -> None:
        # A fresh token on every login (no session fixation).
        self.store.delete_session(request.cookies.get(SESSION_COOKIE))
        token = self.store.create_session(user.id, self.session_ttl,
                                          request.headers.get("user-agent", ""))
        self.store.record_login(user.id)
        self._set_cookie(response, SESSION_COOKIE, token, int(self.session_ttl.total_seconds()))
        self.store.delete_pending(request.cookies.get(PENDING_COOKIE))
        response.delete_cookie(PENDING_COOKIE, path="/")

    def _limit(self, limiter: RateLimiter, key: str, what: str) -> None:
        if not limiter.allow(key):
            wait = limiter.retry_after(key)
            raise HTTPException(429, f"Too many {what}. Try again in {max(1, wait // 60)} min.",
                                headers={"Retry-After": str(wait)})

    @staticmethod
    def _ip(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _resolve(self, request: Request, response: Response, ident: VerifiedIdentity,
                 intent: str, link_user_id: int | None = None) -> dict:
        """After a provider or phone proved who someone is: log in, link, or ask for a
        username and password to finish signing up."""
        owner = self.store.find_identity_user(ident.provider, ident.subject)
        if intent == "link":
            current = self.current_user(request)
            if current is None or (link_user_id is not None and current.id != link_user_id):
                raise HTTPException(401, "Log in first to connect an account.")
            if owner and owner.id != current.id:
                raise HTTPException(409, "That account is already connected to another user.")
            if owner is None:
                self.store.link_identity(current.id, ident.provider, ident.subject, ident.email)
                if current.is_guest:
                    self.store.end_guest_trial(current.id)
            return {"status": "linked", "provider": ident.provider}
        if owner is not None:
            self._log_in(response, request, owner)
            return {"status": "logged_in"}
        token = self.store.create_pending(
            PendingIdentity(ident.provider, ident.subject, ident.email, ident.name), PENDING_TTL)
        self._set_cookie(response, PENDING_COOKIE, token, int(PENDING_TTL.total_seconds()))
        return {"status": "needs_account", **self._pending_summary(
            PendingIdentity(ident.provider, ident.subject, ident.email, ident.name))}

    @staticmethod
    def _pending_summary(p: PendingIdentity) -> dict:
        shown = mask_phone(p.subject) if p.provider == "phone" else (p.email or p.name or "")
        return {"provider": p.provider, "verified_as": shown, "suggested_name": p.name}

    # ---------- routes ----------
    def _build_router(self) -> APIRouter:
        r = APIRouter()
        s = self.settings

        @r.get("/api/auth/providers")
        def providers() -> dict:
            return {
                "google": is_configured(s, "google"),
                "github": is_configured(s, "github"),
                "phone": self.sms is not None,
                "phone_dev_mode": bool(self.sms is not None and self.sms.dev_only),
                "guest_trial_days": self.trial_days,
            }

        @r.get("/api/auth/me")
        def me(request: Request) -> dict:
            user = self.current_user(request)
            if user is None:
                raise HTTPException(401, "Not logged in")
            return self.me(user)

        @r.post("/api/auth/login")
        def login(body: LoginBody, request: Request, response: Response) -> dict:
            self._limit(self.login_ip, self._ip(request), "login attempts")
            user = self.store.get_user_by_username(body.username.strip())
            if user is None:
                verify_password(body.password, DUMMY_HASH)  # same time as a real check
                raise HTTPException(401, "Wrong username or password.")
            ok = verify_password(body.password, user.password_hash)
            if self.store.is_locked(user):
                raise HTTPException(429, "Too many failed attempts on this account. "
                                         "Try again in 15 minutes.")
            if not ok:
                self.store.record_failed_login(user.id)
                raise HTTPException(401, "Wrong username or password.")
            self._log_in(response, request, user)
            return self.me(user)

        @r.post("/api/auth/logout")
        def logout(request: Request, response: Response) -> dict:
            self.store.delete_session(request.cookies.get(SESSION_COOKIE))
            response.delete_cookie(SESSION_COOKIE, path="/")
            return {"status": "logged_out"}

        @r.get("/api/auth/pending")
        def pending(request: Request) -> dict:
            p = self.store.get_pending(request.cookies.get(PENDING_COOKIE))
            if p is None:
                raise HTTPException(404, "Nothing waiting to be completed")
            return self._pending_summary(p)

        @r.post("/api/auth/signup", status_code=201)
        def signup(body: SignupBody, request: Request, response: Response) -> dict:
            self._limit(self.signup_ip, self._ip(request), "sign-ups from this network")
            username = body.username.strip()
            problem = username_problem(username) or password_problem(body.password, username)
            if problem:
                raise HTTPException(400, problem)
            pending_token = request.cookies.get(PENDING_COOKIE)
            p = self.store.get_pending(pending_token)
            if p is None and not body.guest:
                raise HTTPException(400, "Verify with Google, GitHub or your phone first, "
                                         "or start a guest trial.")
            if p and self.store.find_identity_user(p.provider, p.subject):
                raise HTTPException(409, "That account is already connected to another user.")
            display = (body.display_name or (p.name if p else None) or "").strip() or None
            try:
                user = self.store.create_user(
                    username, hash_password(body.password), display_name=display,
                    email=p.email if p else None,
                    guest_trial_days=None if p else self.trial_days)
            except ValueError as e:
                raise HTTPException(409, str(e)) from None
            if p:
                self.store.link_identity(user.id, p.provider, p.subject, p.email)
                user = self.store.get_user(user.id)
            log.info("New %s account %s", "guest" if user.is_guest else "verified", user.id)
            self._log_in(response, request, user)
            return self.me(user)

        # ---------- account settings ----------
        def require(request: Request) -> User:
            user = self.current_user(request)
            if user is None:
                raise HTTPException(401, "Log in to continue")
            return user

        @r.post("/api/account/profile")
        def update_profile(body: ProfileBody, request: Request) -> dict:
            user = require(request)
            name = (body.display_name or "").strip() or None
            email = (body.email or "").strip() or None
            if email and not EMAIL_RE.fullmatch(email):
                raise HTTPException(400, "That email address doesn't look right.")
            self.store.update_profile(user.id, name, email)
            return self.me(self.store.get_user(user.id))

        @r.post("/api/account/password")
        def change_password(body: PasswordChangeBody, request: Request,
                            response: Response) -> dict:
            # A logged-in session is enough (no current password asked); other devices
            # are logged out below, so a stolen session elsewhere stops working.
            user = require(request)
            problem = password_problem(body.new_password, user.username)
            if problem:
                raise HTTPException(400, problem)
            if verify_password(body.new_password, user.password_hash):
                raise HTTPException(400, "That's already your password. Choose a new one.")
            self.store.update_password(user.id, hash_password(body.new_password))
            # Everyone else who had this password is logged out; this device gets a new token.
            self.store.delete_other_sessions(user.id, None)
            self._log_in(response, request, self.store.get_user(user.id))
            log.info("Password changed for account %s", user.id)
            return {"status": "changed"}

        @r.post("/api/account/delete")
        def delete_account(request: Request, response: Response) -> dict:
            # Being logged in is enough; the page asks "Are you sure?" first. The app's
            # request guard refuses cross-site and non-JSON writes, so another site
            # can't trigger this.
            user = require(request)
            self.store.delete_user(user.id)
            response.delete_cookie(SESSION_COOKIE, path="/")
            log.info("Account %s deleted", user.id)
            return {"status": "deleted"}

        @r.post("/api/auth/phone/send")
        def phone_send(body: PhoneSendBody, request: Request) -> dict:
            if self.sms is None:
                raise HTTPException(503, "Phone sign-in isn't set up on this server.")
            if self.sms.dev_only and not _is_loopback(self._ip(request)):
                raise HTTPException(503, "Phone sign-in isn't set up on this server.")
            phone = normalize_phone(body.phone)
            if phone is None:
                raise HTTPException(400, "Enter the number with its country code, "
                                         "like +91 98765 43210.")
            self._limit(self.otp_ip, self._ip(request), "codes requested")
            self._limit(self.otp_phone, phone, "codes for this number")
            code = self.store.create_otp(phone, self.otp_ttl)
            minutes = int(self.otp_ttl.total_seconds() // 60)
            try:
                self.sms.send(phone, f"Your Posture Monitor code is {code}. "
                                     f"It expires in {minutes} minutes.")
            except SmsError as e:
                raise HTTPException(502, str(e)) from None
            return {"sent_to": mask_phone(phone), "dev_mode": self.sms.dev_only}

        @r.post("/api/auth/phone/verify")
        def phone_verify(body: PhoneVerifyBody, request: Request, response: Response) -> dict:
            self._limit(self.verify_ip, self._ip(request), "code attempts")
            phone = normalize_phone(body.phone)
            if phone is None or not self.store.check_otp(phone, body.code):
                raise HTTPException(400, "That code is wrong or has expired.")
            return self._resolve(request, response,
                                 VerifiedIdentity("phone", phone, None, None), body.intent)

        @r.get("/auth/{provider}/start")
        def oauth_start(provider: str, request: Request,
                        intent: Literal["login", "link"] = "login") -> Response:
            if provider not in PROVIDERS or not is_configured(s, provider):
                return _login_error(f"{provider.title()} sign-in isn't set up on this server.")
            user = self.current_user(request)
            if intent == "link" and user is None:
                return _login_error("Log in first to connect an account.")
            state, challenge = self.flows.start(provider, intent, user.id if user else None)
            response = RedirectResponse(authorize_url(s, provider, state, challenge), 302)
            self._set_cookie(response, OAUTH_COOKIE, state, 600)
            return response

        @r.get("/auth/{provider}/callback")
        async def oauth_callback(provider: str, request: Request, code: str | None = None,
                                 state: str | None = None, error: str | None = None) -> Response:
            flow = self.flows.take(state)
            bound = request.cookies.get(OAUTH_COOKIE)
            if flow is None or bound != state or flow.provider != provider:
                return _login_error("That sign-in link expired or didn't start here. Try again.")
            if error or not code:
                return _login_error(f"{provider.title()} sign-in was cancelled.")
            try:
                ident = await fetch_identity(s, flow, code)
                result = JSONResponse({})  # collects cookies set while resolving
                outcome = self._resolve(request, result, ident, flow.intent, flow.user_id)
            except OAuthError as e:
                return _login_error(str(e))
            except HTTPException as e:
                return _login_error(e.detail)
            target = {"logged_in": "/", "linked": f"/?linked={provider}",
                      "needs_account": "/login.html#complete"}[outcome["status"]]
            response = RedirectResponse(target, 302)
            for header in result.headers.getlist("set-cookie"):
                response.headers.append("set-cookie", header)
            response.delete_cookie(OAUTH_COOKIE, path="/")
            return response

        return r


def _login_error(message: str) -> RedirectResponse:
    return RedirectResponse(f"/login.html?error={quote(message)}", 302)
