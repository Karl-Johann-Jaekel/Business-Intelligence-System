"""Admin access against the local Keycloak: admin scopes only for the role bis-admin, and never
without an OTP. Skipped when the local stack is not running."""

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
import time
from html import unescape
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
import pytest

KEYCLOAK = f"http://127.0.0.1:{os.getenv('BIS_KEYCLOAK_PORT', '8180')}"
SITE = f"http://127.0.0.1:{os.getenv('BIS_FRONTEND_PORT', '8103')}"
CALLBACK = f"{SITE}/"
ADMIN_SCOPES = {"admin:simulation", "admin:agents", "admin:actions", "admin:review"}


def _up() -> bool:
    try:
        return (
            httpx.get(f"{KEYCLOAK}/realms/bis/.well-known/openid-configuration", timeout=2).status_code == 200
        )
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not (_up() and os.getenv("BIS_KEYCLOAK_ADMIN_PASSWORD") and os.getenv("BIS_DEMO_PASSWORD")),
    reason="local Keycloak not running",
)


def totp(secret: str, at: float | None = None) -> str:
    """RFC 6238 with Keycloak defaults (HmacSHA1, 6 digits, 30 s); Keycloak keys on the raw secret."""
    counter = int((at or time.time()) // 30)
    digest = hmac.new(secret.encode(), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


class Browser:
    """Authorization code + PKCE through the login pages, like the portal does."""

    def __init__(self):
        self.http = httpx.Client(follow_redirects=False, timeout=15)
        self.cookies: dict[str, str] = {}
        self.verifier = secrets.token_urlsafe(48)

    def _keep(self, response: httpx.Response) -> httpx.Response:
        for name, value in response.cookies.items():
            self.cookies[name] = value
        return response

    def _header(self) -> dict:
        # The cookie jar does not send cookies back to a bare IP, so set the header ourselves.
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}

    def start(self) -> str:
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b"=").decode()
        )
        page = self._keep(
            self.http.get(
                f"{KEYCLOAK}/realms/bis/protocol/openid-connect/auth?"
                + urlencode(
                    {
                        "client_id": "bis-frontend",
                        "response_type": "code",
                        "scope": "openid",
                        "redirect_uri": CALLBACK,
                        "code_challenge": challenge,
                        "code_challenge_method": "S256",
                        "state": "s",
                    }
                )
            )
        )
        return page.text

    def submit(self, page: str, form: dict) -> httpx.Response:
        action = unescape(re.search(r'action="([^"]+)"', page).group(1))
        return self._keep(self.http.post(action, data=form, headers=self._header()))

    def follow(self, response: httpx.Response) -> httpx.Response:
        """Follow Keycloak-internal redirects (e.g. to a required action), stop at the app callback."""
        while response.status_code == 302 and not response.headers["location"].startswith(CALLBACK):
            response = self._keep(self.http.get(response.headers["location"], headers=self._header()))
        return response

    def token(self, redirect: httpx.Response) -> dict:
        assert redirect.status_code == 302 and redirect.headers["location"].startswith(CALLBACK), (
            redirect.text[:300]
        )
        code = parse_qs(urlparse(redirect.headers["location"]).query)["code"][0]
        tokens = self.http.post(
            f"{KEYCLOAK}/realms/bis/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "client_id": "bis-frontend",
                "code": code,
                "redirect_uri": CALLBACK,
                "code_verifier": self.verifier,
            },
        )
        tokens.raise_for_status()
        return jwt.decode(tokens.json()["access_token"], options={"verify_signature": False})


@pytest.fixture
def temp_admin():
    """A throw-away user with the admin role and a permanent password, deleted afterwards."""
    from orchestration.keycloak_setup import ADMIN_ROLE, _admin

    admin = _admin()
    username, password = f"it-admin-{secrets.token_hex(4)}", secrets.token_urlsafe(16)
    admin.send(
        "POST",
        "/users",
        {
            "username": username,
            "enabled": True,
            "emailVerified": True,
            "email": f"{username}@bis.local",
            "firstName": "IT",
            "lastName": "Admin",
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        },
    )
    user_id = admin.get("/users", username=username, exact="true")[0]["id"]
    admin.send("POST", f"/users/{user_id}/role-mappings/realm", [admin.get(f"/roles/{ADMIN_ROLE}")])
    yield username, password
    admin.send("DELETE", f"/users/{user_id}")


def test_demo_user_gets_no_admin_scopes():
    browser = Browser()
    page = browser.start()
    redirect = browser.submit(
        page, {"username": os.getenv("BIS_DEMO_USER", "demo"), "password": os.environ["BIS_DEMO_PASSWORD"]}
    )
    claims = browser.token(redirect)
    scopes = set(claims["scope"].split())
    assert "read:kpi" in scopes and not scopes & ADMIN_SCOPES


def test_admin_needs_an_otp_and_then_gets_admin_scopes(temp_admin):
    username, password = temp_admin

    # First login: password alone does not finish the login; Keycloak demands an OTP device.
    browser = Browser()
    after_password = browser.follow(
        browser.submit(browser.start(), {"username": username, "password": password})
    )
    assert after_password.status_code == 200 and "totpSecret" in after_password.text
    secret = unescape(re.search(r'name="totpSecret" value="([^"]+)"', after_password.text).group(1))
    configured = browser.submit(
        after_password.text, {"totp": totp(secret), "totpSecret": secret, "userLabel": "it"}
    )
    claims = browser.token(browser.follow(configured))
    assert ADMIN_SCOPES <= set(claims["scope"].split())

    # Later logins: the OTP is asked every time; a wrong code gives no token.
    browser = Browser()
    otp_page = browser.follow(browser.submit(browser.start(), {"username": username, "password": password}))
    assert otp_page.status_code == 200 and 'name="otp"' in otp_page.text
    wrong = browser.follow(
        browser.submit(otp_page.text, {"otp": "000000" if totp(secret) != "000000" else "111111"})
    )
    assert wrong.status_code == 200 and 'name="otp"' in wrong.text  # back on the form, no code
    browser = Browser()
    otp_page = browser.follow(browser.submit(browser.start(), {"username": username, "password": password}))
    # The code of the first login must not be reused; the next window is accepted (look-ahead 1).
    claims = browser.token(
        browser.follow(browser.submit(otp_page.text, {"otp": totp(secret, time.time() + 30)}))
    )
    assert ADMIN_SCOPES <= set(claims["scope"].split())


def test_totp_matches_rfc6238_vector():
    # RFC 6238 appendix B, SHA1, T = 59 s -> 94287082 (8 digits); last 6 digits for Keycloak.
    assert totp("12345678901234567890", at=59) == "287082"
