"""Accounts: passwords, store, rate limits, and the auth routes end to end."""
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auth import routes as auth_routes
from backend.auth.oauth import FlowStore, VerifiedIdentity
from backend.auth.passwords import (
    hash_password, password_problem, username_problem, verify_password,
)
from backend.auth.ratelimit import RateLimiter
from backend.auth.sms import mask_phone, normalize_phone
from backend.auth.store import AuthStore, PendingIdentity

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = json.loads((ROOT / "config" / "settings.json").read_text())
GOOD_PW = "correct horse battery"


class FakeSms:
    def __init__(self, dev_only=False):
        self.dev_only = dev_only
        self.sent = []

    def send(self, phone, text):
        self.sent.append((phone, text))

    def last_code(self):
        return self.sent[-1][1].split("code is ")[1][:6]


class Now:
    def __init__(self):
        self.t = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


# ---------- passwords / rules ----------

def test_password_hashing():
    h = hash_password(GOOD_PW)
    assert h.startswith("scrypt$") and GOOD_PW not in h
    assert verify_password(GOOD_PW, h) and not verify_password("wrong password!", h)
    assert hash_password(GOOD_PW) != h  # random salt
    assert not verify_password(GOOD_PW, "garbage") and not verify_password(GOOD_PW, "md5$x$y$z$a$b")


def test_username_and_password_rules():
    assert username_problem("shubh_01") is None
    for bad in ("ab", "-start", "has space", "x" * 40, "émile", ""):
        assert username_problem(bad)
    assert password_problem(GOOD_PW) is None
    assert "at least" in password_problem("short")
    assert "guess" in password_problem("password123")
    assert "guess" in password_problem("aaaaaaaaaaaa")
    assert "username" in password_problem("my-name-is-shubh-ok", "shubh")
    assert "at most" in password_problem("x1" * 100)


def test_rate_limiter():
    t = {"now": 0.0}
    rl = RateLimiter(3, 60, clock=lambda: t["now"])
    assert all(rl.allow("k") for _ in range(3)) and not rl.allow("k")
    assert rl.allow("other")
    assert rl.retry_after("k") > 0
    t["now"] = 61
    assert rl.allow("k")


def test_phone_helpers():
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert normalize_phone("(+1) 555 123 4567") == "+15551234567"
    for bad in ("9876543210", "+0123456789", "+12", "+1234567890123456", "abc"):
        assert normalize_phone(bad) is None
    assert mask_phone("+919876543210") == "+91••••••••10"


# ---------- store ----------

@pytest.fixture
def store(tmp_path):
    now = Now()
    s = AuthStore(tmp_path / "a.db", secret=b"k" * 32, now=now)
    yield s, now
    s.close()


def test_store_users_sessions_and_tokens(store):
    s, now = store
    u = s.create_user("Alice", hash_password(GOOD_PW))
    with pytest.raises(ValueError, match="taken"):
        s.create_user("alice", hash_password(GOOD_PW))  # case-insensitive
    token = s.create_session(u.id, timedelta(hours=1))
    assert s.session_user(token).id == u.id
    assert s.session_user("forged") is None and s.session_user(None) is None
    raw_db = (Path(s._conn.execute("PRAGMA database_list").fetchone()[2])).read_bytes()
    assert token.encode() not in raw_db  # only the hash is stored
    now.t += timedelta(hours=2)
    assert s.session_user(token) is None  # expired
    t2 = s.create_session(u.id, timedelta(hours=1))
    s.delete_session(t2)
    assert s.session_user(t2) is None


def test_store_lockout(store):
    s, now = store
    u = s.create_user("bob", hash_password(GOOD_PW))
    for _ in range(8):
        s.record_failed_login(u.id)
    assert s.is_locked(s.get_user(u.id))
    now.t += timedelta(minutes=16)
    assert not s.is_locked(s.get_user(u.id))


def test_store_otp(store):
    s, now = store
    code = s.create_otp("+15551234567", timedelta(minutes=5))
    assert not s.check_otp("+15551234567", "000000" if code != "000000" else "111111")
    assert s.check_otp("+15551234567", code)
    assert not s.check_otp("+15551234567", code)  # single use
    code = s.create_otp("+15551234567", timedelta(minutes=5))
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        s.check_otp("+15551234567", wrong)
    assert not s.check_otp("+15551234567", code)  # too many wrong guesses burns it
    code = s.create_otp("+15551234567", timedelta(minutes=5))
    now.t += timedelta(minutes=6)
    assert not s.check_otp("+15551234567", code)  # expired


