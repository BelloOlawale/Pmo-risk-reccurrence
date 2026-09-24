"""Read the Entra ID directory via Microsoft Graph using app-only credentials.

Requires the app registration to have the Microsoft Graph **application**
permission ``User.Read.All`` with admin consent. If your tenant cannot grant
that, use the ``az ad user list`` wrapper (``infra/sync-entra-users.sh``)
instead — it produces the same data without runtime Graph access.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from collections.abc import Iterator

from riskapp.config import settings

_GRAPH = "https://graph.microsoft.com/v1.0"


def _access_token() -> str:
    data = urllib.parse.urlencode(
        {
            "client_id": settings.entra_client_id,
            "client_secret": settings.entra_client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default",
        }
    ).encode()
    url = (
        f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
        "/oauth2/v2.0/token"
    )
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as resp:
        return json.load(resp)["access_token"]  # type: ignore[no-any-return]


def _get(url: str, token: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=60) as resp:
        return json.load(resp)  # type: ignore[no-any-return]


def iter_directory_users(token: str | None = None) -> Iterator[tuple[str | None, str | None]]:
    """Yield ``(upn, display_name)`` for every user in the tenant.

    ``token`` may be supplied by the caller (e.g. a delegated token from the
    Azure CLI); otherwise an app-only token is obtained from the configured
    client credentials.
    """
    if token is None:
        if not (
            settings.entra_tenant_id
            and settings.entra_client_id
            and settings.entra_client_secret
        ):
            raise RuntimeError(
                "Entra credentials are not configured (RISKAPP_ENTRA_TENANT_ID, "
                "RISKAPP_ENTRA_CLIENT_ID, RISKAPP_ENTRA_CLIENT_SECRET)."
            )
        token = _access_token()

    url: str | None = (
        f"{_GRAPH}/users?$select=userPrincipalName,displayName,mail&$top=999"
    )
    while url:
        payload = _get(url, token)
        users = payload.get("value")
        if isinstance(users, list):
            for user in users:
                if not isinstance(user, dict):
                    continue
                upn = user.get("userPrincipalName") or user.get("mail")
                name = user.get("displayName")
                yield (
                    upn if isinstance(upn, str) else None,
                    name if isinstance(name, str) else None,
                )
        next_link = payload.get("@odata.nextLink")
        url = next_link if isinstance(next_link, str) else None
