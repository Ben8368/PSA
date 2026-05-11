from __future__ import annotations
import os
import win32com.client

from psa_models import TextLayerRecord, AdaptedParams
from psa_utils import (
    PixelUnitsContext,
    safe_get,
    enter_smart_object,
    find_layer_by_id,
    find_layer_by_path,
    pt_to_px,
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

    # Build font index
    logger.log_info("Building font index...")
    font_index = build_font_index(app)
    logger.log_info(f"Font index built: {len(font_index)} families")

    # Resolve font PS names
    for record in to_process:
        record.new_font_ps = _resolve_font_for_record(record, font_index, logger)

    # Create _auto copy
    auto_path = _make_auto_path(source_psd_path)
    logger.log_info(f"Creating auto copy: {auto_path}")
    _create_auto_copy(app, source_psd_path, auto_path, logger)

    # Open auto copy
    try:
        auto_doc = app.Open(auto_path)
    except Exception as e:
        raise PSAError(f"Failed to open auto copy '{auto_path}': {e}")

    try:
        auto_dpi = float(safe_get(auto_doc, "Resolution", 72.0))

        # Separate direct vs SO layers
        direct_records = [r for r in to_process if not r.in_smart_object]
        so_records = [r for r in to_process if r.in_smart_object]

        # Group SO records by PSB name
        so_groups: dict[str, list[TextLayerRecord]] = {}
        for r in so_records:
            key = r.so_psb_name or r.so_layer_path or "unknown"
            so_groups.setdefault(key, []).append(r)

        # Process direct layers using a reusable lab doc per DPI
        if direct_records:
            with LabDocument(app, auto_dpi) as lab:
                for record in direct_records:
                    logger.log_layer_before(record)
                    try:
                        layer = find_layer_by_id(auto_doc, record.layer_id)
                        if layer is None:
                            raise LayerNotFoundError(
                                f"Layer id={record.layer_id} path='{record.layer_path}' not found"
                            )
                        new_font_ps = record.new_font_ps or record.font
                        new_text = record.new_text if record.new_text is not None else record.text
                        logger.log_apply_start(record.layer_path, record.bounds_h_px, new_font_ps)
                        params = lab.find_adapted_params(record, new_font_ps, new_text, logger)
                        _apply_to_text_layer(layer, params, record, logger)
                        logger.log_apply_result(record.layer_path, params, record)
                        logger.log_layer_after(record, params)
                    except Exception as e:
                        logger.log_error(f"apply direct layer '{record.layer_path}'", e)

        # Process SO layers
        for psb_name, group in so_groups.items():
            # Find SO layer in auto_doc
            so_layer = None
            for record in group:
                if record.so_layer_id is not None:
                    so_layer = find_layer_by_id(auto_doc, record.so_layer_id)
                if so_layer is None and record.so_layer_path:
                    parts = record.so_layer_path.split("/")
                    so_layer = find_layer_by_path(auto_doc, parts)
                if so_layer is not None:
                    break

            if so_layer is None:
                logger.log_error(f"SO layer for PSB '{psb_name}'",
                                 SOEnterError("SO layer not found in auto doc"))
                continue

            try:
                so_doc = enter_smart_object(app, so_layer)
            except SOEnterError as e:
                logger.log_error(f"enter SO '{psb_name}'", e)
                continue

            try:
                so_dpi = float(safe_get(so_doc, "Resolution", auto_dpi))
                with LabDocument(app, so_dpi) as lab:
                    for record in group:
                        logger.log_layer_before(record)
                        try:
                            parts = record.layer_path.split("/")
                            layer = find_layer_by_path(so_doc, parts)
                            if layer is None:
                                layer = find_layer_by_id(so_doc, record.layer_id)
                            if layer is None:
                                raise LayerNotFoundError(
                                    f"Layer '{record.layer_path}' not found in SO '{psb_name}'"
                                )
                            new_font_ps = record.new_font_ps or record.font
                            new_text = record.new_text if record.new_text is not None else record.text
                            logger.log_apply_start(record.layer_path, record.bounds_h_px, new_font_ps)
                            params = lab.find_adapted_params(record, new_font_ps, new_text, logger)
                            _apply_to_text_layer(layer, params, record, logger)
                            logger.log_apply_result(record.layer_path, params, record)
                            logger.log_layer_after(record, params)
                        except Exception as e:
                            logger.log_error(f"apply SO layer '{record.layer_path}'", e)

                # Save and close SO doc
                try:
                    so_doc.Save()
                    so_doc.Close(1)  # save changes
                except Exception as e:
                    logger.log_error(f"save/close SO '{psb_name}'", e)

            except Exception as e:
                logger.log_error(f"process SO group '{psb_name}'", e)
                try:
                    so_doc.Close(2)
                except Exception:
                    pass

        # Save and close auto doc
        try:
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


def _apply_to_text_layer(art_layer, params: AdaptedParams, record: TextLayerRecord, logger) -> None:
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
    # Set contents last to avoid PS auto-reflow interfering with size
    new_text = record.new_text if record.new_text is not None else record.text
    try:
        ti.Contents = new_text
    except Exception as e:
        logger.log_error(f"set Contents on '{record.layer_path}'", e)


def _resolve_font_for_record(
    record: TextLayerRecord,
    font_index: dict,
    logger,
) -> str:
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
        f"→ PS name='{ps_name}'"
    )
    return ps_name


def _make_auto_path(source_psd_path: str) -> str:
    base, ext = os.path.splitext(source_psd_path)
    return base + "_auto" + ext


def _create_auto_copy(app, source_path: str, auto_path: str, logger) -> None:
    # Open the source if not already open, then SaveAs copy
    source_doc = None
    try:
        # Check if already open
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
        psd_opts = win32com.client.Dispatch("Photoshop.PSDSaveOptions")
        source_doc.SaveAs(auto_path, psd_opts, True)
        logger.log_copy_created(source_path, auto_path)
    except Exception as e:
        raise PSAError(f"Failed to create auto copy '{auto_path}': {e}")
    finally:
        if opened_here and source_doc is not None:
            try:
                source_doc.Close(2)
            except Exception:
                pass
