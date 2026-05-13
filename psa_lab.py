from __future__ import annotations
from psa_models import TextLayerRecord, AdaptedParams
from psa_utils import PixelUnitsContext, safe_get, pt_to_px, AdaptationError
from psa_algorithm import (
    phase1_binary_search,
    phase2_multiline,
    phase2_singleline,
    width_precheck,
    phase3_tracking,
)


class LabDocument:
    def __init__(self, app, resolution: float):
        self._app = app
        self._resolution = resolution
        self._doc = None

    def __enter__(self):
        try:
            self._doc = self._app.Documents.Add(
                1000, 1000, self._resolution, "PSA_Lab"
            )
        except Exception as e:
            raise AdaptationError(f"Failed to create lab document: {e}")
        return self

    def __exit__(self, *args):
        if self._doc is not None:
            try:
                self._doc.Close(2)
            except Exception:
                pass
            self._doc = None

    def _activate(self):
        try:
            self._app.ActiveDocument = self._doc
        except Exception:
            pass

    def _create_text_layer(self, font_ps: str, contents: str, size_pt: float,
                            tracking: float, auto_leading: bool, leading_pt: float):
        doc = self._doc
        try:
            lab_layer = doc.ArtLayers.Add()
            lab_layer.Kind = 2
        except Exception as e:
            raise AdaptationError(f"Failed to create text layer in lab doc: {e}")
        ti = lab_layer.TextItem
        try: ti.Font = font_ps
        except Exception: pass
        try: ti.Contents = contents
        except Exception: pass
        try: ti.Tracking = tracking
        except Exception: pass
        try: ti.UseAutoLeading = auto_leading
        except Exception: pass
        if not auto_leading and leading_pt > 0:
            try: ti.Leading = leading_pt
            except Exception: pass
        try: ti.Size = size_pt
        except Exception: pass
        return lab_layer, ti

    def _get_h(self, lab_layer) -> float:
        with PixelUnitsContext(self._app):
            try:
                bounds = lab_layer.Bounds
                return float(bounds[3]) - float(bounds[1])
            except Exception:
                return 0.0

    def _get_w(self, lab_layer) -> float:
        with PixelUnitsContext(self._app):
            try:
                bounds = lab_layer.Bounds
                return float(bounds[2]) - float(bounds[0])
            except Exception:
                return 0.0

    def measure_text(self, font_ps: str, contents: str, size_pt: float,
                      tracking: float, auto_leading: bool, leading_pt: float) -> float:
        if self._doc is None:
            raise AdaptationError("Lab document is not open.")
        self._activate()
        lab_layer, _ti = self._create_text_layer(
            font_ps, contents, size_pt, tracking, auto_leading, leading_pt
        )
        h = self._get_h(lab_layer)
        try:
            lab_layer.Delete()
        except Exception:
            pass
        return h

    def measure_text_width(self, font_ps: str, contents: str, size_pt: float,
                           tracking: float, auto_leading: bool, leading_pt: float) -> float:
        if self._doc is None:
            raise AdaptationError("Lab document is not open.")
        self._activate()
        lab_layer, _ti = self._create_text_layer(
            font_ps, contents, size_pt, tracking, auto_leading, leading_pt
        )
        w = self._get_w(lab_layer)
        try:
            lab_layer.Delete()
        except Exception:
            pass
        return w

    def find_adapted_params(
        self,
        record: TextLayerRecord,
        new_font_ps: str,
        new_text: str,
        logger=None,
        target_h_override: float | None = None,
    ) -> AdaptedParams:
        doc = self._doc
        if doc is None:
            raise AdaptationError("Lab document is not open.")

        dpi = self._resolution
        target_h = target_h_override if target_h_override is not None else record.bounds_h_px
        is_multiline = "\r" in new_text or "\n" in new_text
        iterations_log: list[str] = []

        _base = max(1.0, target_h * 0.005)
        phase2_threshold = max(2.0, target_h * 0.01) if record.faux_bold else _base
        final_threshold = max(2.0, target_h * 0.01) if record.faux_bold else max(2.0, target_h * 0.008)

        self._activate()
        lab_layer, ti = self._create_text_layer(
            new_font_ps, new_text, 72.0, record.tracking, record.auto_leading, record.leading_pt
        )

        def get_h() -> float:
            return self._get_h(lab_layer)

        def get_w() -> float:
            return self._get_w(lab_layer)

        # Phase 1: binary search on size
        last_mid = phase1_binary_search(ti, get_h, target_h, iterations_log, logger)

        # Phase 2: precision adjustment
        if is_multiline and not record.auto_leading:
            last_mid = phase2_multiline(ti, get_h, target_h, phase2_threshold,
                                        last_mid, iterations_log, logger)
        else:
            last_mid = phase2_singleline(ti, get_h, target_h, phase2_threshold,
                                         last_mid, iterations_log, logger)

        # Capture Phase 2 state
        phase2_h = get_h()
        try:
            phase2_leading = float(safe_get(ti, "Leading", 0.0) or 0.0) if is_multiline else 0.0
        except Exception:
            phase2_leading = 0.0

        # Measure original text width once
        try:
            orig_w = self.measure_text_width(
                record.font, record.text, record.size_pt,
                record.tracking, record.auto_leading, record.leading_pt
            )
        except Exception:
            orig_w = 0.0

        # Level 1: width pre-check
        last_mid = width_precheck(ti, get_h, get_w, target_h, phase2_threshold,
                                  orig_w, record.size_pt, last_mid, iterations_log, logger)

        # Phase 3: tracking/size micro-adjustment
        p3 = phase3_tracking(ti, get_h, get_w, phase2_h, orig_w, record,
                             last_mid, is_multiline, iterations_log, logger)

        if p3.tracking_adjustment_failed:
            if p3.width_hard_clamped:
                log_entry = (
                    f"[phase3 final] Width overflow: size clamped at 80% floor "
                    f"({record.size_pt:.1f}pt). Tracking locked at -100. "
                    f"Width matching abandoned for readability."
                )
            else:
                log_entry = (
                    f"[phase3 final] Width mismatch. "
                    f"Prioritized height/leading preservation over width matching."
                )
            iterations_log.append(log_entry)

        # Capture final state
        final_h = get_h()
        try:
            final_size_pt = float(safe_get(ti, "Size", p3.last_mid) or p3.last_mid)
        except Exception:
            final_size_pt = p3.last_mid

        final_auto_leading = bool(safe_get(ti, "UseAutoLeading", True))
        final_leading_pt = 0.0
        if not final_auto_leading:
            final_leading_pt = float(safe_get(ti, "Leading", 0.0) or 0.0)

        final_size_px = pt_to_px(final_size_pt, dpi)
        final_leading_px = pt_to_px(final_leading_pt, dpi)
        converged = abs(final_h - target_h) < final_threshold

        try:
            lab_layer.Delete()
        except Exception:
            pass

        return AdaptedParams(
            font_ps=new_font_ps,
            size_pt=final_size_pt,
            size_px=final_size_px,
            auto_leading=final_auto_leading,
            leading_pt=final_leading_pt,
            leading_px=final_leading_px,
            tracking=p3.best_tracking,
            final_bounds_h_px=final_h,
            target_h_px=target_h,
            converged=converged,
            iterations_log=iterations_log,
        )
