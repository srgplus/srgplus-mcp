"""A channel category's display options in plain words, both ways.

The options as read (GET /api/v2/channels/{id}, each category's ``options``) and as written
(POST/PUT of a category) have the same JSON shape:

    {"expandable": true,
     "view": {"presentation":
         {"$type": "Standard", "global": {"type": "Classic"}}
      or {"$type": "Custom", "main": {"type": "List", "subType": "Compact"}, "expanded": {"type": "Waterfall"}}},
     "cover": {"aspect":
         {"$type": "Standard", "ratio": {"ratio": "SixteenByNine", "position": "Vertical"}}
      or {"$type": "Custom", "mobileRatio": {...}, "desktopRatio": {...}}},
     "progression": {"progression": false, "sequentialCompletion": false}}

The apps call the views Grid (Waterfall), List and Scroll (Classic, the horizontal row).
"Standard" is one view with large cards that opens as a grid in the apps. "Custom" adds the
card size (subType Extended = large, Compact = small; the backend drops a subType on
Standard, so a small card size needs Custom) and the view the category opens in when
expanded (Waterfall or List, never Classic). The backend parses these names case-sensitively
and reads "$type" only as the FIRST key of an object.

A cover ratio is said here as the card's real shape, width:height, the way the apps draw it:
"16:9" is SixteenByNine landscape, "9:16" the same turned upright (position Vertical), and
"4:5" is FourByFive Vertical (FourByFive without a position is drawn 5:4).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

VIEWS = {
    "grid": "Waterfall",
    "waterfall": "Waterfall",
    "list": "List",
    "scroll": "Classic",
    "classic": "Classic",
    "row": "Classic",
    "carousel": "Classic",
}
VIEW_NAMES = {"Waterfall": "grid", "List": "list", "Classic": "scroll"}
OPEN_VIEWS = {"grid": "Waterfall", "waterfall": "Waterfall", "list": "List"}
CARD_SIZES = {"large": "Extended", "extended": "Extended", "big": "Extended", "small": "Compact", "compact": "Compact"}
SIZE_NAMES = {"Extended": "large", "Compact": "small"}

# width:height → (ratio, position)
RATIOS = {
    "original": ("Original", None),
    "square": ("Square", None),
    "1:1": ("Square", None),
    "16:9": ("SixteenByNine", "Horizontal"),
    "9:16": ("SixteenByNine", "Vertical"),
    "3:2": ("ThreeByTwo", "Horizontal"),
    "2:3": ("ThreeByTwo", "Vertical"),
    "5:4": ("FourByFive", "Horizontal"),
    "4:5": ("FourByFive", "Vertical"),
}
_RATIO_SHAPES = {
    ("SixteenByNine", False): "16:9",
    ("SixteenByNine", True): "9:16",
    ("ThreeByTwo", False): "3:2",
    ("ThreeByTwo", True): "2:3",
    ("FourByFive", False): "5:4",
    ("FourByFive", True): "4:5",
}


def _key(value: Any) -> str:  # noqa: ANN401
    return " ".join(str(value).strip().lower().split())


def _pick(value: Any, table: dict[str, str], name: str, choices: str) -> str:  # noqa: ANN401
    picked = table.get(_key(value))
    if picked is None:
        raise ValueError(f"{name} must be {choices}, got {value!r}.")
    return picked


def ratio_of(value: Any) -> tuple[str, str | None]:  # noqa: ANN401
    """"16:9", "9x16", "4/5", "square", "original" → (ratio, position)."""
    key = _key(value).replace(" ", "").replace("x", ":").replace("/", ":").replace("×", ":")
    picked = RATIOS.get(key)
    if picked is None:
        raise ValueError(
            "cover_ratio must be the card's shape as width:height: 16:9, 9:16, 3:2, 2:3, 5:4, 4:5, "
            f"square or original, got {value!r}."
        )
    return picked


def _type_first(value: Any) -> Any:  # noqa: ANN401
    """The same object with "$type" moved to the front (the backend reads it only there)."""
    if isinstance(value, dict) and "$type" in value:
        return {"$type": value["$type"], **{k: v for k, v in value.items() if k != "$type"}}
    return value


def default_options() -> dict:
    """What a category gets when nothing is chosen (the backend defaults)."""
    return {
        "view": {"presentation": {"$type": "Standard", "global": {"type": "Classic"}}},
        "progression": {"progression": False, "sequentialCompletion": False},
        "cover": {"aspect": {"$type": "Standard", "ratio": {"ratio": "Original", "position": None}}},
        "expandable": True,
    }


@dataclass
class _View:
    kind: str  # Classic | List | Waterfall
    size: str | None  # Extended | Compact | None
    opens: str  # Waterfall | List


def _view_of(options: dict) -> _View:
    presentation = ((options.get("view") or {}).get("presentation")) or {}
    if presentation.get("$type") == "Custom":
        main = presentation.get("main") or {}
        return _View(
            kind=main.get("type") or "Classic",
            size=main.get("subType"),
            opens=(presentation.get("expanded") or {}).get("type") or "Waterfall",
        )
    kind = (presentation.get("global") or {}).get("type") or "Classic"
    # Standard draws large cards and opens as a grid in the apps.
    return _View(kind=kind, size=None if kind == "Classic" else "Extended", opens="Waterfall")


def _presentation(view: _View) -> dict:
    standard = view.opens == "Waterfall" and (
        view.size is None if view.kind == "Classic" else view.size == "Extended"
    )
    if standard:
        return {"$type": "Standard", "global": {"type": view.kind}}
    return {
        "$type": "Custom",
        "main": {"type": view.kind, "subType": view.size},
        "expanded": {"type": view.opens},
    }


def with_changes(
    options: dict | None,
    *,
    view: str | None = None,
    card_size: str | None = None,
    open_view: str | None = None,
    cover_ratio: str | None = None,
    expandable: bool | None = None,
    progression: bool | None = None,
    sequential: bool | None = None,
) -> dict:
    """A copy of ``options`` (or the defaults) with only the given settings changed.

    Raises ValueError, before anything is written, for a value the apps cannot show.
    """
    out = copy.deepcopy(options) if options else default_options()
    for part, default in default_options().items():
        if out.get(part) is None:
            out[part] = default

    if view is not None or card_size is not None or open_view is not None:
        state = _view_of(out)
        if view is not None:
            kind = _pick(view, VIEWS, "view", "grid, list or scroll")
            if kind == "Classic":
                state.size = None
            elif state.kind == "Classic" and state.size is None:
                state.size = "Extended"
            state.kind = kind
        if card_size is not None:
            if state.kind == "Classic":
                raise ValueError(
                    "card_size is for the grid and list views; a scroll view has one card size. "
                    "Pass view='grid' or view='list' with it."
                )
            state.size = _pick(card_size, CARD_SIZES, "card_size", "large or small")
        if open_view is not None:
            state.opens = _pick(open_view, OPEN_VIEWS, "open_view", "grid or list")
        out["view"] = {"presentation": _presentation(state)}
    else:
        presentation = (out.get("view") or {}).get("presentation")
        out["view"] = {"presentation": _type_first(presentation) if presentation else _presentation(_view_of({}))}

    if cover_ratio is not None:
        ratio, position = ratio_of(cover_ratio)
        out["cover"] = {"aspect": {"$type": "Standard", "ratio": {"ratio": ratio, "position": position}}}
    else:
        aspect = (out.get("cover") or {}).get("aspect")
        out["cover"] = {"aspect": _type_first(aspect) if aspect else default_options()["cover"]["aspect"]}

    if progression is False and sequential:
        raise ValueError("sequential needs progression: pass progression=True (or leave it out).")
    steps = dict(out.get("progression") or {})
    steps.setdefault("progression", False)
    steps.setdefault("sequentialCompletion", False)
    if progression is not None:
        steps["progression"] = bool(progression)
        if not progression:
            steps["sequentialCompletion"] = False
    if sequential is not None:
        steps["sequentialCompletion"] = bool(sequential)
        if sequential:
            steps["progression"] = True
    out["progression"] = steps

    if expandable is not None:
        out["expandable"] = bool(expandable)
    return out


def _shape(ratio: dict | None) -> str | None:
    ratio = ratio or {}
    name = ratio.get("ratio")
    if name in ("Original", "Square"):
        return name.lower()
    shape = _RATIO_SHAPES.get((name, ratio.get("position") == "Vertical"))
    return shape or name


def settings_of(category: dict) -> dict:
    """A category's settings in the words the tools take (read from get_channel's raw shape)."""
    options = category.get("options") or {}
    view = _view_of(options)
    aspect = ((options.get("cover") or {}).get("aspect")) or {}
    if aspect.get("$type") == "Custom":
        cover: Any = {"mobile": _shape(aspect.get("mobileRatio")), "desktop": _shape(aspect.get("desktopRatio"))}
    else:
        cover = _shape(aspect.get("ratio"))
    steps = options.get("progression") or {}
    return {
        "pinned": bool(category.get("isPinned")),
        "view": VIEW_NAMES.get(view.kind, view.kind),
        "card_size": None if view.kind == "Classic" else SIZE_NAMES.get(view.size or ""),
        "open_view": VIEW_NAMES.get(view.opens, view.opens),
        "cover_ratio": cover,
        "expandable": bool(options.get("expandable", True)),
        "progression": bool(steps.get("progression")),
        "sequential": bool(steps.get("sequentialCompletion")),
        "notifications": bool(category.get("notificationsEnabled")),
        "email": bool(category.get("emailEnabled")),
    }
