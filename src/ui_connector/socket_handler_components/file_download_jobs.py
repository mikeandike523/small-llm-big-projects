from __future__ import annotations

import logging
import os
import shutil
import stat
import tempfile
import threading
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from src.ui_connector.socket_handler_components.emit import _emit_backend_log

logger = logging.getLogger(__name__)

MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
_JOB_TTL_SECONDS = 60 * 60
_COPY_CHUNK_BYTES = 1024 * 1024
_DISK_SAFETY_BYTES = 64 * 1024 * 1024
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="slbp-download")
_jobs: dict[str, "DownloadJob"] = {}
_jobs_lock = threading.RLock()


class DownloadJobError(RuntimeError):
    """A user-facing failure while preparing a download."""


@dataclass(frozen=True)
class ArchiveFile:
    path: Path
    archive_name: str
    size: int
    modified_at: float
    mode: int


@dataclass(frozen=True)
class ArchiveManifest:
    files: list[ArchiveFile]
    directories: list[str]
    total_bytes: int


@dataclass
class DownloadJob:
    id: str
    session_id: str
    root: Path
    source: Path
    kind: str
    download_name: str
    state: str
    created_at: float = field(default_factory=time.time)
    file_count: int = 0
    files_processed: int = 0
    total_input_bytes: int = 0
    processed_bytes: int = 0
    archive_bytes: int | None = None
    error: str | None = None
    prepared_path: Path | None = None
    temporary: bool = False
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def snapshot(self) -> dict:
        with self.lock:
            payload = {
                "download_id": self.id,
                "kind": self.kind,
                "download_name": self.download_name,
                "state": self.state,
                "file_count": self.file_count,
                "files_processed": self.files_processed,
                "total_input_bytes": self.total_input_bytes,
                "processed_bytes": self.processed_bytes,
                "archive_bytes": self.archive_bytes,
                "error": self.error,
            }
            if self.state == "ready":
                payload["content_url"] = (
                    f"/api/file-explorer/downloads/{self.id}/content"
                )
            return payload


def _portable_archive_path(*parts: str) -> str:
    return str(PurePosixPath(*parts))


def _within_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _update(job: DownloadJob, **values) -> None:
    with job.lock:
        for key, value in values.items():
            setattr(job, key, value)


def _remove_prepared_file(job: DownloadJob) -> None:
    with job.lock:
        prepared_path = job.prepared_path if job.temporary else None
        job.prepared_path = None if job.temporary else job.prepared_path
    if prepared_path is not None:
        try:
            prepared_path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "Could not remove temporary download archive %s",
                prepared_path,
                exc_info=True,
            )


def _cleanup_expired_jobs() -> None:
    cutoff = time.time() - _JOB_TTL_SECONDS
    expired: list[DownloadJob] = []
    with _jobs_lock:
        for job_id, job in list(_jobs.items()):
            if job.created_at < cutoff and job.state in {
                "ready",
                "complete",
                "failed",
            }:
                expired.append(_jobs.pop(job_id))
    for job in expired:
        _remove_prepared_file(job)


def create_download_job(session_id: str, root: Path, source: Path) -> DownloadJob:
    _cleanup_expired_jobs()
    kind = "directory" if source.is_dir() else "file"
    if kind == "file" and not source.is_file():
        raise DownloadJobError("Requested path is not a regular file or directory")

    download_name = source.name or "download"
    if kind == "directory":
        download_name += ".zip"
    job = DownloadJob(
        id=uuid.uuid4().hex,
        session_id=session_id,
        root=root,
        source=source,
        kind=kind,
        download_name=download_name,
        state="discovering" if kind == "directory" else "ready",
    )
    if kind == "file":
        size = source.stat().st_size
        job.file_count = 1
        job.total_input_bytes = size
        job.archive_bytes = size
        job.prepared_path = source

    with _jobs_lock:
        _jobs[job.id] = job
    if kind == "directory":
        _executor.submit(_run_directory_job, job)
    return job


def get_download_job(job_id: str) -> DownloadJob | None:
    _cleanup_expired_jobs()
    with _jobs_lock:
        return _jobs.get(job_id)


def _discover(job: DownloadJob) -> ArchiveManifest:
    top_level = job.source.name or "download"
    directories = [_portable_archive_path(top_level) + "/"]
    files: list[ArchiveFile] = []
    total_bytes = 0
    pending: list[tuple[Path, str]] = [(job.source, top_level)]

    while pending:
        directory, archive_directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise DownloadJobError(f"Could not read directory: {directory}") from exc

        for entry in entries:
            raw_path = Path(entry.path)
            try:
                resolved = raw_path.resolve(strict=True)
            except OSError as exc:
                raise DownloadJobError(f"Could not resolve: {raw_path}") from exc
            if not _within_root(resolved, job.root):
                raise DownloadJobError(
                    f"Archive entry is outside the session directory: {raw_path.name}"
                )
            archive_name = _portable_archive_path(archive_directory, entry.name)
            if entry.is_symlink() and resolved.is_dir():
                raise DownloadJobError(
                    f"Directory symlinks cannot be archived: {raw_path.name}"
                )
            if entry.is_dir(follow_symlinks=False):
                directories.append(archive_name + "/")
                pending.append((resolved, archive_name))
                continue
            if not resolved.is_file():
                raise DownloadJobError(
                    f"Unsupported archive entry type: {raw_path.name}"
                )
            file_stat = resolved.stat()
            files.append(
                ArchiveFile(
                    path=resolved,
                    archive_name=archive_name,
                    size=file_stat.st_size,
                    modified_at=file_stat.st_mtime,
                    mode=file_stat.st_mode,
                )
            )
            total_bytes += file_stat.st_size
            _update(
                job,
                file_count=len(files),
                total_input_bytes=total_bytes,
            )

    files.sort(key=lambda item: item.archive_name.casefold())
    directories.sort(key=str.casefold)
    return ArchiveManifest(files, directories, total_bytes)


