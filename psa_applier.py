from __future__ import annotations
import os

from psa_models import TextLayerRecord, AdaptedParams
from psa_utils import (
    PixelUnitsContext,
    safe_get,
    enter_smart_object,
    find_layer_by_id,
    find_layer_by_path,
    get_so_psb_name,
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


def apply_workorder(
    app,
    source_psd_path: str,
    records: list[TextLayerRecord],
    logger,
) -> str:
    to_process = [r for r in records if r.enabled]
    if not to_process:
        logger.log_info("No enabled layers to process.")
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

        so_groups: dict[str, list[TextLayerRecord]] = {}
        for r in so_records:
            key = r.so_psb_name or r.so_layer_path or "unknown"
            so_groups.setdefault(key, []).append(r)

        # Direct layers
        if direct_records:
            app.ActiveDocument = auto_doc
            with LabDocument(app, auto_dpi) as lab:
                for record in direct_records:
                    _process_layer(app, auto_doc, record, lab, logger)

        # SO layers
        for psb_name, group in so_groups.items():
            so_layer = _find_so_by_psb(app, auto_doc, psb_name)
            if so_layer is None:
                for record in group:
                    if record.so_layer_path:
                        so_layer = find_layer_by_path(auto_doc, record.so_layer_path.split("/"))
                    if so_layer is None and record.so_layer_id is not None:
                        so_layer = find_layer_by_id(auto_doc, record.so_layer_id)
                    if so_layer is not None:
                        break

            if so_layer is None:
                logger.log_error(f"SO layer for PSB '{psb_name}'",
                                 SOEnterError("SO layer not found in auto doc"))
                continue

            try:
                app.ActiveDocument = auto_doc
                so_doc = enter_smart_object(app, so_layer)
            except SOEnterError as e:
                logger.log_error(f"enter SO '{psb_name}'", e)
                continue

            try:
                so_dpi = float(safe_get(so_doc, "Resolution", auto_dpi))
                with LabDocument(app, so_dpi) as lab:
                    for record in group:
                        _process_layer(app, so_doc, record, lab, logger, in_so=True)

                try:
                    so_doc.Save()
                    so_doc.Close(1)
                except Exception as e:
                    logger.log_error(f"save/close SO '{psb_name}'", e)

            except Exception as e:
                logger.log_error(f"process SO group '{psb_name}'", e)
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
                expand_so_canvas(app, doc)
                logger.log_info(f"BOUNDARY PROTECT [{record.layer_path}]: Expanded SO canvas by 20%")
            except Exception as e:
                logger.log_warning(f"BOUNDARY PROTECT [{record.layer_path}]: {str(e)}")

        # ===== Method B: verify real rendered height, refine if needed =====
        try:
            real_h = _real_bounds_h(app, layer)
            logger.log_info(
                f"VERIFY [{record.layer_path}]: real_h={real_h:.2f}px target={record.bounds_h_px:.2f}px "
                f"diff={real_h - record.bounds_h_px:+.2f}px"
            )

            for refine_iter in range(1, 6):  # up to 5 refinement rounds
                diff = real_h - record.bounds_h_px
                if abs(diff) < 2.0:
                    break
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
            params.converged = abs(real_h - record.bounds_h_px) < 3.0
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
    if not record.new_font_family or not record.new_font_weight:
        return record.font
    ps_name = resolve_font(
        font_index=font_index,
        target_family=record.new_font_family,
        target_weight_kw=record.new_font_weight,
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


def _find_so_by_psb(app, container, target_psb: str):
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