def test_store_identities_and_pending(store):
    s, now = store
    a = s.create_user("a1x", hash_password(GOOD_PW))
    b = s.create_user("b1x", hash_password(GOOD_PW))
    s.link_identity(a.id, "github", "42", "a@example.com")
    assert s.find_identity_user("github", "42").id == a.id
    with pytest.raises(ValueError, match="already connected"):
        s.link_identity(b.id, "github", "42")
    assert s.get_user(a.id).email == "a@example.com"
    token = s.create_pending(PendingIdentity("google", "g1", "x@example.com", "X"),
                             timedelta(minutes=15))
    assert s.get_pending(token).subject == "g1"
    now.t += timedelta(minutes=16)
    assert s.get_pending(token) is None


# ---------- routes ----------

@pytest.fixture
def app_env(tmp_path, monkeypatch):
    (tmp_path / "messages").mkdir()
    shutil.copy(ROOT / "messages" / "alerts.json", tmp_path / "messages")
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "index.html").write_text("<h1>app</h1>")
    (tmp_path / "frontend" / "login.html").write_text("<h1>login</h1>")
    settings = dict(SETTINGS)
    settings["web_allowed_hosts"] = [*SETTINGS["web_allowed_hosts"], "testserver"]
    settings.update(google_client_id="gid", google_client_secret="gsecret")
    now = Now()
    store = AuthStore(tmp_path / "data/output/posture.db", secret=b"s" * 32, now=now)
    sms = FakeSms()
    app = create_app(settings, tmp_path, sms=sms, auth_store=store)
    with TestClient(app) as client:
        yield client, sms, now, store


def post(client, url, body=None, **kw):
    return client.post(url, json=body or {}, **kw)


def test_pages_need_login_and_security_headers(app_env):
    client, *_ = app_env
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/login.html"
    login = client.get("/login.html")
    assert login.status_code == 200
    h = login.headers
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert client.get("/api/stats").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/docs").status_code == 404  # no public API map


