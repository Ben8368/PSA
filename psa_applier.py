from __future__ import annotations
import os

from psa_models import TextLayerRecord, AdaptedParams
from psa_utils import (
    PixelUnitsContext,
    safe_get,
    enter_smart_object,
    find_layer_by_id,
    find_layer_by_path,
    expand_so_canvas,
    pt_to_px,
    layer_bounds_px,
    PSAError,
    SOEnterError,
    LayerNotFoundError,
    FontNotFoundError,
)
from psa_fonts import build_font_index, resolve_font
from psa_lab import LabDocument
from psa_so_handler import (
    _find_so_by_psb, outermost_key, find_outermost_so, process_so_level,
)


def apply_workorder(
    app,
    source_psd_path: str,
    records: list[TextLayerRecord],
    logger,
) -> str:
    to_process = [r for r in records if r.enabled]

    # Skip single English letters (decorative, not meaningful text)
    skipped_decorative = 0
    filtered = []
    for r in to_process:
        stripped = (r.text or "").strip()
        if len(stripped) == 1 and stripped.isascii() and stripped.isalpha():
            logger.log_info(
                f"SKIP decorative single English char '{stripped}' "
                f"at '{r.layer_path}'"
            )
            skipped_decorative += 1
            continue
        filtered.append(r)
    to_process = filtered
    if skipped_decorative:
        logger.log_info(f"Skipped {skipped_decorative} decorative single-English-char layer(s)")

    if not to_process:
        logger.log_info("No enabled layers to process (after filtering).")
        return ""

    logger.log_info("Building font index...")
    font_index = build_font_index(app)
    logger.log_info(f"Font index built: {len(font_index)} families")

    for record in to_process:
        record.new_font_ps = _resolve_font_for_record(record, font_index, logger)

    auto_path = _make_auto_path(source_psd_path)
    logger.log_info(f"Creating auto copy: {auto_path}")
    _create_auto_copy(app, source_psd_path, auto_path, logger)

    try:
        auto_doc = app.Open(auto_path)
    except Exception as e:
        raise PSAError(f"Failed to open auto copy '{auto_path}': {e}")

    try:
        auto_dpi = float(safe_get(auto_doc, "Resolution", 72.0))

        direct_records = [r for r in to_process if not r.in_smart_object]
        so_records = [r for r in to_process if r.in_smart_object]

        # Direct layers
        if direct_records:
            app.ActiveDocument = auto_doc
            with LabDocument(app, auto_dpi) as lab:
                for record in direct_records:
                    _process_layer(app, auto_doc, record, lab, logger)

        # SO layers — group by outermost SO and process recursively
        if so_records:
            outermost: dict[str, list[TextLayerRecord]] = {}
            for r in so_records:
                key = outermost_key(r)
                outermost.setdefault(key, []).append(r)

            for key, group in outermost.items():
                so_layer = find_outermost_so(app, auto_doc, key, group, logger)
                if so_layer is None:
                    logger.log_error(f"SO '{key}'", SOEnterError("SO layer not found in auto doc"))
                    continue

                try:
                    app.ActiveDocument = auto_doc
                    so_doc = enter_smart_object(app, so_layer)
                except SOEnterError as e:
                    logger.log_error(f"enter SO '{key}'", e)
                    continue

                try:
                    so_dpi = float(safe_get(so_doc, "Resolution", auto_dpi))
                    process_so_level(app, so_doc, group, logger, so_dpi, depth=1,
                                     _process_layer_func=_process_layer)
                    try:
                        so_doc.Save()
                        so_doc.Close(1)
                    except Exception as e:
                        logger.log_error(f"save/close SO '{key}'", e)
                except Exception as e:
                    logger.log_error(f"process SO group '{key}'", e)
                    try:
                        so_doc.Close(2)
                    except Exception:
                        pass

        try:
            app.ActiveDocument = auto_doc
            auto_doc.Save()
            auto_doc.Close(1)
        except Exception as e:
            logger.log_error("save/close auto doc", e)

    except Exception as e:
        logger.log_error("apply_workorder", e)
        try:
            auto_doc.Close(2)
        except Exception:
            pass
        raise

    logger.log_info(f"Done. Auto document saved: {auto_path}")
    return auto_path


