"""
PSA → MediaTools Adapter
========================
Drop-in replacement for MediaTools' text modification engine using PSA's
superior adaptive algorithm.

Public API:
    psa_scan(ps, psd_path=None, psd_dir=None, output_dir=None) -> list[TextLayerRecord]
    psa_apply(ps, psd_path, workorder_path, output_dir=None) -> dict
    psa_run(ps, psd_path=None, psd_dir=None, workorder_path=None, output_dir=None) -> dict
    psa_verify_font(ps, psd_path, font_from, font_to, output_dir=None) -> list[dict]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure PSA modules are importable
_self_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_self_dir)
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)

from psa_models import TextLayerRecord
from psa_utils import get_active_doc, safe_get, PSAError
from psa_logger import PSALogger
from psa_fonts import build_font_index, resolve_font
from psa_applier import apply_workorder
from psa_scanner import scan_document

from psa_mediatools_adapter._bridge import (
    ModifyResult,
    extract_app,
    connector_guard,
    make_result,
)


def _make_log_path(base_name: str, output_dir: str) -> str:
    import datetime
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(output_dir, f"{base_name}_{ts}.log")


# ═══════════════════════════════════════════════════════════════════════
# psa_scan
# ═══════════════════════════════════════════════════════════════════════

def psa_scan(
    ps,
    psd_path: str | None = None,
    psd_dir: str | None = None,
    output_dir: str | None = None,
) -> list[TextLayerRecord]:
    """Scan PSD file(s) for text layers and return records.

    Args:
        ps: PhotoshopConnector instance (or raw COM app).
        psd_path: Single PSD file path. If None, uses current active document.
        psd_dir: Directory of PSD files. If set, psd_path is ignored.
        output_dir: Directory for the JSON work order. Defaults to PSD directory.

    Returns:
        List of TextLayerRecord (also saved as JSON to output_dir).
    """
    app = extract_app(ps)

    if psd_dir:
        return _scan_directory(app, psd_dir, output_dir)

    if psd_path:
        return _scan_single_file(app, psd_path, output_dir)

    # Default: scan current active document
    return _scan_active_document(app, output_dir)


def _scan_single_file(app, psd_path: str, output_dir: str | None) -> list[TextLayerRecord]:
    psd_path = os.path.abspath(psd_path)
    if output_dir is None:
        output_dir = os.path.dirname(psd_path)

    log_path = _make_log_path(Path(psd_path).stem, output_dir)
    logger = PSALogger(log_path)
    logger.log_info(f"SCAN: opening {psd_path}")

    doc = None
    opened = False
    try:
        # Check if already open
        doc = _find_open_doc(app, psd_path)
        if doc is None:
            doc = app.Open(psd_path)
            opened = True

        records = _do_scan(app, doc, logger, output_dir, psd_path)
    finally:
        if opened and doc is not None:
            try:
                doc.Close(2)
            except Exception:
                pass

    return records


def _scan_active_document(app, output_dir: str | None) -> list[TextLayerRecord]:
    doc = get_active_doc(app)
    psd_path = safe_get(doc, "FullName", "")
    if output_dir is None:
        output_dir = os.path.dirname(psd_path) if psd_path else "."

    doc_name = safe_get(doc, "Name", "active_document")
    log_path = _make_log_path(os.path.splitext(doc_name)[0], output_dir)
    logger = PSALogger(log_path)
    return _do_scan(app, doc, logger, output_dir, psd_path or "active_document")


def _scan_directory(app, psd_dir: str, output_dir: str | None) -> list[TextLayerRecord]:
    psd_dir = os.path.abspath(psd_dir)
    if output_dir is None:
        output_dir = psd_dir

    all_records: list[TextLayerRecord] = []
    psd_files = list(Path(psd_dir).glob("*.psd")) + list(Path(psd_dir).glob("*.PSD"))
    if not psd_files:
        raise PSAError(f"No PSD files found in {psd_dir}")

    for psd_file in psd_files:
        psd_path = str(psd_file)
        log_path = _make_log_path(psd_file.stem, output_dir)
        logger = PSALogger(log_path)
        doc = None
        opened = False
        try:
            doc = _find_open_doc(app, psd_path)
            if doc is None:
                doc = app.Open(psd_path)
                opened = True
            records = _do_scan(app, doc, logger, output_dir, psd_path)
            all_records.extend(records)
        finally:
            if opened and doc is not None:
                try:
                    doc.Close(2)
                except Exception:
                    pass

    # Write combined work order
    workorder_path = os.path.join(output_dir, "batch_workorder.json")
    _write_workorder(all_records, workorder_path, logger)
    return all_records


def _do_scan(app, doc, logger, output_dir: str, source_path: str) -> list[TextLayerRecord]:
    with connector_guard(app):
        records = scan_document(app, doc, logger)

    stem = Path(source_path).stem
    workorder_path = os.path.join(output_dir, f"{stem}_workorder.json")
    _write_workorder(records, workorder_path, logger)
    return records


def _write_workorder(records: list[TextLayerRecord], path: str, logger) -> None:
    data = [r.to_dict() for r in records]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.log_info(f"Work order written: {path}")


def _find_open_doc(app, psd_path: str):
    import os as _os
    norm_target = _os.path.normcase(_os.path.abspath(psd_path))
    for i in range(app.Documents.Count):
        try:
            d = app.Documents[i]
            if _os.path.normcase(safe_get(d, "FullName", "")) == norm_target:
                return d
        except Exception:
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════
# psa_apply
# ═══════════════════════════════════════════════════════════════════════

def psa_apply(
    ps,
    psd_path: str,
    workorder_path: str,
    output_dir: str | None = None,
) -> dict:
    """Apply a JSON work order to a PSD file using PSA's adaptive algorithm.

    Automatically skips layers where both text and font are unchanged.

    Args:
        ps: PhotoshopConnector instance (or raw COM app).
        psd_path: Source PSD file path.
        workorder_path: JSON work order file path.
        output_dir: Directory for outputs. Defaults to PSD directory.

    Returns:
        dict with keys: source_psd, auto_psd, log_file, results, summary.
    """
    app = extract_app(ps)
    psd_path = os.path.abspath(psd_path)
    workorder_path = os.path.abspath(workorder_path)

    if output_dir is None:
        output_dir = os.path.dirname(psd_path)
    os.makedirs(output_dir, exist_ok=True)

    log_path = _make_log_path(Path(psd_path).stem, output_dir)
    logger = PSALogger(log_path)

    # Load work order
    with open(workorder_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    all_records = [TextLayerRecord.from_dict(d) for d in raw]

    # Enable records that have changes; skip unchanged automatically
    enabled_count = 0
    skipped_count = 0
    for r in all_records:
        has_text_change = r.new_text is not None and r.new_text != r.text
        has_font_change = r.new_font_family is not None and r.new_font_family.strip() != ""
        if has_text_change or has_font_change:
            r.enabled = True
            enabled_count += 1
        else:
            r.enabled = False
            skipped_count += 1

    logger.log_info(
        f"Work order loaded: {len(all_records)} layers, "
        f"{enabled_count} enabled, {skipped_count} skipped (unchanged)"
    )

    if enabled_count == 0:
        logger.log_info("No layers with changes to apply.")
        return {
            "source_psd": psd_path,
            "auto_psd": "",
            "log_file": logger.log_path,
            "results": [
                make_result(r, skipped=True, message="unchanged").__dict__
                for r in all_records
            ],
            "summary": {
                "total": len(all_records),
                "processed": 0,
                "skipped": skipped_count,
                "converged": 0,
                "errors": 0,
            },
        }

    # Run PSA apply
    with connector_guard(app):
        auto_path = apply_workorder(app, psd_path, all_records, logger)

    # Build results
    results = []
    for r in all_records:
        if not r.enabled:
            results.append(make_result(r, skipped=True, message="unchanged").__dict__)
        else:
            # Get adapted params from the record
            from psa_models import AdaptedParams
            params = AdaptedParams(
                font_ps=r.new_font_ps or r.font,
                size_pt=r.size_pt,
                size_px=r.size_px,
                auto_leading=r.auto_leading,
                leading_pt=r.leading_pt,
                leading_px=r.leading_px,
                tracking=r.tracking,
                final_bounds_h_px=r.bounds_h_px,
                target_h_px=r.bounds_h_px,
                converged=True,
                iterations_log=[],
            )
            results.append(make_result(r, params, message="applied").__dict__)

    processed = enabled_count
    errors = sum(1 for r in results if not r.get("converged", False) and not r.get("skipped", False))

    return {
        "source_psd": psd_path,
        "auto_psd": auto_path,
        "log_file": logger.log_path,
        "results": results,
        "summary": {
            "total": len(all_records),
            "processed": processed,
            "skipped": skipped_count,
            "converged": processed - errors,
            "errors": errors,
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# psa_run
# ═══════════════════════════════════════════════════════════════════════

def psa_run(
    ps,
    psd_path: str | None = None,
    psd_dir: str | None = None,
    workorder_path: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Scan + Apply in one step.

    If workorder_path is provided, skip scan and use existing work order.
    Otherwise scan first, then apply immediately.

    Args:
        ps: PhotoshopConnector instance (or raw COM app).
        psd_path: Single PSD file path.
        psd_dir: Directory of PSD files (batch mode).
        workorder_path: Existing work order JSON (skip scan).
        output_dir: Output directory.

    Returns:
        Same dict as psa_apply.
    """
    if workorder_path:
        target_psd = psd_path or _resolve_psd_from_workorder(workorder_path)
        if not target_psd:
            raise PSAError("psd_path is required when using an existing workorder")
        return psa_apply(ps, target_psd, workorder_path, output_dir)

    if psd_dir:
        # Batch: scan all, then apply each
        records = psa_scan(ps, psd_dir=psd_dir, output_dir=output_dir)
        all_results = []
        # Group records by source_psd
        from collections import defaultdict
        grouped: dict[str, list] = defaultdict(list)
        for r in records:
            grouped[r.layer_path.split("/")[0]].append(r)  # simplified grouping

        for psd_file in Path(psd_dir).glob("*.psd"):
            psd_path_str = str(psd_file)
            wo_path = os.path.join(output_dir or psd_dir, f"{psd_file.stem}_workorder.json")
            if os.path.exists(wo_path):
                result = psa_apply(ps, psd_path_str, wo_path, output_dir)
                all_results.append(result)
        return {
            "batch": True,
            "output_dir": output_dir or psd_dir,
            "files": all_results,
        }

    # Single file: scan then apply
    if psd_path is None:
        app = extract_app(ps)
        doc = get_active_doc(app)
        psd_path = safe_get(doc, "FullName", "")
    if output_dir is None:
        output_dir = os.path.dirname(psd_path) if psd_path else "."

    records = psa_scan(ps, psd_path=psd_path, output_dir=output_dir)
    stem = Path(psd_path).stem
    wo_path = os.path.join(output_dir, f"{stem}_workorder.json")
    return psa_apply(ps, psd_path, wo_path, output_dir)


