from __future__ import annotations
import re
from dataclasses import dataclass


WEIGHT_MAP: list[tuple[str, int]] = [
    ("Thin", 100),
    ("Hairline", 100),
    ("ExtraLight", 200),
    ("UltraLight", 200),
    ("Light", 300),
    ("DemiLight", 350),
    ("Book", 380),
    ("Regular", 400),
    ("Normal", 400),
    ("Roman", 400),
    ("Medium", 500),
    ("Demi", 600),
    ("SemiBold", 600),
    ("DemiBold", 600),
    ("Bold", 700),
    ("ExtraBold", 800),
    ("UltraBold", 800),
    ("Heavy", 800),
    ("Black", 900),
    ("Ultra", 950),
]

# Sorted longest-first so "ExtraBold" matches before "Bold"
_WEIGHT_SORTED = sorted(WEIGHT_MAP, key=lambda x: -len(x[0]))


@dataclass
class FontEntry:
    ps_name: str
    family: str
    weight_kw: str
    weight_num: int
    is_italic: bool
    style: str


def _parse_weight(style_or_suffix: str) -> tuple[str, int]:
    s = style_or_suffix.replace("-", "").replace(" ", "")
    # Check italic
    is_italic_part = bool(re.search(r"(?i)italic|oblique", s))
    clean = re.sub(r"(?i)italic|oblique", "", s)
    for kw, num in _WEIGHT_SORTED:
        if re.search(re.escape(kw), clean, re.IGNORECASE):
            return (kw, num)
    return ("Regular", 400)


def build_font_index(app) -> dict[str, list[FontEntry]]:
    index: dict[str, list[FontEntry]] = {}
    try:
        fonts = app.Fonts
        count = fonts.Count
    except Exception:
        return index
    for i in range(count):
        try:
            font = fonts[i]
            ps_name = font.Name
            family = font.Family
            style = font.Style if hasattr(font, "Style") else ""
        except Exception:
            continue

        # Determine if italic from style string
        is_italic = bool(re.search(r"(?i)italic|oblique", style))

        # Parse weight from style
        weight_kw, weight_num = _parse_weight(style)

        entry = FontEntry(
            ps_name=ps_name,
            family=family,
            weight_kw=weight_kw,
            weight_num=weight_num,
            is_italic=is_italic,
            style=style,
        )
        index.setdefault(family, []).append(entry)

    return index


def resolve_font(
    font_index: dict[str, list[FontEntry]],
    target_family: str,
    target_weight_kw: str,
    preserve_italic: bool = False,
    original_ps_name: str = "",
) -> str | None:
    candidates = font_index.get(target_family)
    if not candidates:
        # Try case-insensitive search
        for fam, entries in font_index.items():
            if fam.lower() == target_family.lower():
                candidates = entries
                break
    if not candidates:
        # Try whitespace-normalized search (e.g. "NotoSans" → "Noto Sans")
        target_normalized = target_family.replace(" ", "").lower()
        for fam, entries in font_index.items():
            if fam.replace(" ", "").lower() == target_normalized:
                candidates = entries
                break
    if not candidates:
        return None

    # Determine if original was italic
    orig_italic = bool(re.search(r"(?i)italic|oblique", original_ps_name))
    target_italic = orig_italic if preserve_italic else False

    # Filter by italic preference
    filtered = [e for e in candidates if e.is_italic == target_italic]
    if not filtered:
        filtered = candidates  # fall back to all

    # Get target weight numeric value
    target_num = 400
    for kw, num in _WEIGHT_SORTED:
        if kw.lower() == target_weight_kw.lower():
            target_num = num
            break

    # Exact keyword match first
    for e in filtered:
        if e.weight_kw.lower() == target_weight_kw.lower():
            return e.ps_name

    # Nearest by numeric distance
    best = min(filtered, key=lambda e: abs(e.weight_num - target_num))
    return best.ps_name


def list_family_weights(font_index: dict[str, list[FontEntry]], family: str) -> list[FontEntry]:
    candidates = font_index.get(family, [])
    if not candidates:
        for fam, entries in font_index.items():
            if fam.lower() == family.lower():
                candidates = entries
                break
    return sorted(candidates, key=lambda e: e.weight_num)
