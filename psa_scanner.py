from __future__ import annotations
from psa_models import TextLayerRecord
from psa_utils import (
    PixelUnitsContext,
    safe_get,
    layer_bounds_px,
    enter_smart_object,
    get_so_psb_name,
    pt_to_px,
    PSAError,
    SOEnterError,
)


def scan_document(app, doc, logger=None) -> list[TextLayerRecord]:
    records: list[TextLayerRecord] = []
    visited_psbs: set[str] = set()
    dpi = float(safe_get(doc, "Resolution", 72.0))

    if logger:
        logger.log_scan_start(
            doc_name=safe_get(doc, "Name", "unknown"),
            doc_path=safe_get(doc, "FullName", ""),
            dpi=dpi,
        )

    with PixelUnitsContext(app):
        _walk_layers(
            app=app,
            container=doc,
            path_parts=[],
            dpi=dpi,
            in_smart_object=False,
            so_layer_id=None,
            so_layer_path=None,
            so_psb_name=None,
            records=records,
            visited_psbs=visited_psbs,
            logger=logger,
        )

    if logger:
        logger.log_scan_complete(len(records))

    return records


def _walk_layers(
    app,
    container,
    path_parts: list[str],
    dpi: float,
    in_smart_object: bool,
    so_layer_id: int | None,
    so_layer_path: str | None,
    so_psb_name: str | None,
    records: list[TextLayerRecord],
    visited_psbs: set[str],
    logger,
    so_chain: list[dict] | None = None,
):
    try:
        layers = container.Layers
        count = layers.Count
    except Exception:
        return

    for i in range(count):
        try:
            layer = layers[i]
        except Exception:
            continue

        layer_name = safe_get(layer, "Name", f"Layer_{i}")
        current_path = path_parts + [layer_name]

        # Determine layer kind
        kind = safe_get(layer, "Kind", None)

        if kind == 2:  # TextLayer
            try:
                record = _extract_text_record(
                    app=app,
                    art_layer=layer,
                    path_parts=current_path,
                    dpi=dpi,
                    in_smart_object=in_smart_object,
                    so_layer_id=so_layer_id,
                    so_layer_path=so_layer_path,
                    so_psb_name=so_psb_name,
                    so_chain=so_chain or [],
                )
                records.append(record)
                if logger:
                    logger.log_scan_layer(record)
            except Exception as e:
                if logger:
                    logger.log_error(f"scan text layer {'/'.join(current_path)}", e)

        elif kind == 17:  # SmartObject
            # Cap nested SO depth at 3 levels
            current_depth = len(so_chain or [])
            if current_depth >= 3:
                if logger:
                    logger.log_info(
                        f"SO max depth reached (3), skipping nested SO: "
                        f"{'/'.join(current_path)}"
                    )
                continue

            psb_name = get_so_psb_name(app, layer)

            if psb_name in visited_psbs:
                if logger:
                    logger.log_info(f"SO PSB '{psb_name}' already visited, skipping: {'/'.join(current_path)}")
                continue

            visited_psbs.add(psb_name)

            try:
                so_doc = enter_smart_object(app, layer)
                so_dpi = float(safe_get(so_doc, "Resolution", dpi))
                so_layer_path_str = "/".join(current_path)
                so_id = safe_get(layer, "id", None)

                # Build chain entry and append for nested SO tracking
                entry = {"psb_name": psb_name, "layer_path": so_layer_path_str, "layer_id": so_id}
                new_chain = (so_chain or []) + [entry]

                with PixelUnitsContext(app):
                    _walk_layers(
                        app=app,
                        container=so_doc,
                        path_parts=[],
                        dpi=so_dpi,
                        in_smart_object=True,
                        so_layer_id=so_id,
                        so_layer_path=so_layer_path_str,
                        so_psb_name=psb_name,
                        records=records,
                        visited_psbs=visited_psbs,
                        logger=logger,
                        so_chain=new_chain,
                    )

                # Close SO doc without saving
                try:
                    so_doc.Close(2)  # 2 = don't save
                except Exception:
                    pass

            except SOEnterError as e:
                if logger:
                    logger.log_error(f"enter SO {'/'.join(current_path)}", e)

        else:
            # Try recurse (LayerSet / group has no Kind or Kind=3)
            try:
                _ = layer.Layers
                _walk_layers(
                    app=app,
                    container=layer,
                    path_parts=current_path,
                    dpi=dpi,
                    in_smart_object=in_smart_object,
                    so_layer_id=so_layer_id,
                    so_layer_path=so_layer_path,
                    so_psb_name=so_psb_name,
                    records=records,
                    visited_psbs=visited_psbs,
                    logger=logger,
                    so_chain=so_chain,
                )
            except Exception:
                pass


