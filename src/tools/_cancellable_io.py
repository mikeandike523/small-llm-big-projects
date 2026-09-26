from __future__ import annotations

import os
import shutil
import threading
import tempfile

from src.tools._cancellation import check_cancelled


_BINARY_CHUNK_SIZE = 1024 * 1024
_TEXT_CHUNK_SIZE = 256 * 1024


def copy_file_cancellable(
    src: str,
    dst: str,
    *,
    tool_name: str,
    cancel_event: threading.Event | None,
    preserve_metadata: bool,
    follow_symlinks: bool = True,
) -> str:
    """Copy a file while polling once per MiB; return the final destination."""
    check_cancelled(tool_name, cancel_event)
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))

    # Preserve shutil's symlink-copy semantics for this fast metadata-only case.
    if not follow_symlinks and os.path.islink(src):
        result = (
            shutil.copy2(src, dst, follow_symlinks=False)
            if preserve_metadata
            else shutil.copy(src, dst, follow_symlinks=False)
        )
        check_cancelled(tool_name, cancel_event)
        return result

    if os.path.exists(dst) and os.path.samefile(src, dst):
        raise shutil.SameFileError(src, dst, "are the same file")

    with open(src, "rb") as source, open(dst, "wb") as target:
        while True:
            check_cancelled(tool_name, cancel_event)
            chunk = source.read(_BINARY_CHUNK_SIZE)
            if not chunk:
                break
            target.write(chunk)

    if preserve_metadata:
        shutil.copystat(src, dst, follow_symlinks=follow_symlinks)
    else:
        shutil.copymode(src, dst, follow_symlinks=follow_symlinks)
    check_cancelled(tool_name, cancel_event)
    return dst


def read_text_cancellable(
    path,
    *,
    tool_name: str,
    cancel_event: threading.Event | None,
    encoding: str = "utf-8",
    newline=None,
) -> str:
    chunks: list[str] = []
    with open(path, "r", encoding=encoding, newline=newline) as handle:
        while True:
            check_cancelled(tool_name, cancel_event)
            chunk = handle.read(_TEXT_CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
    return "".join(chunks)


def write_text_cancellable(
    path,
    content: str,
    *,
    tool_name: str,
    cancel_event: threading.Event | None,
    encoding: str = "utf-8",
    newline=None,
) -> None:
    path_string = os.fspath(path)
    parent = os.path.dirname(os.path.abspath(path_string))
    descriptor, temporary = tempfile.mkstemp(prefix=".slbp-write-", dir=parent)
    try:
        with os.fdopen(
            descriptor, "w", encoding=encoding, newline=newline
        ) as handle:
            for offset in range(0, len(content), _TEXT_CHUNK_SIZE):
                check_cancelled(tool_name, cancel_event)
                handle.write(content[offset : offset + _TEXT_CHUNK_SIZE])
            check_cancelled(tool_name, cancel_event)
        if os.path.exists(path_string):
            shutil.copymode(path_string, temporary)
        check_cancelled(tool_name, cancel_event)
        os.replace(temporary, path_string)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def remove_tree_cancellable(
    path: str,
    *,
    tool_name: str,
    cancel_event: threading.Event | None,
) -> None:
    """Remove a directory tree while checking cancellation for every entry."""
    for root, directories, files in os.walk(path, topdown=False, followlinks=False):
        check_cancelled(tool_name, cancel_event)
        for filename in files:
            check_cancelled(tool_name, cancel_event)
            os.unlink(os.path.join(root, filename))
        for dirname in directories:
            check_cancelled(tool_name, cancel_event)
            child = os.path.join(root, dirname)
            if os.path.islink(child):
                os.unlink(child)
            else:
                os.rmdir(child)
    check_cancelled(tool_name, cancel_event)
    os.rmdir(path)
