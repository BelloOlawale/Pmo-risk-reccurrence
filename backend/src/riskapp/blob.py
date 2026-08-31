"""Azure Blob Storage: uploaded registers + citation links.

SPEC §8 / ARCHITECTURE §2. Register files uploaded through the admin import
flow are stored in Blob so the resulting risks carry a durable
``source_file_url``. The upload is a no-op (returns ``None``) when Blob is not
configured, so dev and tests run without Azure.
"""

from __future__ import annotations

from typing import Protocol

from riskapp.config import settings


class BlobStorageProvider(Protocol):
    """Contract for storing uploaded register files (stubbed in tests)."""

    def upload_bytes(
        self, blob_name: str, data: bytes, *, content_type: str | None = None
    ) -> str | None:
        """Upload ``data`` to ``blob_name`` and return its public URL.

        Returns ``None`` when storage is not configured.
        """
        ...


def register_blob_name(project_id: int, job_id: str, file_name: str) -> str:
    """Build a stable, path-safe blob key for an uploaded register."""
    safe = (file_name or "upload.xlsx").replace("\\", "/").split("/")[-1]
    return f"imports/{project_id}/{job_id}/{safe}"


class AzureBlobStorage:
    """Blob-backed upload using account name + key (dev: .env, prod: Key Vault)."""

    def __init__(
        self,
        account_name: str | None = None,
        account_key: str | None = None,
        container: str | None = None,
    ) -> None:
        self._account_name = (
            settings.blob_account_name if account_name is None else account_name
        )
        self._account_key = (
            settings.blob_account_key if account_key is None else account_key
        )
        self._container = settings.blob_container if container is None else container

    def upload_bytes(
        self, blob_name: str, data: bytes, *, content_type: str | None = None
    ) -> str | None:
        if not (self._account_name and self._account_key and self._container):
            return None
        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError as exc:  # pragma: no cover - dependency not in dev env
            raise RuntimeError(
                "azure-storage-blob is not installed; "
                "run `pip install azure-storage-blob`."
            ) from exc

        account_url = f"https://{self._account_name}.blob.core.windows.net"
        client = BlobServiceClient(
            account_url=account_url, credential=self._account_key
        )
        blob = (
            client.get_container_client(self._container)
            .get_blob_client(blob_name)
        )
        blob.upload_blob(data, overwrite=True, content_type=content_type)
        return blob.url
