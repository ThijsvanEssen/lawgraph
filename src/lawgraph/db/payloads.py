"""Where the text payloads of raw records are kept: outside the database.

The XML and HTML of the sources (a BWB toestand is megabytes, an EU act hundreds of KB, a
judgment tens) is most of what LawGraph stores, nothing queries inside it, and only the
pipelines read it, whole. So a text payload is an object in a payload store, gzip-compressed,
and ``raw_sources`` keeps the metadata of the record and the name of its object
(``payload_ref``). JSON payloads (the records of the Tweede Kamer, a few KB) stay in the
database, where queries filter on them.

A payload store is a directory (``file:///path``) or an S3 bucket (``s3://bucket/prefix``, for
example at LeafCloud). An object is written before the record that names it, so a record never
names an object that is not there.
"""

from __future__ import annotations

import gzip
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse


class PayloadMissing(LookupError):
    """The payload store holds no object of that name."""


class PayloadStore(Protocol):
    location: str

    def put(self, name: str, data: bytes) -> None: ...

    def get(self, name: str) -> bytes: ...

    def exists(self, name: str) -> bool: ...


def encode(text: str) -> bytes:
    return gzip.compress(text.encode("utf-8"), compresslevel=6)


def decode(data: bytes) -> str:
    return gzip.decompress(data).decode("utf-8")


class FilePayloadStore:
    """Objects as files under a directory; a name's slashes are its subdirectories."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.location = f"file://{self.root}"

    def _path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"payload name outside the store: {name!r}")
        return path

    def put(self, name: str, data: bytes) -> None:
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Written next to its place and renamed: a reader never sees half a file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def get(self, name: str) -> bytes:
        try:
            return self._path(name).read_bytes()
        except FileNotFoundError as exc:
            raise PayloadMissing(name) from exc

    def exists(self, name: str) -> bool:
        return self._path(name).is_file()


class S3PayloadStore:
    """Objects in an S3 bucket, under an optional prefix."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        *,
        endpoint: str | None,
        region: str | None,
        access_key: str | None,
        secret_key: str | None,
    ) -> None:
        import boto3  # only a deployment with an S3 store needs it
        from botocore.config import Config

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.location = f"s3://{bucket}/{self.prefix}".rstrip("/")
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                retries={"max_attempts": 5, "mode": "standard"},
                max_pool_connections=32,
            ),
        )

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    def put(self, name: str, data: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=self._key(name), Body=data)

    def get(self, name: str) -> bytes:
        try:
            answer = self._client.get_object(Bucket=self.bucket, Key=self._key(name))
        except self._client.exceptions.NoSuchKey as exc:
            raise PayloadMissing(name) from exc
        return bytes(answer["Body"].read())

    def exists(self, name: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(name))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise
        return True


def open_payload_store(
    url: str,
    *,
    s3_endpoint: str | None = None,
    s3_region: str | None = None,
    s3_access_key: str | None = None,
    s3_secret_key: str | None = None,
) -> PayloadStore:
    """The payload store of *url*: ``file:///path`` or ``s3://bucket[/prefix]``."""
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return FilePayloadStore(parsed.netloc + parsed.path)
    if parsed.scheme == "s3" and parsed.netloc:
        return S3PayloadStore(
            parsed.netloc,
            parsed.path,
            endpoint=s3_endpoint,
            region=s3_region,
            access_key=s3_access_key,
            secret_key=s3_secret_key,
        )
    raise ValueError(
        f"LAWGRAPH_PAYLOAD_STORE={url!r}: expected file:///path or s3://bucket[/prefix]"
    )
