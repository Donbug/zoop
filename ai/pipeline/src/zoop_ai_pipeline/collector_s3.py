"""S3 object store for collector checkpoints and configuration. The only module that imports boto3.

Credentials come from the default AWS provider chain (the ECS task role in production); nothing here reads or accepts a key.
"""
from __future__ import annotations

import re
from pathlib import Path
from threading import Lock

from .collector_checkpoint import CheckpointError

_URI = re.compile(r"^s3://([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])(?:/(.*))?$")


def parse_uri(uri: str) -> tuple[str, str]:
    match = _URI.fullmatch(uri)
    if match is None or ".." in (match[2] or "").split("/"):
        raise CheckpointError("s3_uri_invalid", uri)
    return match[1], (match[2] or "").strip("/")


class S3Store:
    def __init__(self, bucket: str, *, client_options: dict | None = None):
        self.bucket = bucket
        self._options = dict(client_options or {})
        self._connection = None
        self._client_lock = Lock()

    @property
    def _client(self):
        # Defer credential discovery until after spawn has consumed its arguments; it may perform network I/O.
        import boto3
        from botocore.config import Config
        with self._client_lock:
            if self._connection is None:
                options = dict(self._options)
                options.setdefault("config", Config(
                    retries={"max_attempts": 4, "mode": "standard"}, connect_timeout=5, read_timeout=30))
                self._connection = boto3.client("s3", **options)
        return self._connection

    def __getstate__(self):
        # Botocore clients/sockets cannot cross process boundaries.
        return self.bucket, self._options

    def __setstate__(self, state):
        self.__init__(state[0], client_options=state[1])

    @staticmethod
    def _missing(error) -> bool:
        return error.response.get("Error", {}).get("Code", "") in {"404", "NoSuchKey", "NotFound"}

    def _call(self, operation, *args, **kwargs):
        from botocore.exceptions import BotoCoreError, ClientError
        try:
            return operation(*args, **kwargs)
        except ClientError as exc:
            if self._missing(exc):
                raise
            raise CheckpointError("store_error", exc.response.get("Error", {}).get("Code", "ClientError")) from None
        except (BotoCoreError, OSError) as exc:
            raise CheckpointError("store_error", type(exc).__name__) from None

    def put_file(self, key: str, path: Path, *, sha256: str) -> None:
        self._call(self._client.upload_file, str(path), self.bucket, key, ExtraArgs={"Metadata": {"sha256": sha256}})

    def copy(self, source_key: str, key: str, *, sha256: str) -> None:
        self._call(self._client.copy_object, Bucket=self.bucket, Key=key, MetadataDirective="REPLACE",
                   Metadata={"sha256": sha256}, CopySource={"Bucket": self.bucket, "Key": source_key})

    def put_bytes(self, key: str, data: bytes) -> None:
        self._call(self._client.put_object, Bucket=self.bucket, Key=key, Body=data)

    def put_pointer(self, key: str, data: bytes) -> None:
        """Dispatch latest exactly once; a lost response requires operator reconciliation."""
        import boto3
        from botocore.config import Config
        options = {**self._options, "config": self._client.meta.config.merge(Config(retries={"total_max_attempts": 1}))}
        client = boto3.client("s3", **options)
        try:
            self._call(client.put_object, Bucket=self.bucket, Key=key, Body=data)
        finally:
            client.close()

    def get_bytes(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError
        try:
            return self._call(self._client.get_object, Bucket=self.bucket, Key=key)["Body"].read()
        except ClientError:
            return None

    def get_file(self, key: str, path: Path) -> None:
        from botocore.exceptions import ClientError
        try:
            self._call(self._client.download_file, self.bucket, key, str(path))
        except ClientError:
            raise CheckpointError("file_missing", key) from None

    def head(self, key: str) -> tuple[int, str | None] | None:
        from botocore.exceptions import ClientError
        try:
            response = self._call(self._client.head_object, Bucket=self.bucket, Key=key)
        except ClientError:
            return None
        return response["ContentLength"], response.get("Metadata", {}).get("sha256")


def open_store(uri: str) -> tuple[S3Store, str]:
    """Return (store, key prefix) for `s3://bucket/prefix`."""
    bucket, prefix = parse_uri(uri)
    return S3Store(bucket), prefix