def _compression_bound(size: int) -> int:
    return size + (size >> 12) + (size >> 14) + (size >> 25) + 13


def _required_disk_bytes(manifest: ArchiveManifest) -> int:
    file_data = sum(_compression_bound(item.size) for item in manifest.files)
    names = sum(len(item.archive_name.encode("utf-8")) for item in manifest.files)
    names += sum(len(item.encode("utf-8")) for item in manifest.directories)
    zip_metadata = names * 2 + (len(manifest.files) + len(manifest.directories)) * 128
    return min(MAX_ARCHIVE_BYTES + 1, file_data + zip_metadata)


def _zip_datetime(timestamp: float) -> tuple[int, int, int, int, int, int]:
    value = datetime.fromtimestamp(timestamp)
    year = min(2107, max(1980, value.year))
    return year, value.month, value.day, value.hour, value.minute, value.second


def _ensure_archive_limit(output, job: DownloadJob) -> None:
    archive_bytes = output.tell()
    _update(job, archive_bytes=archive_bytes)
    if archive_bytes > MAX_ARCHIVE_BYTES:
        raise DownloadJobError("ZIP archive exceeds the 2 GiB download limit")


def _build_archive(job: DownloadJob, manifest: ArchiveManifest) -> Path:
    temp_directory = Path(tempfile.gettempdir())
    predicted_archive_bytes = _required_disk_bytes(manifest)
    if predicted_archive_bytes > MAX_ARCHIVE_BYTES:
        raise DownloadJobError("ZIP archive exceeds the 2 GiB download limit")
    required = predicted_archive_bytes + _DISK_SAFETY_BYTES
    if shutil.disk_usage(temp_directory).free < required:
        raise DownloadJobError("Not enough temporary disk space to create the ZIP")

    fd, raw_temp_path = tempfile.mkstemp(
        prefix="slbp-download-", suffix=".zip", dir=temp_directory
    )
    os.close(fd)
    temp_path = Path(raw_temp_path)
    _update(job, prepared_path=temp_path, temporary=True)

    with temp_path.open("w+b") as output:
        with zipfile.ZipFile(
            output,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for directory in manifest.directories:
                info = zipfile.ZipInfo(directory)
                info.external_attr = (stat.S_IFDIR | 0o755) << 16
                archive.writestr(info, b"")
                _ensure_archive_limit(output, job)

            processed_bytes = 0
            for index, member in enumerate(manifest.files, start=1):
                current = member.path.stat()
                if (
                    current.st_size != member.size
                    or current.st_mtime != member.modified_at
                ):
                    raise DownloadJobError(
                        f"File changed while preparing archive: {member.archive_name}"
                    )
                info = zipfile.ZipInfo(
                    member.archive_name, date_time=_zip_datetime(member.modified_at)
                )
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (stat.S_IFREG | stat.S_IMODE(member.mode)) << 16
                with member.path.open("rb") as source:
                    with archive.open(info, mode="w", force_zip64=True) as target:
                        while chunk := source.read(_COPY_CHUNK_BYTES):
                            target.write(chunk)
                            processed_bytes += len(chunk)
                            _update(job, processed_bytes=processed_bytes)
                            _ensure_archive_limit(output, job)
                _update(job, files_processed=index)
                _ensure_archive_limit(output, job)
        _ensure_archive_limit(output, job)
    return temp_path


def _report_failure(job: DownloadJob, exc: Exception) -> None:
    failed_stage = job.state
    public_message = (
        str(exc)
        if isinstance(exc, DownloadJobError)
        else "Could not prepare the ZIP archive"
    )
    _update(job, state="failed", error=public_message)
    logger.exception(
        "Download job %s failed during %s for %s",
        job.id,
        failed_stage,
        job.source,
        exc_info=exc,
    )
    try:
        _emit_backend_log(
            job.session_id,
            {
                "source": "file-download",
                "download_id": job.id,
                "stage": failed_stage,
                "path": str(job.source),
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
    except Exception:
        logger.exception("Could not emit Debug Panel log for download job %s", job.id)


def _run_directory_job(job: DownloadJob) -> None:
    try:
        manifest = _discover(job)
        _update(
            job,
            state="zipping",
            file_count=len(manifest.files),
            total_input_bytes=manifest.total_bytes,
        )
        archive_path = _build_archive(job, manifest)
        _update(
            job,
            state="ready",
            prepared_path=archive_path,
            archive_bytes=archive_path.stat().st_size,
        )
    except Exception as exc:
        _report_failure(job, exc)
        _remove_prepared_file(job)


def mark_download_complete(job: DownloadJob) -> None:
    _update(job, state="complete")
    _remove_prepared_file(job)
