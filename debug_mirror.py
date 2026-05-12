"""
Debug script: generate a corrected workorder with
  1) per-line mirror (each line independently reversed)
  2) spaces preserved as spaces (not hyphens)
  3) new_font_family set to "Bytes" family, weight matched from original

Run: python debug_mirror.py
Outputs: test_debug_workorder.json  (ready for `python psa.py apply`)
Also prints a side-by-side diff of old vs new new_text for review.
"""

import json
import re

SRC = "test_workorder.json"
DST = "test_debug_workorder.json"

# Bytes family name as it appears in Photoshop font list.
# Covers: ByteSans, ByteDance Sans, Bytes, etc.
# We'll use "Bytes" as the key — psa_fonts resolve_font does case-insensitive lookup.
# The actual family string must match what PS reports; adjust if needed.
BYTES_FAMILY = "Byte Sans"

# Available weights in "Byte Sans": Bold / Light / Medium / Regular / SemiLight
# Map source weight → nearest available Byte Sans weight keyword
def _weight_from_ps_name(ps_name: str) -> str:
    """Map source PS font weight to the nearest available Byte Sans weight."""
    name = ps_name.replace("-", "").replace(" ", "")
    # Ordered longest-first to avoid "Bold" matching inside "SemiBold"
    source_weights = [
        ("ExtraBold", "Bold"),
        ("UltraBold", "Bold"),
        ("SemiBold",  "Bold"),      # no SemiBold in Byte Sans → Bold
        ("DemiBold",  "Bold"),
        ("Bold",      "Bold"),
        ("SemiLight", "SemiLight"),
        ("DemiLight", "Light"),
        ("Medium",    "Medium"),
        ("Light",     "Light"),
        ("Thin",      "Light"),     # no Thin → Light
        ("Black",     "Bold"),      # no Black → Bold
        ("Heavy",     "Bold"),
        ("Regular",   "Regular"),
        ("Normal",    "Regular"),
    ]
    for kw, mapped in source_weights:
        if re.search(kw, name, re.IGNORECASE):
            return mapped
    return "Regular"


def mirror_line(line: str) -> str:
    """Reverse a single line of text."""
    return line[::-1]


def mirror_text(text: str) -> str:
    """Mirror each line independently, preserving line structure."""
    # PSD uses \r as line separator
    lines = text.split("\r")
    return "\r".join(mirror_line(line) for line in lines)


def main():
    with open(SRC, encoding="utf-8") as f:
        records = json.load(f)

    issues = []
    for r in records:
        orig_text = r.get("text", "")
        old_new_text = r.get("new_text", "")
        correct_new_text = mirror_text(orig_text)

        # Check if old mirror was wrong
        if old_new_text != correct_new_text:
            issues.append({
                "layer": r["layer_path"],
                "original": orig_text,
                "old_mirror": old_new_text,
                "correct_mirror": correct_new_text,
            })

        # Apply corrections
        r["new_text"] = correct_new_text
        r["new_font_family"] = BYTES_FAMILY
        r["new_font_weight"] = _weight_from_ps_name(r.get("font", ""))

    with open(DST, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Written: {DST}\n")
    print("=" * 70)
    print("MIRROR ISSUES FOUND (old workorder had wrong reversals):")
    print("=" * 70)

    if not issues:
        print("  None — all mirrors were already correct.")
    else:
        for item in issues:
            print(f"\nLayer: {item['layer']}")
            orig_lines = item['original'].split('\r')
            old_lines  = item['old_mirror'].split('\r')
            new_lines  = item['correct_mirror'].split('\r')
            for i, orig in enumerate(orig_lines):
                old = old_lines[i] if i < len(old_lines) else "<missing>"
                new = new_lines[i] if i < len(new_lines) else "<missing>"
                match = "OK" if old == new else "FIX"
                print(f"  [{match}] orig='{orig}'  old='{old}'  correct='{new}'")

    print("\n" + "=" * 70)
    print("FONT ASSIGNMENTS:")
    print("=" * 70)
    for r in records:
        print(f"  {r['layer_path'][:55]:<55}  {r['font']:<30} -> {r['new_font_family']} / {r['new_font_weight']}")


if __name__ == "__main__":
    main()
