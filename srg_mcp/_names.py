"""Asset display names (SRGDEV-909).

The backend builds a Drive file's storage key as ``{name}.{extension}`` and the
SRG+ apps send the name WITHOUT the extension. A name that still carries it
("clip.mp4" + extension "mp4") gave a key of "clip.mp4.mp4".
"""

from __future__ import annotations

from pathlib import PurePath


def strip_extension(name: str, extension: str | None) -> str:
    """Drop a trailing ``.<extension>`` (case-insensitive) from ``name``.

    Only that exact suffix goes: "v1.2 final.mp4" with extension "mp4" becomes
    "v1.2 final", and "v1.2 final" stays as it is. A name that is nothing but
    the extension (".mp4") is left alone so it never turns empty.
    """
    ext = (extension or "").lstrip(".")
    if not ext:
        return name
    suffix = f".{ext}"
    if len(name) > len(suffix) and name.lower().endswith(suffix.lower()):
        return name[: -len(suffix)]
    return name


def name_from_path(path: str) -> str:
    """The file's name without its extension (the app's default display name)."""
    return PurePath(path).stem