def _process_layer(app, doc, record: TextLayerRecord, lab: LabDocument, logger, in_so: bool = False):
    """Handle one layer: find it, calibrate scale via lab, run adaptive, apply, verify+refine."""
    try:
        if in_so:
            parts = record.layer_path.split("/")
            layer = find_layer_by_path(doc, parts)
            if layer is None:
                layer = find_layer_by_id(doc, record.layer_id)
        else:
            layer = find_layer_by_id(doc, record.layer_id)

        if layer is None:
            raise LayerNotFoundError(
                f"Layer id={record.layer_id} path='{record.layer_path}' not found"
            )

        logger.log_layer_before(record)
        new_font_ps = record.new_font_ps or record.font
        new_text = record.new_text if record.new_text is not None else record.text
        logger.log_apply_start(record.layer_path, record.bounds_h_px, new_font_ps)

        # ===== Method A: calibrate scale using original text in lab =====
        scale = 1.0
        try:
            lab_orig_h = lab.measure_text(
                font_ps=record.font,
                contents=record.text,
                size_pt=record.size_pt,
                tracking=record.tracking,
                auto_leading=record.auto_leading,
                leading_pt=record.leading_pt,
            )
            if lab_orig_h > 0.5:
                scale = record.bounds_h_px / lab_orig_h
            logger.log_info(
                f"CALIBRATE [{record.layer_path}]: real_h={record.bounds_h_px:.2f}px "
                f"lab_h={lab_orig_h:.2f}px scale={scale:.4f}"
            )
        except Exception as e:
            logger.log_error(f"calibrate scale for '{record.layer_path}'", e)
            scale = 1.0

        target_h_lab = record.bounds_h_px / scale if scale > 0 else record.bounds_h_px

        # Restore doc+layer as active (lab switched it)
        app.ActiveDocument = doc
        doc.ActiveLayer = layer

        # Run adaptive algorithm with corrected target
        params = lab.find_adapted_params(
            record, new_font_ps, new_text, logger,
            target_h_override=target_h_lab,
        )

        # Apply to real layer
        app.ActiveDocument = doc
        doc.ActiveLayer = layer
        _apply_to_text_layer(app, doc, layer, params, record, logger)

        # ===== Boundary protection for Smart Objects =====
        if in_so:
            try:
                size_ratio = params.size_pt / max(record.size_pt, 0.1)
                expansion = max(1.2, size_ratio * 1.1)
                expansion = min(expansion, 3.0)
                expand_so_canvas(app, doc, expansion)
                pct = int((expansion - 1.0) * 100)
                logger.log_info(
                    f"BOUNDARY PROTECT [{record.layer_path}]: Expanded SO canvas by {pct}% "
                    f"(scale={expansion:.3f}, size_ratio={size_ratio:.3f})"
                )
            except Exception as e:
                logger.log_warning(f"BOUNDARY PROTECT [{record.layer_path}]: {str(e)}")

        # ===== Method B: verify real rendered height, refine if needed =====
        try:
            real_h = _real_bounds_h(app, layer)
            logger.log_info(
                f"VERIFY [{record.layer_path}]: real_h={real_h:.2f}px target={record.bounds_h_px:.2f}px "
                f"diff={real_h - record.bounds_h_px:+.2f}px"
            )

            max_refine = 5 if record.faux_bold else 3
            refine_converge_px = 4.0 if record.faux_bold else 2.0
            _refine_safety = False
            for refine_iter in range(1, max_refine + 1):
                diff = real_h - record.bounds_h_px
                if abs(diff) < refine_converge_px:
                    if _refine_safety:
                        break
                    _refine_safety = True
                ratio = record.bounds_h_px / real_h if real_h > 0.5 else 1.0
                new_size_pt = params.size_pt * ratio
                try:
                    app.ActiveDocument = doc
                    doc.ActiveLayer = layer
                    ti = layer.TextItem
                    ti.Size = new_size_pt
                    if not params.auto_leading:
                        new_leading = params.leading_pt * ratio
                        ti.Leading = new_leading
                        params.leading_pt = new_leading
                        params.leading_px = pt_to_px(new_leading, record.dpi)
                    params.size_pt = new_size_pt
                    params.size_px = pt_to_px(new_size_pt, record.dpi)
                except Exception as e:
                    logger.log_error(f"refine iter {refine_iter} '{record.layer_path}'", e)
                    break
                real_h = _real_bounds_h(app, layer)
                logger.log_info(
                    f"REFINE {refine_iter} [{record.layer_path}]: size={new_size_pt:.4f}pt "
                    f"real_h={real_h:.2f}px target={record.bounds_h_px:.2f}px"
                )

            params.final_bounds_h_px = real_h
            params.target_h_px = record.bounds_h_px
            final_conv_px = 6.0 if record.faux_bold else 3.0
            params.converged = abs(real_h - record.bounds_h_px) < final_conv_px
        except Exception as e:
            logger.log_error(f"verify '{record.layer_path}'", e)

        logger.log_apply_result(record.layer_path, params, record)
        logger.log_layer_after(record, params)
    except Exception as e:
        logger.log_error(f"apply layer '{record.layer_path}'", e)


