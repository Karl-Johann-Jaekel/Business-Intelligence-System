"""Idempotent Keycloak provisioning for realm `bis` via the admin REST API.

The realm and its clients come from infra/keycloak/realm-bis.json (imported on first start).
This adds what must not live in a committed file or depends on Keycloak's built-in scopes:
- client scopes per API permission (plan section 9) and their assignment to clients,
- the demo user, with its password from infra/.env.
"""

import os
from dataclasses import dataclass

import httpx

REALM = "bis"
# Permission scopes of the API (plan section 9).
API_SCOPES = ("read:kpi", "read:knowledge", "write:facts", "admin:review")
# What the browser dashboard gets by default; the rest arrives with the knowledge layer (K1-K4).
FRONTEND_DEFAULT_SCOPES = ("read:kpi",)
FRONTEND_OPTIONAL_SCOPES = ("read:knowledge",)


@dataclass
class KeycloakAdmin:
    base_url: str
    client: httpx.Client

    @classmethod
    def login(cls, base_url: str, password: str, username: str = "admin") -> "KeycloakAdmin":
        client = httpx.Client(timeout=15)
        response = client.post(
            f"{base_url}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": username,
                "password": password,
            },
        )
        response.raise_for_status()
        client.headers["Authorization"] = f"Bearer {response.json()['access_token']}"
        return cls(base_url, client)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/admin/realms/{REALM}{path}"

    def get(self, path: str, **params):
        response = self.client.get(self._url(path), params=params)
        response.raise_for_status()
        return response.json()

    def send(self, method: str, path: str, json=None) -> httpx.Response:
        response = self.client.request(method, self._url(path), json=json)
        response.raise_for_status()
        return response

    def client_uuid(self, client_id: str) -> str:
        return self.get("/clients", clientId=client_id)[0]["id"]

    def ensure_scope(self, name: str) -> str:
        existing = {s["name"]: s["id"] for s in self.get("/client-scopes")}
        if name not in existing:
            self.send(
                "POST",
                "/client-scopes",
                {
                    "name": name,
                    "protocol": "openid-connect",
                    "attributes": {"include.in.token.scope": "true", "display.on.consent.screen": "false"},
                },
            )
            existing = {s["name"]: s["id"] for s in self.get("/client-scopes")}
        return existing[name]

    def assign_scope(self, client_id: str, scope_id: str, kind: str) -> None:
        """kind: 'default' (always in the token) or 'optional' (on request)."""
        client = self.client_uuid(client_id)
        assigned = {s["id"] for s in self.get(f"/clients/{client}/{kind}-client-scopes")}
        if scope_id not in assigned:
            self.send("PUT", f"/clients/{client}/{kind}-client-scopes/{scope_id}")

    def ensure_user(self, username: str, password: str) -> None:
        users = self.get("/users", username=username, exact="true")
        if not users:
            self.send(
                "POST",
                "/users",
                {
                    "username": username,
                    "enabled": True,
                    "emailVerified": True,
                    "email": f"{username}@bis.local",
                    "firstName": "Demo",
                    "lastName": "User",
                },
            )
            users = self.get("/users", username=username, exact="true")
        # Keep Keycloak in sync with infra/.env on every run.
        self.send(
            "PUT",
            f"/users/{users[0]['id']}/reset-password",
            {"type": "password", "value": password, "temporary": False},
        )


def provision(base_url: str | None = None) -> list[str]:
    """Returns a log of what was ensured (names only, no secrets)."""
    from ingestion.config import require_secret

    base_url = base_url or f"http://127.0.0.1:{os.getenv('BIS_KEYCLOAK_PORT', '8180')}"
    admin = KeycloakAdmin.login(base_url, require_secret("BIS_KEYCLOAK_ADMIN_PASSWORD"))
    scope_ids = {name: admin.ensure_scope(name) for name in API_SCOPES}
    for name in FRONTEND_DEFAULT_SCOPES:
        admin.assign_scope("bis-frontend", scope_ids[name], "default")
    for name in FRONTEND_OPTIONAL_SCOPES:
        admin.assign_scope("bis-frontend", scope_ids[name], "optional")
    user = os.getenv("BIS_DEMO_USER", "demo")
    admin.ensure_user(user, require_secret("BIS_DEMO_PASSWORD"))
    return [
        f"scopes: {', '.join(API_SCOPES)}",
        f"bis-frontend default: {', '.join(FRONTEND_DEFAULT_SCOPES)}",
        f"user: {user}",
    ]
