"""Object storage, behind one seam (architecture §5.6).

The API never streams a file body. It checks the permission, then hands out a time-limited URL and
gets out of the way — which is what keeps a 25 MB upload off the application process and lets the
same code path serve a 200 KB figure and a large dataset.

Keys are derived from ids and a content hash, never from the filename. A filename is user input; a
key is a path. The original extension is kept only when it is one we recognise, because it is
useful for the browser and useless as a security boundary.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app.core.clock import now

log = logging.getLogger(__name__)

DEFAULT_PUT_TTL = 900  # 15 minutes: long enough for a slow upload, short enough to be a grant
DEFAULT_GET_TTL = 300

# Extensions worth carrying into the key. Everything else is dropped: an unrecognised suffix helps
# nobody and a recognised-but-executable one is a liability (REP-04, requirements §11 "Security").
SAFE_EXTENSIONS = frozenset(
    {
        "md",
        "txt",
        "csv",
        "tsv",
        "json",
        "pdf",
        "docx",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "webp",
        "zip",
        "ipynb",
        "tex",
        "bib",
    }
)

CONTENT_TYPES = {
    "md": "text/markdown",
    "txt": "text/plain",
    "csv": "text/csv",
    "tsv": "text/tab-separated-values",
    "json": "application/json",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "svg": "image/svg+xml",
    "webp": "image/webp",
    "zip": "application/zip",
    "ipynb": "application/x-ipynb+json",
    "tex": "text/x-tex",
    "bib": "text/x-bibtex",
}


@dataclass(frozen=True, slots=True)
class PresignedUrl:
    url: str
    expires_in: int
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ObjectInfo:
    key: str
    byte_size: int
    content_type: str
    modified_at: datetime


class ObjectStore(Protocol):
    async def presigned_put(
        self, key: str, *, content_type: str, expires_in: int = DEFAULT_PUT_TTL
    ) -> PresignedUrl: ...

    async def presigned_get(
        self, key: str, *, expires_in: int = DEFAULT_GET_TTL, filename: str | None = None
    ) -> PresignedUrl: ...

    async def head(self, key: str) -> ObjectInfo | None: ...

    async def exists(self, key: str) -> bool: ...

    async def get_bytes(self, key: str) -> bytes | None: ...

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> ObjectInfo: ...

    async def delete(self, key: str) -> None: ...

    async def bucket_ready(self) -> bool: ...

    async def ensure_bucket(self) -> None: ...


def _attachment(filename: str | None) -> str:
    if not filename:
        return "attachment"
    quoted = filename.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")
    return f'attachment; filename="{quoted}"'


def extension_of(filename: str) -> str:
    _, _, suffix = filename.rpartition(".")
    lowered = suffix.lower()
    return lowered if lowered in SAFE_EXTENSIONS else ""


def content_type_for(filename: str, fallback: str = "application/octet-stream") -> str:
    return CONTENT_TYPES.get(extension_of(filename), fallback)


def extension_for_content_type(content_type: str) -> str:
    """The extension a server's own Content-Type implies.

    A fetched URL usually ends in something that is not a file extension — `/abs/2401.00001`, a
    query string, a trailing slash — so the server's declaration is the better evidence of what the
    bytes are, and extraction reads better with it.
    """
    declared = content_type.split(";", 1)[0].strip().lower()
    for extension, known in CONTENT_TYPES.items():
        if known == declared:
            return extension
    if declared.startswith("text/"):
        return "txt"
    return ""


SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def is_sha256_hex(value: str) -> bool:
    """A SHA-256 digest, lowercase hex. Anything else must not reach a key."""
    return bool(SHA256_HEX.match(value))


def storage_key(
    *, workspace_id: UUID, artifact_id: UUID, version_no: int, sha256: str, filename: str
) -> str:
    """`{workspace}/artifacts/{artifact}/{version}/{sha256}.{ext}` (architecture §5.6).

    A key is a path, so every segment interpolated into it has to be something a caller cannot
    shape. The ids are ours; the checksum is the client's, so it is checked here as well as at the
    edge — a 64-character string of `../` would otherwise normalise above the workspace prefix and
    turn a presigned PUT into a write anywhere in the bucket.
    """
    if not is_sha256_hex(sha256):
        raise ValueError("a storage key needs a lowercase hex SHA-256 digest")
    extension = extension_of(filename)
    leaf = f"{sha256}.{extension}" if extension else sha256
    return f"{workspace_id}/artifacts/{artifact_id}/{version_no}/{leaf}"


def extracted_text_key(original_key: str) -> str:
    """The extracted text sits beside its original, so the pair is obvious in the bucket."""
    return f"{original_key.rsplit('/', 1)[0]}/extracted.txt"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InMemoryObjectStore:
    """The store tests and the demo run against: no network, same contract.

    Its presigned URLs are not real credentials, which is the point — nothing in the test suite
    should be able to upload to anywhere by accident.
    """

    def __init__(self, base_url: str = "memory://objects") -> None:
        self.base_url = base_url
        self._objects: dict[str, tuple[bytes, str, datetime]] = {}

    async def presigned_put(
        self, key: str, *, content_type: str, expires_in: int = DEFAULT_PUT_TTL
    ) -> PresignedUrl:
        return PresignedUrl(
            url=f"{self.base_url}/{key}?upload=1",
            expires_in=expires_in,
            headers={"Content-Type": content_type},
        )

    async def presigned_get(
        self, key: str, *, expires_in: int = DEFAULT_GET_TTL, filename: str | None = None
    ) -> PresignedUrl:
        return PresignedUrl(url=f"{self.base_url}/{key}", expires_in=expires_in)

    async def bucket_ready(self) -> bool:
        return True

    async def ensure_bucket(self) -> None:
        return None

    async def head(self, key: str) -> ObjectInfo | None:
        stored = self._objects.get(key)
        if stored is None:
            return None
        data, content_type, modified = stored
        return ObjectInfo(
            key=key, byte_size=len(data), content_type=content_type, modified_at=modified
        )

    async def exists(self, key: str) -> bool:
        return key in self._objects

    async def get_bytes(self, key: str) -> bytes | None:
        stored = self._objects.get(key)
        return None if stored is None else stored[0]

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> ObjectInfo:
        self._objects[key] = (data, content_type, now())
        info = await self.head(key)
        assert info is not None
        return info

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)


class S3ObjectStore:
    """MinIO, or anything else speaking the S3 API (architecture §3)."""

    def __init__(self, settings: Any) -> None:
        import boto3

        self._bucket = settings.s3_bucket

        from botocore.config import Config

        # Path addressing, stated rather than inferred. Left on "auto", botocore may put a
        # DNS-compliant bucket name in front of the host — `rm-dev.objects.example.edu` — which
        # needs a wildcard certificate and a wildcard DNS record that nothing here provisions.
        # It resolves to path style today for both endpoints; this keeps it that way.
        config = Config(s3={"addressing_style": "path"})

        def client(endpoint: str) -> Any:
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
                region_name="us-east-1",
                config=config,
            )

        self._client = client(settings.s3_endpoint)
        # Presigned URLs are signed for the host the browser will send them to, which is not the
        # host this process talks to. A second client rather than a rewritten URL, because the
        # signature covers Host: editing the string produces a link the store rejects.
        public = getattr(settings, "s3_public_endpoint", "") or settings.s3_endpoint
        self._signer = self._client if public == settings.s3_endpoint else client(public)

    async def presigned_put(
        self, key: str, *, content_type: str, expires_in: int = DEFAULT_PUT_TTL
    ) -> PresignedUrl:
        url = await asyncio.to_thread(
            self._signer.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        return PresignedUrl(url=url, expires_in=expires_in, headers={"Content-Type": content_type})

    async def presigned_get(
        self, key: str, *, expires_in: int = DEFAULT_GET_TTL, filename: str | None = None
    ) -> PresignedUrl:
        params: dict[str, Any] = {"Bucket": self._bucket, "Key": key}
        # Always an attachment, named or not. An uploaded .html fetched inline would run its own
        # script in the storage origin, next to every other artifact in the bucket — so the
        # disposition is set here rather than left to each caller to remember (requirements §11
        # "Security"). A quote in the filename would otherwise close the parameter and start
        # another, so it is escaped the way RFC 6266 asks.
        params["ResponseContentDisposition"] = _attachment(filename)
        url = await asyncio.to_thread(
            self._signer.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
        )
        return PresignedUrl(url=url, expires_in=expires_in)

    async def head(self, key: str) -> ObjectInfo | None:
        try:
            response = await asyncio.to_thread(
                self._client.head_object, Bucket=self._bucket, Key=key
            )
        except Exception:  # noqa: BLE001 - a missing object is an absence, not a failure
            return None
        return ObjectInfo(
            key=key,
            byte_size=int(response.get("ContentLength", 0)),
            content_type=str(response.get("ContentType", "application/octet-stream")),
            modified_at=response.get("LastModified", now()),
        )

    async def exists(self, key: str) -> bool:
        return await self.head(key) is not None

    async def get_bytes(self, key: str) -> bytes | None:
        try:
            response = await asyncio.to_thread(
                self._client.get_object, Bucket=self._bucket, Key=key
            )
        except Exception:  # noqa: BLE001
            return None
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body

    async def put_bytes(self, key: str, data: bytes, *, content_type: str) -> ObjectInfo:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return ObjectInfo(
            key=key, byte_size=len(data), content_type=content_type, modified_at=now()
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def bucket_ready(self) -> bool:
        """Whether the bucket is actually there.

        Readiness used to ping the store's own liveness endpoint, which answers happily while the
        bucket is missing — so the status page read `object_storage ok` and every upload came back
        `NoSuchBucket`. A store that cannot store anything is not ready.
        """
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except Exception:  # noqa: BLE001 - absent or unreachable are both "not ready"
            return False
        return True

    async def ensure_bucket(self) -> None:
        """Create the bucket if it is missing. Idempotent, and never fatal.

        A deployment whose credentials may not create buckets is a normal arrangement, not a
        misconfiguration to crash on: the bucket is made by whoever provisions the account, and
        readiness reports the truth either way.
        """
        if await self.bucket_ready():
            return
        try:
            await asyncio.to_thread(self._client.create_bucket, Bucket=self._bucket)
            log.info("created object storage bucket %s", self._bucket)
        except Exception as error:  # noqa: BLE001
            log.warning("could not create bucket %s: %s", self._bucket, error)


_store: ObjectStore | None = None


def register_store(store: ObjectStore) -> ObjectStore:
    global _store
    _store = store
    return store


def current_store() -> ObjectStore:
    """The configured store, or the in-memory one, so a test never reaches a bucket by accident."""
    if _store is None:
        return InMemoryObjectStore()
    return _store


def build_store(settings: Any) -> ObjectStore:
    if not settings.s3_access_key:
        log.info("no object storage credentials configured; attachments stay in memory")
        return InMemoryObjectStore()
    return S3ObjectStore(settings)