def _resolve_psd_from_workorder(workorder_path: str) -> str:
    """Best-effort: infer source PSD path from work order file location."""
    wo_dir = os.path.dirname(os.path.abspath(workorder_path))
    wo_name = os.path.basename(workorder_path)
    # Try stripping _workorder suffix
    stem = wo_name.replace("_workorder.json", "").replace("_scan.json", "")
    candidate = os.path.join(wo_dir, f"{stem}.psd")
    if os.path.exists(candidate):
        return candidate
    return ""


# ═══════════════════════════════════════════════════════════════════════
# psa_verify_font
# ═══════════════════════════════════════════════════════════════════════

def psa_verify_font(
    ps,
    psd_path: str,
    font_from: str,
    font_to: str,
    output_dir: str | None = None,
) -> list[dict]:
    """Verify font conversion: scan a PSD, find layers using font_from,
    predict what font_to weight PSA's algorithm would resolve to.

    Args:
        ps: PhotoshopConnector instance (or raw COM app).
        psd_path: Source PSD file.
        font_from: Source font family (e.g. "Byte Sans").
        font_to: Target font family (e.g. "Noto Sans").
        output_dir: Output directory for cache CSV.

    Returns:
        List of {original_font, target_font, layer_count} dicts.
    """
    app = extract_app(ps)
    psd_path = os.path.abspath(psd_path)
    if output_dir is None:
        output_dir = os.path.dirname(psd_path)

    log_path = _make_log_path(Path(psd_path).stem, output_dir)
    logger = PSALogger(log_path)
    font_index = build_font_index(app)

    records = psa_scan(ps, psd_path=psd_path, output_dir=output_dir)

    # Collect unique original fonts that match font_from
    from collections import Counter
    font_counter = Counter()
    for r in records:
        font_counter[r.font] += 1

    results = []
    for orig_font, count in sorted(font_counter.items()):
        result = resolve_font(
            font_index=font_index,
            target_family=font_to,
            target_weight_kw="",  # Let algorithm find closest
            preserve_italic=False,
            original_ps_name=orig_font,
        )
        results.append({
            "original_font": orig_font,
            "target_font": result or "NOT FOUND",
            "layer_count": count,
            "verified": result is not None,
        })

    # Write cache CSV (compatible format)
    if output_dir:
        import csv
        cache_path = os.path.join(output_dir, f"font_cache_{font_to}.csv")
        with open(cache_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["original_font", "target_font", "layer_count"])
            for r in results:
                writer.writerow([r["original_font"], r["target_font"], r["layer_count"]])
        logger.log_info(f"Font cache written: {cache_path}")

    return results
