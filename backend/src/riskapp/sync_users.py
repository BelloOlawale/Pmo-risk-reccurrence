"""Import the Entra ID directory into the local ``users`` table.

Usage:
    # from a JSON export (e.g. `az ad user list -o json`)
    python -m riskapp.sync_users --source file --file users.json

    # straight from Microsoft Graph (needs User.Read.All + admin consent)
    python -m riskapp.sync_users --source graph

Existing rows are matched case-insensitively by UPN and never deleted, so this
is safe to re-run (e.g. from a scheduled job) to keep the owner picker current.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
from collections.abc import Iterable

from riskapp.db import SessionLocal
from riskapp.directory import DirectoryEntry, prune_guest_users, sync_directory_users


def _from_file(path: str) -> Iterable[DirectoryEntry]:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("value") or data.get("users") or []
    for item in data:
        if isinstance(item, str):
            yield item, None
            continue
        upn = (
            item.get("upn")
            or item.get("userPrincipalName")
            or item.get("mail")
            or item.get("email")
        )
        name = item.get("display_name") or item.get("displayName") or item.get("name")
        yield upn, name


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the Entra ID directory into users.")
    parser.add_argument("--source", choices=["file", "graph"], default="file")
    parser.add_argument("--file", help="JSON export path (required for --source file)")
    parser.add_argument(
        "--include-guests",
        action="store_true",
        help="Also import B2B guest accounts (#EXT# UPNs); excluded by default",
    )
    parser.add_argument(
        "--prune-guests",
        action="store_true",
        help="Delete any existing B2B guest rows (after clearing references)",
    )
    args = parser.parse_args()

    if args.source == "graph":
        from riskapp.entra_graph import iter_directory_users

        # A delegated token can be supplied (e.g. from `az account
        # get-access-token`); otherwise app-only client credentials are used.
        entries: Iterable[DirectoryEntry] = iter_directory_users(
            token=os.environ.get("GRAPH_ACCESS_TOKEN") or None
        )
    else:
        if not args.file:
            raise SystemExit("ERROR: --file is required when --source file")
        entries = _from_file(args.file)

    with SessionLocal() as db:
        created, updated, guests = sync_directory_users(
            db, entries, include_guests=args.include_guests
        )
        pruned = prune_guest_users(db) if args.prune_guests else 0

    print(
        f"Directory sync complete: {created} created, {updated} updated, "
        f"{guests} guest(s) skipped, {pruned} guest(s) pruned."
    )


if __name__ == "__main__":
    main()
