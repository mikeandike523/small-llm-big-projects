"""Sidebar shortcuts for the browser-based folder picker.

Home is always first. The rest come from, in order:

1. On Linux, the XDG user-dirs file (``~/.config/user-dirs.dirs``), which most
   desktop distros write and which knows localized names (``~/Dokumente``).
2. A per-OS / per-distro list of conventional folders (the constants below).

Only folders that actually exist are returned; duplicates are dropped.
"""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

from src.utils.cwd_policy import OsFamily, current_os_family

# (label, path relative to home)
Shortcut = tuple[str, str]

_COMMON_MEDIA: tuple[Shortcut, ...] = (
    ("Desktop", "Desktop"),
    ("Documents", "Documents"),
    ("Downloads", "Downloads"),
    ("Music", "Music"),
    ("Pictures", "Pictures"),
    ("Videos", "Videos"),
)

_COMMON_CODE: tuple[Shortcut, ...] = (
    ("Projects", "Projects"),
    ("projects", "projects"),
    ("src", "src"),
    ("code", "code"),
    ("repos", "repos"),
    ("dev", "dev"),
)

FOLDER_SHORTCUTS_DEFAULT: tuple[Shortcut, ...] = _COMMON_MEDIA + _COMMON_CODE

FOLDER_SHORTCUTS_UBUNTU: tuple[Shortcut, ...] = (
    _COMMON_MEDIA + (("Public", "Public"), ("Templates", "Templates")) + _COMMON_CODE
)

FOLDER_SHORTCUTS_DEBIAN: tuple[Shortcut, ...] = FOLDER_SHORTCUTS_UBUNTU

FOLDER_SHORTCUTS_FEDORA: tuple[Shortcut, ...] = FOLDER_SHORTCUTS_UBUNTU

FOLDER_SHORTCUTS_ARCH: tuple[Shortcut, ...] = FOLDER_SHORTCUTS_DEFAULT

FOLDER_SHORTCUTS_MACOS: tuple[Shortcut, ...] = (
    ("Desktop", "Desktop"),
    ("Documents", "Documents"),
    ("Downloads", "Downloads"),
    ("Movies", "Movies"),
    ("Music", "Music"),
    ("Pictures", "Pictures"),
    ("Developer", "Developer"),
) + _COMMON_CODE

FOLDER_SHORTCUTS_WINDOWS: tuple[Shortcut, ...] = (
    ("Desktop", "Desktop"),
    ("Documents", "Documents"),
    ("Downloads", "Downloads"),
    ("Music", "Music"),
    ("Pictures", "Pictures"),
    ("Videos", "Videos"),
    ("OneDrive", "OneDrive"),
) + _COMMON_CODE

# Keyed by os-release ID; ID_LIKE values are tried after ID.
FOLDER_SHORTCUTS_BY_DISTRO: dict[str, tuple[Shortcut, ...]] = {
    "ubuntu": FOLDER_SHORTCUTS_UBUNTU,
    "debian": FOLDER_SHORTCUTS_DEBIAN,
    "fedora": FOLDER_SHORTCUTS_FEDORA,
    "rhel": FOLDER_SHORTCUTS_FEDORA,
    "arch": FOLDER_SHORTCUTS_ARCH,
}

# XDG user-dirs keys, in sidebar order, with their display labels.
_XDG_KEYS: tuple[tuple[str, str], ...] = (
    ("XDG_DESKTOP_DIR", "Desktop"),
    ("XDG_DOCUMENTS_DIR", "Documents"),
    ("XDG_DOWNLOAD_DIR", "Downloads"),
    ("XDG_MUSIC_DIR", "Music"),
    ("XDG_PICTURES_DIR", "Pictures"),
    ("XDG_VIDEOS_DIR", "Videos"),
)

_XDG_LINE = re.compile(r'^\s*(XDG_[A-Z]+_DIR)\s*=\s*"(.*)"\s*$')


def _portable(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def _linux_distro_ids() -> list[str]:
    try:
        info = platform.freedesktop_os_release()
    except OSError:
        return []
    ids = [info.get("ID", "")] + info.get("ID_LIKE", "").split()
    return [i.strip().lower() for i in ids if i.strip()]


def _distro_shortcuts() -> tuple[Shortcut, ...]:
    for distro_id in _linux_distro_ids():
        if distro_id in FOLDER_SHORTCUTS_BY_DISTRO:
            return FOLDER_SHORTCUTS_BY_DISTRO[distro_id]
    return FOLDER_SHORTCUTS_DEFAULT


def read_xdg_user_dirs(home: Path) -> list[tuple[str, Path]]:
    """Parse the XDG user-dirs file into ``(label, path)`` pairs.

    Entries pointing at home itself mean "disabled" per the XDG spec and are
    skipped. A missing or unreadable file yields an empty list.
    """
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(home / ".config")
    try:
        text = (Path(config_home) / "user-dirs.dirs").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = _XDG_LINE.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    result: list[tuple[str, Path]] = []
    for key, label in _XDG_KEYS:
        value = found.get(key)
        if not value:
            continue
        if value.startswith("$HOME"):
            path = Path(str(home) + value[len("$HOME") :])
        elif value.startswith("/"):
            path = Path(value)
        else:
            continue
        if path != home:
            result.append((label, path))
    return result


def _candidates(home: Path, family: OsFamily) -> list[tuple[str, Path]]:
    if family == "windows":
        return [(label, home / rel) for label, rel in FOLDER_SHORTCUTS_WINDOWS]
    if family == "macos":
        return [(label, home / rel) for label, rel in FOLDER_SHORTCUTS_MACOS]
    xdg = read_xdg_user_dirs(home)
    xdg_labels = {label for label, _ in xdg}
    conventional = [
        (label, home / rel)
        for label, rel in _distro_shortcuts()
        if label not in xdg_labels
    ]
    return xdg + conventional


def get_folder_shortcuts(home: Path, family: OsFamily | None = None) -> list[dict]:
    """Return ``[{"label", "path"}]`` for existing shortcut folders, Home first."""
    family = family or current_os_family()
    fold = (lambda text: text) if family == "linux" else str.casefold
    shortcuts = [{"label": "Home", "path": _portable(home)}]
    seen = {fold(_portable(home))}
    for label, path in _candidates(home, family):
        key = fold(_portable(path))
        if key in seen:
            continue
        try:
            if not path.is_dir():
                continue
        except OSError:
            continue
        seen.add(key)
        shortcuts.append({"label": label, "path": _portable(path)})
    return shortcuts
