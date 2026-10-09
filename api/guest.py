"""Guest access for portfolio visitors (plan section 9): "continue as guest" after a Cloudflare
Turnstile check, without an account.

- The API issues a short-lived token (EdDSA). Its public key is published as JWKS so the
  Central-Intelligence-Agent accepts the same token; audience is both APIs.
- Guests get read scopes and `ask:guest`, never an admin scope.
- Abuse protection besides Turnstile: sessions per client (hashed IP) per hour and per day overall.
  Counters live in memory only; no IP address is stored.
"""

import base64
import hashlib
import logging
import os
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api.auth import Principal

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
# Cloudflare's documented test secrets (always pass / always fail / token already spent).
TEST_SECRET_PREFIXES = ("1x0000", "2x0000", "3x0000")
log = logging.getLogger(__name__)
GUEST_SCOPES = ("read:kpi", "read:knowledge", "ask:guest")
AUDIENCES = ["bis-api", "cia-api"]
ALGORITHM = "EdDSA"

router = APIRouter(prefix="/api/v1/guest", tags=["guest"])


@dataclass(frozen=True)
class GuestSettings:
    enabled: bool
    site_key: str
    turnstile_secret: str
    signing_secret: str
    issuer: str
    ttl_seconds: int
    per_client_per_hour: int
    per_day: int


def _enabled(turnstile_secret: str, signing_secret: str) -> bool:
    """Guest mode needs real configuration. Cloudflare's test secrets let every request pass, so
    they only count where explicitly allowed (local stack); otherwise guest mode stays off."""
    if os.getenv("BIS_GUEST_ENABLED", "false").lower() != "true":
        return False
    if len(signing_secret) < 16 or not turnstile_secret:
        log.warning("Guest mode off: BIS_GUEST_TOKEN_SECRET or BIS_TURNSTILE_SECRET_KEY missing")
        return False
    if turnstile_secret.startswith(TEST_SECRET_PREFIXES) and os.getenv("BIS_GUEST_ALLOW_TEST_KEYS") != "true":
        log.warning("Guest mode off: Turnstile test secret without BIS_GUEST_ALLOW_TEST_KEYS=true")
        return False
    return True


@lru_cache
def settings() -> GuestSettings:
    turnstile_secret = os.getenv("BIS_TURNSTILE_SECRET_KEY", "")
    signing_secret = os.getenv("BIS_GUEST_TOKEN_SECRET", "")
    return GuestSettings(
        enabled=_enabled(turnstile_secret, signing_secret),
        site_key=os.getenv("BIS_TURNSTILE_SITE_KEY", ""),
        turnstile_secret=turnstile_secret,
        signing_secret=signing_secret,
        issuer=os.getenv("BIS_GUEST_ISSUER", "bis-guest"),
        ttl_seconds=int(os.getenv("BIS_GUEST_TTL_SECONDS", "7200")),
        per_client_per_hour=int(os.getenv("BIS_GUEST_SESSIONS_PER_CLIENT_HOUR", "10")),
        per_day=int(os.getenv("BIS_GUEST_SESSIONS_PER_DAY", "1000")),
    )


# --- signing key ------------------------------------------------------------------------------


class GuestKeys:
    """Ed25519 key derived from a random secret in the environment: no key file to manage, and
    every API replica signs with the same key."""

    def __init__(self, secret: str):
        if len(secret) < 16:
            raise RuntimeError("BIS_GUEST_TOKEN_SECRET is missing or too short (bis setup generates it)")
        seed = hashlib.sha256(f"bis-guest-token:{secret}".encode()).digest()
        self.private = Ed25519PrivateKey.from_private_bytes(seed)
        self.public = self.private.public_key()
        raw = self.public.public_bytes_raw()
        self.kid = hashlib.sha256(raw).hexdigest()[:16]
        self.jwk = {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode(),
            "kid": self.kid,
            "use": "sig",
            "alg": ALGORITHM,
        }


@lru_cache
def keys() -> GuestKeys:
    return GuestKeys(settings().signing_secret)