def test_guest_signup_login_logout(app_env):
    client, *_ = app_env
    r = post(client, "/api/auth/signup", {"username": "guest_1", "password": GOOD_PW,
                                          "guest": True})
    assert r.status_code == 201
    me = r.json()
    assert me["is_guest"] and me["trial_days_left"] == SETTINGS["guest_trial_days"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/", follow_redirects=False).status_code == 200
    assert client.get("/login.html", follow_redirects=False).status_code == 302  # already in

    assert post(client, "/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    r = post(client, "/api/auth/login", {"username": "GUEST_1", "password": GOOD_PW})
    assert r.status_code == 200 and r.json()["username"] == "guest_1"


def test_signup_rules(app_env):
    client, *_ = app_env
    def signup(**body):
        return post(client, "/api/auth/signup", {"password": GOOD_PW, "guest": True, **body})
    assert signup(username="x").status_code == 400
    assert signup(username="okname", password="password123").status_code == 400
    assert signup(username="taken1").status_code == 201
    post(client, "/api/auth/logout")
    assert signup(username="TAKEN1").status_code == 409
    r = post(client, "/api/auth/signup", {"username": "verified1", "password": GOOD_PW})
    assert r.status_code == 400 and "Verify" in r.json()["detail"]  # non-guest needs proof


def test_login_errors_do_not_reveal_accounts_and_lock_out(app_env):
    client, *_ = app_env
    post(client, "/api/auth/signup", {"username": "victim", "password": GOOD_PW, "guest": True})
    post(client, "/api/auth/logout")
    unknown = post(client, "/api/auth/login", {"username": "nobody", "password": GOOD_PW})
    wrong = post(client, "/api/auth/login", {"username": "victim", "password": "nope nope nope"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    for _ in range(7):
        post(client, "/api/auth/login", {"username": "victim", "password": "nope nope nope"})
    locked = post(client, "/api/auth/login", {"username": "victim", "password": GOOD_PW})
    assert locked.status_code == 429  # even the right password waits out the lock


def test_login_rate_limit_per_ip(app_env):
    client, *_ = app_env
    codes = [post(client, "/api/auth/login", {"username": f"u{i}xx", "password": "x" * 12}).status_code
             for i in range(31)]
    assert codes[-1] == 429 and 401 in codes


def test_cross_site_and_form_posts_are_refused(app_env):
    client, *_ = app_env
    body = {"username": "csrf1", "password": GOOD_PW, "guest": True}
    r = client.post("/api/auth/signup", json=body, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/auth/signup", json=body, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    r = client.post("/api/auth/login", data={"username": "a", "password": "b"})
    assert r.status_code == 415
    r = client.post("/api/auth/signup", json=body, headers={"origin": "http://testserver"})
    assert r.status_code == 201


def test_phone_signup_then_login(app_env):
    client, sms, *_ = app_env
    r = post(client, "/api/auth/phone/send", {"phone": "+91 98765 43210"})
    assert r.status_code == 200 and r.json()["sent_to"] == "+91••••••••10"
    code = sms.last_code()
    assert post(client, "/api/auth/phone/verify",
                {"phone": "+919876543210", "code": "999999" if code != "999999" else "111111"}
                ).status_code == 400
    r = post(client, "/api/auth/phone/verify", {"phone": "+919876543210", "code": code})
    assert r.json()["status"] == "needs_account" and r.json()["provider"] == "phone"
    assert client.get("/api/auth/pending").json()["verified_as"] == "+91••••••••10"
    r = post(client, "/api/auth/signup", {"username": "phoneuser", "password": GOOD_PW})
    assert r.status_code == 201
    me = r.json()
    assert not me["is_guest"] and me["linked"] == ["phone"] and me["phone"] == "+919876543210"
    assert client.get("/api/auth/pending").status_code == 404  # used up

    post(client, "/api/auth/logout")
    post(client, "/api/auth/phone/send", {"phone": "+919876543210"})
    r = post(client, "/api/auth/phone/verify", {"phone": "+919876543210", "code": sms.last_code()})
    assert r.json()["status"] == "logged_in"
    assert client.get("/api/auth/me").json()["username"] == "phoneuser"


def test_console_sms_codes_only_work_on_this_computer(tmp_path):
    (tmp_path / "messages").mkdir()
    shutil.copy(ROOT / "messages" / "alerts.json", tmp_path / "messages")
    settings = dict(SETTINGS)
    settings["web_allowed_hosts"] = [*SETTINGS["web_allowed_hosts"], "testserver"]
    app = create_app(settings, tmp_path, sms=FakeSms(dev_only=True),
                     auth_store=AuthStore(tmp_path / "p.db", secret=b"s" * 32))
    with TestClient(app) as client:  # TestClient's address isn't loopback
        r = post(client, "/api/auth/phone/send", {"phone": "+15551234567"})
        assert r.status_code == 503


def test_phone_code_limits_and_validation(app_env):
    client, sms, *_ = app_env
    assert post(client, "/api/auth/phone/send", {"phone": "98765"}).status_code == 400
    codes = [post(client, "/api/auth/phone/send", {"phone": "+15551234567"}).status_code
             for _ in range(4)]
    assert codes == [200, 200, 200, 429]


def test_guest_upgrades_by_linking_phone_and_cannot_steal_identities(app_env):
    client, sms, *_ = app_env
    post(client, "/api/auth/signup", {"username": "owner1", "password": GOOD_PW, "guest": True})
    post(client, "/api/auth/phone/send", {"phone": "+15550001111"})
    r = post(client, "/api/auth/phone/verify",
             {"phone": "+15550001111", "code": sms.last_code(), "intent": "link"})
    assert r.json()["status"] == "linked"
    me = client.get("/api/auth/me").json()
    assert not me["is_guest"] and me["linked"] == ["phone"]

    post(client, "/api/auth/logout")
    post(client, "/api/auth/signup", {"username": "thief1", "password": GOOD_PW, "guest": True})
    post(client, "/api/auth/phone/send", {"phone": "+15550001111"})
    r = post(client, "/api/auth/phone/verify",
             {"phone": "+15550001111", "code": sms.last_code(), "intent": "link"})
    assert r.status_code == 409


def test_trial_expiry_blocks_the_app_but_allows_login(app_env):
    client, sms, now, store = app_env
    post(client, "/api/auth/signup", {"username": "trialist", "password": GOOD_PW, "guest": True})
    now.t += timedelta(days=SETTINGS["guest_trial_days"] + 1)
    assert client.get("/api/auth/me").status_code == 401  # the 7-day login expired too
    r = post(client, "/api/auth/login", {"username": "trialist", "password": GOOD_PW})
    assert r.status_code == 200  # logging in still works, so they can upgrade
    me = r.json()
    assert me["trial_expired"] and me["trial_days_left"] == 0
    r = client.get("/", follow_redirects=False)
    assert r.headers["location"] == "/login.html#trial-ended"
    assert client.get("/api/stats").status_code == 401
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_websocket_needs_login(app_env):
    client, *_ = app_env
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert exc.value.code == 4401


def test_providers_endpoint(app_env):
    client, *_ = app_env
    p = client.get("/api/auth/providers").json()
    assert p == {"google": True, "github": False, "phone": True, "phone_dev_mode": False,
                 "guest_trial_days": SETTINGS["guest_trial_days"]}


def test_oauth_flow(app_env, monkeypatch):
    client, *_ = app_env
    assert client.get("/auth/github/start", follow_redirects=False).headers["location"] \
        .startswith("/login.html?error=")  # not configured

    r = client.get("/auth/google/start", follow_redirects=False)
    target = urlsplit(r.headers["location"])
    q = parse_qs(target.query)
    assert target.netloc == "accounts.google.com"
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == ["gid"]
    state = q["state"][0]

    async def fake_identity(settings, flow, code, client=None):
        assert code == "the-code" and flow.verifier
        return VerifiedIdentity("google", "g-123", "me@gmail.com", "Me")
    monkeypatch.setattr(auth_routes, "fetch_identity", fake_identity)

    # A forged callback (wrong state) is refused.
    bad = client.get("/auth/google/callback?code=the-code&state=forged", follow_redirects=False)
    assert bad.headers["location"].startswith("/login.html?error=")

    ok = client.get(f"/auth/google/callback?code=the-code&state={state}", follow_redirects=False)
    assert ok.headers["location"] == "/login.html#complete"
    assert client.get("/api/auth/pending").json()["verified_as"] == "me@gmail.com"
    # The same state can't be replayed.
    again = client.get(f"/auth/google/callback?code=the-code&state={state}",
                       follow_redirects=False)
    assert again.headers["location"].startswith("/login.html?error=")

    r = post(client, "/api/auth/signup", {"username": "gmailuser", "password": GOOD_PW})
    assert r.status_code == 201 and r.json()["linked"] == ["google"]
    assert r.json()["email"] == "me@gmail.com" and r.json()["display_name"] == "Me"

    # Next time Google logs straight in.
    post(client, "/api/auth/logout")
    r = client.get("/auth/google/start", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    ok = client.get(f"/auth/google/callback?code=the-code&state={state}", follow_redirects=False)
    assert ok.headers["location"] == "/"
    assert client.get("/api/auth/me").json()["username"] == "gmailuser"


def test_oauth_state_must_match_this_browser(app_env, monkeypatch):
    client, *_ = app_env
    r = client.get("/auth/google/start", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    client.cookies.clear()  # the callback arrives in a different browser (login CSRF)
    r = client.get(f"/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert r.headers["location"].startswith("/login.html?error=")


def test_flow_store_expires():
    t = {"now": 0.0}
    flows = FlowStore(clock=lambda: t["now"])
    state, _ = flows.start("google", "login", None)
    t["now"] = 601
    assert flows.take(state) is None


def test_trial_days_left_rounds_up(store):
    s, now = store
    u = s.create_user("t1x", hash_password(GOOD_PW), guest_trial_days=14)
    now.t += timedelta(seconds=5)  # a moment after signing up
    assert s.get_user(u.id).trial_days_left(now()) == 14
    now.t += timedelta(days=13, hours=23)
    assert s.get_user(u.id).trial_days_left(now()) == 1
    now.t += timedelta(hours=2)
    assert s.get_user(u.id).trial_days_left(now()) == 0
