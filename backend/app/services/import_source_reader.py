"""Verified source reader -- closing the `parse(None)` gap for byte-backed
sources.

Roadmap PR20A (docs/design/PR20_EQUIPMENT_MASTER_IMPORT_PLAN.md §6.5,
architecture-approved via the merged Design PR #89). A new, PR20-owned
infrastructure component, called by the framework
(`import_validation_service.run_validation`/`import_execution_service.
run_dry_run`) immediately before invoking `adapter.parse(...)`/
`adapter.plan_dry_run(...)` for a source that has verified bytes behind
it -- never by the adapter itself, which never queries `import_source_
blobs` or any storage mechanism on its own (§6.5's ownership boundary).

Every dataset_type that does not use PR20A's byte-storage upload endpoint
(§6.2) -- every dataset_type registered only via the existing PR19A
metadata-only `POST /{id}/source` -- has no `import_source_blobs` row for
its source, so the framework's own blob-existence check
(`app.crud.import_source_blob.exists_for_source`) leaves `parse()`
receiving `None` exactly as PR19A shipped it, unchanged. This module is
purely additive: it changes no existing adapter's observable behavior."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import import_source_blob as import_source_blob_crud
from app.services.import_service import MAX_UPLOAD_BYTES


class SourceBlobMissingError(Exception):
    """§6.5 failure-classification table: the blob row referenced by
    `import_source_id` does not exist. Structural/crash failure -- raised
    uncaught, propagating through the same TX1/TX2 crash path every other
    unhandled exception during validate/dry-run already uses. Should never
    actually occur given §6.2's atomic registration contract; this is
    defense-in-depth against a theoretical data-integrity gap, not an
    expected operational path."""


class SourceChecksumMismatchError(Exception):
    """§6.5: the blob's recomputed checksum, read back at read time,
    differs from `import_sources.checksum`. Indicates corruption or
    tampering occurring strictly between write-time verification (§6.2)
    and this read -- never a business/row-level problem, so never
    expressed as a `ValidationFinding`."""


class SourceLengthMismatchError(Exception):
    """§6.5: `len(content) != descriptor.expected_byte_size`. Same
    structural/crash classification as `SourceChecksumMismatchError`."""


@dataclass(frozen=True)
class SourceDescriptor:
    """Immutable. What the framework already knows about a registered
    source before reading its bytes -- never an ORM model, so this can be
    captured and passed around after the ORM session that produced it may
    have expired/rolled back."""

    import_source_id: uuid.UUID
    import_session_id: uuid.UUID
    dataset_type: str
    expected_checksum: str
    expected_byte_size: int
    content_type: str | None
    # Untrusted metadata only -- never used for parsing/verification
    # decisions (§6.5).
    original_filename: str | None
    registration_status: str  # "registered" | "frozen"


@dataclass(frozen=True)
class VerifiedSourceContent:
    """Returned only after every check in `ImportSourceReader.open_verified`
    has passed. This, not raw bytes and not a storage locator, is what
    `raw_input` actually is for `adapter.parse()` once a source has
    verified bytes behind it."""

    content: bytes
    source_descriptor: SourceDescriptor


class ImportSourceReader:
    """§6.5: blob-load, bound-check, checksum-recompute, and
    length-verify at read time -- defense-in-depth, independent of write-time
    verification (§6.2), since it protects against corruption/tampering
    occurring strictly between write and read, which write-time
    verification alone cannot detect."""

    async def open_verified(self, db: AsyncSession, descriptor: SourceDescriptor) -> VerifiedSourceContent:
        content = await import_source_blob_crud.get_content(db, import_source_id=descriptor.import_source_id)
        if content is None:
            raise SourceBlobMissingError(
                f"No import_source_blobs row exists for import_source_id={descriptor.import_source_id!r}."
            )
        # §7/§21: bounded byte/file limit re-enforced again at read time --
        # defense-in-depth, never trusting that write-time enforcement
        # (§6.2, which already bounds every upload to MAX_UPLOAD_BYTES
        # before it is ever persisted) alone remains sufficient forever.
        if len(content) > MAX_UPLOAD_BYTES:
            raise SourceLengthMismatchError(
                f"Stored source content exceeds the maximum allowed size of {MAX_UPLOAD_BYTES} bytes at read time."
            )
        actual_checksum = hashlib.sha256(content).hexdigest()
        if actual_checksum != descriptor.expected_checksum:
            raise SourceChecksumMismatchError(
                "Stored source content's checksum no longer matches import_sources.checksum."
            )
        if len(content) != descriptor.expected_byte_size:
            raise SourceLengthMismatchError(
                "Stored source content's byte length no longer matches import_sources.byte_size."
            )
        return VerifiedSourceContent(content=content, source_descriptor=descriptor)