def issue_token(keys: GuestKeys, issuer: str, ttl: int, now: float | None = None) -> tuple[str, int]:
    now = int(now if now is not None else time.time())
    claims = {
        "iss": issuer,
        "aud": AUDIENCES,
        "sub": f"guest:{uuid.uuid4()}",
        "scope": " ".join(GUEST_SCOPES),
        "role": "guest",
        "iat": now,
        "exp": now + ttl,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(claims, keys.private, algorithm=ALGORITHM, headers={"kid": keys.kid}), ttl


class GuestTokenVerifier:
    """Verifies guest tokens for the BI API (audience bis-api)."""

    def __init__(self, keys: GuestKeys, issuer: str, audience: str = "bis-api"):
        self.keys, self.issuer, self.audience = keys, issuer, audience

    def decode(self, token: str) -> dict:
        claims = jwt.decode(
            token,
            self.keys.public,
            algorithms=[ALGORITHM],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        if claims.get("role") != "guest" or not claims["sub"].startswith("guest:"):
            raise jwt.InvalidTokenError("not a guest token")
        return claims

    def verify(self, token: str) -> Principal:
        claims = self.decode(token)
        # Whatever the token says, a guest never holds more than the guest scopes.
        scopes = frozenset(claims.get("scope", "").split()) & frozenset(GUEST_SCOPES)
        return Principal(subject=claims["sub"], username="Gast", client="guest", scopes=scopes, guest=True)


# --- abuse protection -----------------------------------------------------------------------


class RateLimiter:
    """Sliding windows in memory: per client and hour, overall per day."""

    def __init__(self, per_client_per_hour: int, per_day: int, clock=time.monotonic):
        self.per_client, self.per_day, self.clock = per_client_per_hour, per_day, clock
        self._clients: dict[str, deque[float]] = {}
        self._all: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self, client: str) -> str | None:
        """None if allowed (and counted), otherwise the reason."""
        now = self.clock()
        with self._lock:
            while self._all and now - self._all[0] > 86400:
                self._all.popleft()
            window = self._clients.setdefault(client, deque())
            while window and now - window[0] > 3600:
                window.popleft()
            if len(self._all) >= self.per_day:
                return "daily guest limit reached"
            if len(window) >= self.per_client:
                return "too many guest sessions from this client"
            window.append(now)
            self._all.append(now)
            # Forget idle clients so the map does not grow without bound.
            if len(self._clients) > 10000:
                for key in [k for k, v in self._clients.items() if not v or now - v[-1] > 3600]:
                    del self._clients[key]
            return None

    def stats(self) -> dict[str, int]:
        now = self.clock()
        with self._lock:
            return {
                "sessions_last_24h": sum(1 for t in self._all if now - t <= 86400),
                "sessions_last_hour": sum(1 for t in self._all if now - t <= 3600),
            }


@lru_cache
def limiter() -> RateLimiter:
    s = settings()
    return RateLimiter(s.per_client_per_hour, s.per_day)


def client_key(request: Request) -> str:
    """Hashed client address; the first X-Forwarded-For entry is set by the reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for", "")
    address = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    return hashlib.sha256(f"{settings().signing_secret}:{address}".encode()).hexdigest()[:24]


def verify_turnstile(secret: str, token: str, client: httpx.Client | None = None) -> bool:
    if not secret or not token:
        return False
    http = client or httpx.Client(timeout=10.0)
    try:
        response = http.post(SITEVERIFY_URL, data={"secret": secret, "response": token})
        return response.status_code == 200 and response.json().get("success") is True
    except (httpx.HTTPError, ValueError):
        return False


def get_turnstile_client() -> httpx.Client | None:
    return None  # replaced in tests


# --- endpoints -------------------------------------------------------------------------------


class GuestConfig(BaseModel):
    enabled: bool
    site_key: str


class SessionRequest(BaseModel):
    turnstile_token: str = Field(min_length=1, max_length=4096)


class SessionOut(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str


@router.get("/config")
def guest_config() -> GuestConfig:
    """What the landing page needs: whether guest mode is on, and the public Turnstile site key."""
    s = settings()
    return GuestConfig(enabled=s.enabled, site_key=s.site_key if s.enabled else "")


@router.get("/jwks")
def guest_jwks() -> dict:
    """Public key of guest tokens, for the Central-Intelligence-Agent."""
    if not settings().enabled:
        return {"keys": []}
    return {"keys": [keys().jwk]}


@router.post("/session")
def guest_session(body: SessionRequest, request: Request) -> SessionOut:
    s = settings()
    if not s.enabled:
        raise HTTPException(404, "Guest access is disabled")
    reason = limiter().allow(client_key(request))
    if reason:
        raise HTTPException(429, reason, headers={"Retry-After": "3600"})
    if not verify_turnstile(s.turnstile_secret, body.turnstile_token, get_turnstile_client()):
        raise HTTPException(403, "Captcha verification failed")
    token, ttl = issue_token(keys(), s.issuer, s.ttl_seconds)
    return SessionOut(access_token=token, expires_in=ttl, scope=" ".join(GUEST_SCOPES))
