"""
Smart Object recursive processing.

Handles SO layer discovery, grouping by composite key, and recursive
entry/modification for nested Smart Objects up to 3 levels deep.
"""
from __future__ import annotations
from psa_models import TextLayerRecord
from psa_utils import (
    safe_get, enter_smart_object, find_layer_by_path, find_layer_by_id,
    get_so_psb_name, SOEnterError,
)
from psa_lab import LabDocument


def _find_so_by_psb(app, container, target_psb: str):
    """Find a Smart Object layer by its PSB fileReference in a container."""
    try:
        layers = container.Layers
    except Exception:
        return None
    for i in range(layers.Count):
        try:
            lyr = layers[i]
        except Exception:
            continue
        kind = safe_get(lyr, "Kind", None)
        if kind == 17:
            psb = get_so_psb_name(app, lyr)
            if psb == target_psb:
                return lyr
        result = _find_so_by_psb(app, lyr, target_psb)
        if result is not None:
            return result
    return None


def outermost_key(record: TextLayerRecord) -> str:
    """Composite group key: fileReference + layer_path."""
    if record.so_chain:
        entry = record.so_chain[0]
        psb = entry.get("psb_name", "unknown")
        lpath = entry.get("layer_path", "unknown")
        return f"{psb}@|@{lpath}"
    psb = record.so_psb_name or "unknown"
    lpath = record.so_layer_path or "unknown"
    return f"{psb}@|@{lpath}"


def find_outermost_so(app, container, key: str, group: list[TextLayerRecord], logger):
    """Find outermost SO layer using layer_path then psb_name then id."""
    first = group[0]
    if first.so_chain:
        entry = first.so_chain[0]
        if entry.get("layer_path"):
            so_layer = find_layer_by_path(container, entry["layer_path"].split("/"))
            if so_layer is not None:
                return so_layer
        if entry.get("layer_id") is not None:
            so_layer = find_layer_by_id(container, entry["layer_id"])
            if so_layer is not None:
                return so_layer
        psb_name = entry.get("psb_name", "")
    else:
        if first.so_layer_path:
            so_layer = find_layer_by_path(container, first.so_layer_path.split("/"))
            if so_layer is not None:
                return so_layer
        if first.so_layer_id is not None:
            so_layer = find_layer_by_id(container, first.so_layer_id)
            if so_layer is not None:
                return so_layer
        psb_name = first.so_psb_name or ""

    if psb_name:
        so_layer = _find_so_by_psb(app, container, psb_name)
        if so_layer is not None:
            return so_layer
    return None


def process_so_level(app, doc, records: list[TextLayerRecord], logger, dpi: float, depth: int,
                     _process_layer_func):
    """Recursively process records inside an SO document.

    At each depth level, records whose so_chain length matches the depth
    are processed directly. Records with deeper chains are grouped by the
    next SO in the chain and processed via recursive entry.
    """
    direct_here: list[TextLayerRecord] = []
    nested: dict[str, list[TextLayerRecord]] = {}

    for r in records:
        chain_len = len(r.so_chain)
        if chain_len <= depth or depth >= 3:
            direct_here.append(r)
        else:
            next_entry = r.so_chain[depth]
            psb = next_entry.get("psb_name", "unknown")
            lpath = next_entry.get("layer_path", "unknown")
            nkey = f"{psb}@|@{lpath}"
            nested.setdefault(nkey, []).append(r)

    if direct_here:
        with LabDocument(app, dpi) as lab:
            for r in direct_here:
                _process_layer_func(app, doc, r, lab, logger, in_so=True)

    for nkey, ngroup in nested.items():
        entry = ngroup[0].so_chain[depth]
        so_layer = None
        if entry.get("layer_path"):
            so_layer = find_layer_by_path(doc, entry["layer_path"].split("/"))
        if so_layer is None and entry.get("layer_id") is not None:
            so_layer = find_layer_by_id(doc, entry["layer_id"])
        if so_layer is None:
            psb_name = entry.get("psb_name", "")
            if psb_name:
                so_layer = _find_so_by_psb(app, doc, psb_name)

        if so_layer is None:
            logger.log_error(f"nested SO '{nkey}' at depth {depth}",
                             SOEnterError("SO layer not found"))
            continue

        try:
            app.ActiveDocument = doc
            inner_doc = enter_smart_object(app, so_layer)
        except SOEnterError as e:
            logger.log_error(f"enter nested SO '{nkey}'", e)
            continue

        try:
            inner_dpi = float(safe_get(inner_doc, "Resolution", dpi))
            process_so_level(app, inner_doc, ngroup, logger, inner_dpi, depth + 1,
                             _process_layer_func)
            try:
                inner_doc.Save()
                inner_doc.Close(1)
            except Exception as e:
                logger.log_error(f"save/close nested SO '{nkey}'", e)
        except Exception as e:
            logger.log_error(f"process nested SO '{nkey}'", e)
            try:
                inner_doc.Close(2)
            except Exception:
                pass