def _real_bounds_h(app, art_layer) -> float:
    bounds = layer_bounds_px(app, art_layer)
    return float(bounds[3]) - float(bounds[1])


def _apply_to_text_layer(app, doc, art_layer, params: AdaptedParams, record: TextLayerRecord, logger) -> None:
    try:
        app.ActiveDocument = doc
        doc.ActiveLayer = art_layer
    except Exception:
        pass
    ti = art_layer.TextItem
    try:
        ti.Font = params.font_ps
    except Exception as e:
        logger.log_error(f"set Font on '{record.layer_path}'", e)
    try:
        ti.Size = params.size_pt
    except Exception as e:
        logger.log_error(f"set Size on '{record.layer_path}'", e)
    try:
        ti.UseAutoLeading = params.auto_leading
    except Exception as e:
        logger.log_error(f"set UseAutoLeading on '{record.layer_path}'", e)
    if not params.auto_leading:
        try:
            ti.Leading = params.leading_pt
        except Exception as e:
            logger.log_error(f"set Leading on '{record.layer_path}'", e)
    try:
        ti.Tracking = params.tracking
    except Exception as e:
        logger.log_error(f"set Tracking on '{record.layer_path}'", e)
    new_text = record.new_text if record.new_text is not None else record.text
    try:
        ti.Contents = new_text
    except Exception as e:
        logger.log_error(f"set Contents on '{record.layer_path}'", e)


def _resolve_font_for_record(record: TextLayerRecord, font_index: dict, logger) -> str:
    if not record.new_font_family or not record.new_font_family.strip():
        return record.font
    target_weight = (record.new_font_weight or "").strip()
    ps_name = resolve_font(
        font_index=font_index,
        target_family=record.new_font_family,
        target_weight_kw=target_weight,
        preserve_italic=False,
        original_ps_name=record.font,
    )
    if ps_name is None:
        logger.log_warning(
            f"Font family '{record.new_font_family}' not found. "
            f"Falling back to original font '{record.font}'."
        )
        return record.font
    logger.log_info(
        f"Font resolved: family='{record.new_font_family}' weight='{record.new_font_weight}' "
        f"-> PS name='{ps_name}'"
    )
    return ps_name


def _make_auto_path(source_psd_path: str) -> str:
    base, ext = os.path.splitext(source_psd_path)
    return base + "_auto" + ext


def _create_auto_copy(app, source_path: str, auto_path: str, logger) -> None:
    source_doc = None
    try:
        for i in range(app.Documents.Count):
            try:
                doc = app.Documents[i]
                if os.path.normcase(safe_get(doc, "FullName", "")) == os.path.normcase(source_path):
                    source_doc = doc
                    break
            except Exception:
                continue
    except Exception:
        pass

    opened_here = False
    if source_doc is None:
        try:
            source_doc = app.Open(source_path)
            opened_here = True
        except Exception as e:
            raise PSAError(f"Failed to open source PSD '{source_path}': {e}")

    try:
        source_doc.SaveAs(auto_path, None, True)
        logger.log_copy_created(source_path, auto_path)
    except Exception as e:
        raise PSAError(f"Failed to create auto copy '{auto_path}': {e}")
    finally:
        if opened_here and source_doc is not None:
            try:
                source_doc.Close(2)
            except Exception:
                pass