def _extract_text_record(
    app,
    art_layer,
    path_parts: list[str],
    dpi: float,
    in_smart_object: bool,
    so_layer_id: int | None,
    so_layer_path: str | None,
    so_psb_name: str | None,
    so_chain: list[dict] | None = None,
) -> TextLayerRecord:
    ti = art_layer.TextItem
    layer_id = safe_get(art_layer, "id", -1)
    layer_name = safe_get(art_layer, "Name", path_parts[-1] if path_parts else "")
    layer_path = "/".join(path_parts)

    text = safe_get(ti, "Contents", "")
    font = safe_get(ti, "Font", "")
    size_pt = float(safe_get(ti, "Size", 12.0) or 12.0)
    size_px = pt_to_px(size_pt, dpi)

    tracking = float(safe_get(ti, "Tracking", 0.0) or 0.0)

    auto_leading = bool(safe_get(ti, "UseAutoLeading", True))
    leading_pt = 0.0
    if not auto_leading:
        leading_pt = float(safe_get(ti, "Leading", 0.0) or 0.0)
    leading_px = pt_to_px(leading_pt, dpi)

    auto_leading_amount = float(safe_get(ti, "AutoLeadingAmount", 0.0) or 0.0)

    faux_bold = bool(safe_get(ti, "FauxBold", False))
    faux_italic = bool(safe_get(ti, "FauxItalic", False))

    just_val = safe_get(ti, "Justification", None)
    justification = str(just_val) if just_val is not None else ""

    cap_val = safe_get(ti, "Capitalization", None)
    capitalization = str(cap_val) if cap_val is not None else ""

    aa_val = safe_get(ti, "AntiAlias", None)
    anti_alias = str(aa_val) if aa_val is not None else ""

    # Color
    color_r = color_g = color_b = 0.0
    try:
        color = ti.Color
        rgb = color.RGB
        color_r = float(rgb.Red)
        color_g = float(rgb.Green)
        color_b = float(rgb.Blue)
    except Exception:
        pass

    # Bounding box
    bounds = layer_bounds_px(app, art_layer)
    bl, bt, br, bb = bounds
    bounds_h = bb - bt

    return TextLayerRecord(
        layer_id=layer_id,
        layer_name=layer_name,
        layer_path=layer_path,
        in_smart_object=in_smart_object,
        so_layer_id=so_layer_id,
        so_layer_path=so_layer_path,
        so_psb_name=so_psb_name,
        text=text,
        font=font,
        size_pt=size_pt,
        size_px=size_px,
        tracking=tracking,
        auto_leading=auto_leading,
        leading_pt=leading_pt,
        leading_px=leading_px,
        bounds_left=bl,
        bounds_top=bt,
        bounds_right=br,
        bounds_bottom=bb,
        bounds_h_px=bounds_h,
        dpi=dpi,
        faux_bold=faux_bold,
        faux_italic=faux_italic,
        justification=justification,
        capitalization=capitalization,
        anti_alias=anti_alias,
        auto_leading_amount=auto_leading_amount,
        color_r=color_r,
        color_g=color_g,
        color_b=color_b,
        so_chain=so_chain or [],
    )
