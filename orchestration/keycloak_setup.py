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
LOCAL_ORIGINS = "http://127.0.0.1:8103,http://127.0.0.1:5173"
MCP_CLIENT_ID = "bis-claude"
# Callbacks of Claude's custom connectors (claude.ai / claude.com).
CLAUDE_CALLBACKS = ("https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback")


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

    def set_frontend_urls(self, client_id: str, origins: list[str]) -> None:
        """Redirect URIs, web origins and logout targets exactly for the given origins."""
        client = self.client_uuid(client_id)
        rep = self.get(f"/clients/{client}")
        rep["redirectUris"] = [f"{o}/*" for o in origins]
        rep["webOrigins"] = list(origins)
        rep.setdefault("attributes", {})["post.logout.redirect.uris"] = "##".join(f"{o}/*" for o in origins)
        self.send("PUT", f"/clients/{client}", rep)

    def ensure_mcp_client(self, client_id: str, resource_url: str, redirect_uris: list[str]) -> None:
        """Confidential client for Claude's MCP connector: authorization code + PKCE, tokens whose
        audience is the MCP resource only (they are not valid for the REST API)."""
        rep = {
            "clientId": client_id,
            "name": "Claude MCP connector",
            "enabled": True,
            "publicClient": False,
            "clientAuthenticatorType": "client-secret",
            "standardFlowEnabled": True,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "redirectUris": redirect_uris,
            "attributes": {"pkce.code.challenge.method": "S256"},
            "protocolMappers": [
                {
                    "name": "audience mcp resource",
                    "protocol": "openid-connect",
                    "protocolMapper": "oidc-audience-mapper",
                    "config": {
                        "included.custom.audience": resource_url,
                        "id.token.claim": "false",
                        "access.token.claim": "true",
                    },
                }
            ],
        }
        existing = self.get("/clients", clientId=client_id)
        if not existing:
            self.send("POST", "/clients", rep)
            return
        current = self.get(f"/clients/{existing[0]['id']}")
        current.update({k: v for k, v in rep.items() if k != "protocolMappers"})
        current.setdefault("attributes", {}).update(rep["attributes"])
        self.send("PUT", f"/clients/{existing[0]['id']}", current)
        mapper = rep["protocolMappers"][0]
        mappers = {m["name"]: m for m in self.get(f"/clients/{existing[0]['id']}/protocol-mappers/models")}
        if mapper["name"] in mappers:
            self.send(
                "PUT",
                f"/clients/{existing[0]['id']}/protocol-mappers/models/{mappers[mapper['name']]['id']}",
                mappers[mapper["name"]] | {"config": mapper["config"]},
            )
        else:
            self.send("POST", f"/clients/{existing[0]['id']}/protocol-mappers/models", mapper)

    def client_secret(self, client_id: str) -> str:
        return self.get(f"/clients/{self.client_uuid(client_id)}/client-secret")["value"]

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

    base_url = (
        base_url
        or os.getenv("BIS_KEYCLOAK_URL")
        or f"http://127.0.0.1:{os.getenv('BIS_KEYCLOAK_PORT', '8180')}"
    )
    admin = KeycloakAdmin.login(base_url, require_secret("BIS_KEYCLOAK_ADMIN_PASSWORD"))
    scope_ids = {name: admin.ensure_scope(name) for name in API_SCOPES}
    for name in FRONTEND_DEFAULT_SCOPES:
        admin.assign_scope("bis-frontend", scope_ids[name], "default")
    for name in FRONTEND_OPTIONAL_SCOPES:
        admin.assign_scope("bis-frontend", scope_ids[name], "optional")
    # Where the dashboard runs; locally both the container and the Vite dev server.
    origins = [
        o.strip().rstrip("/")
        for o in os.getenv("BIS_FRONTEND_ORIGINS", LOCAL_ORIGINS).split(",")
        if o.strip()
    ]
    admin.set_frontend_urls("bis-frontend", origins)
    mcp_resource = os.getenv("BIS_MCP_RESOURCE_URL", "http://127.0.0.1:8103/mcp")
    admin.ensure_mcp_client(MCP_CLIENT_ID, mcp_resource, list(CLAUDE_CALLBACKS))
    for name in FRONTEND_DEFAULT_SCOPES:
        admin.assign_scope(MCP_CLIENT_ID, scope_ids[name], "default")
    user = os.getenv("BIS_DEMO_USER", "demo")
    admin.ensure_user(user, require_secret("BIS_DEMO_PASSWORD"))
    return [
        f"scopes: {', '.join(API_SCOPES)}",
        f"bis-frontend default: {', '.join(FRONTEND_DEFAULT_SCOPES)}",
        f"bis-frontend origins: {', '.join(origins)}",
        f"{MCP_CLIENT_ID}: audience {mcp_resource}",
        f"user: {user}",
    ]


def _admin() -> KeycloakAdmin:
    from ingestion.config import require_secret

    base_url = os.getenv("BIS_KEYCLOAK_URL") or f"http://127.0.0.1:{os.getenv('BIS_KEYCLOAK_PORT', '8180')}"
    return KeycloakAdmin.login(base_url, require_secret("BIS_KEYCLOAK_ADMIN_PASSWORD"))


def mcp_client_credentials() -> tuple[str, str]:
    """Client id and secret for the Claude connector (shown only on explicit request)."""
    return MCP_CLIENT_ID, _admin().client_secret(MCP_CLIENT_ID)
