"""Tests for the Blob storage client and the source_file_url import wiring."""

from __future__ import annotations

from riskapp.blob import AzureBlobStorage, register_blob_name


class TestRegisterBlobName:
    def test_builds_stable_key(self) -> None:
        assert register_blob_name(7, "abc123", "punuka_bpa.xlsx") == (
            "imports/7/abc123/punuka_bpa.xlsx"
        )

    def test_strips_path_separators(self) -> None:
        assert register_blob_name(1, "j", "..\\..\\evil.xlsx") == "imports/1/j/evil.xlsx"
        assert register_blob_name(1, "j", "/etc/passwd.xlsx") == "imports/1/j/passwd.xlsx"

    def test_falls_back_to_default_name(self) -> None:
        assert register_blob_name(1, "j", "") == "imports/1/j/upload.xlsx"


class TestAzureBlobStorage:
    def test_returns_none_when_unconfigured(self) -> None:
        storage = AzureBlobStorage(account_name="", account_key="", container="")
        assert storage.upload_bytes("imports/1/j/a.xlsx", b"data") is None

    def test_returns_none_when_partially_configured(self) -> None:
        storage = AzureBlobStorage(account_name="acct", account_key="", container="c")
        assert storage.upload_bytes("imports/1/j/a.xlsx", b"data") is None
