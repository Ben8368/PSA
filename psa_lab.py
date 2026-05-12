from __future__ import annotations
from psa_models import TextLayerRecord, AdaptedParams
from psa_utils import PixelUnitsContext, safe_get, pt_to_px, AdaptationError


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
        """Get text layer width in pixels."""
        with PixelUnitsContext(self._app):
            try:
                bounds = lab_layer.Bounds
                return float(bounds[2]) - float(bounds[0])
            except Exception:
                return 0.0

    def measure_text(self, font_ps: str, contents: str, size_pt: float,
                      tracking: float, auto_leading: bool, leading_pt: float) -> float:
        """Render text with given params in lab doc, return its bounds height in px. Cleans up layer after."""
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
        """Render text and return its bounds width in px."""
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

        self._activate()
        lab_layer, ti = self._create_text_layer(
            new_font_ps, new_text, 72.0, record.tracking, True, 0.0
        )

        def get_h() -> float:
            return self._get_h(lab_layer)

        def get_w() -> float:
            return self._get_w(lab_layer)

        # Phase 1: 10-iteration binary search on size
        lo, hi = 1.0, 500.0
        last_mid = 72.0
        for i in range(1, 11):
            mid = (lo + hi) / 2.0
            try: ti.Size = mid
            except Exception: pass
            last_mid = mid
            h = get_h()
            if logger:
                logger.log_iteration(i, "size", mid, h, target_h)
            log_entry = f"[iter {i:02d} size] tried={mid:.4f}pt -> h={h:.2f}px target={target_h:.2f}px"
            iterations_log.append(log_entry)
            if h < target_h:
                lo = mid
            else:
                hi = mid

        # Phase 2: 5 precision iterations (multiline only)
        if is_multiline:
            try:
                ti.UseAutoLeading = False
                current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                ti.Leading = current_size * 1.2
            except Exception:
                pass

            for prec_iter in range(1, 6):
                h = get_h()
                if abs(h - target_h) < 1.0:
                    break
                try:
                    current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                    lo_l = current_size * 0.8
                    hi_l = current_size * 2.5
                    for _ in range(7):
                        mid_l = (lo_l + hi_l) / 2.0
                        try: ti.Leading = mid_l
                        except Exception: pass
                        h_test = get_h()
                        if h_test < target_h:
                            lo_l = mid_l
                        else:
                            hi_l = mid_l
                except Exception:
                    pass

                h = get_h()
                try:
                    current_leading = float(safe_get(ti, "Leading", 0.0) or 0.0)
                except Exception:
                    current_leading = 0.0

                log_entry = (
                    f"[prec {prec_iter:02d} lead] tried={current_leading:.4f}pt"
                    f" -> h={h:.2f}px target={target_h:.2f}px"
                )
                iterations_log.append(log_entry)
                if logger:
                    logger.log_iteration(10 + prec_iter, "lead", current_leading, h, target_h)

                if abs(h - target_h) >= 1.0:
                    try:
                        current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                        if h > target_h:
                            new_size = current_size * 0.97
                        else:
                            new_size = current_size * 1.03
                        ti.Size = new_size
                        ti.Leading = new_size * 1.2
                    except Exception:
                        pass

        # Phase 3: 5 tracking adaptation iterations
        # Measure original text width for comparison
        try:
            orig_w = self.measure_text_width(
                record.font, record.text, record.size_pt,
                record.tracking, record.auto_leading, record.leading_pt
            )
        except Exception:
            orig_w = 0.0

        current_tracking = record.tracking
        best_tracking = current_tracking
        best_tracking_diff = float('inf')

        for track_iter in range(1, 6):
            try:
                current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                new_w = get_w()

                # Calculate tracking adjustment needed
                if orig_w > 1.0:
                    width_ratio = new_w / orig_w
                    # Adjust tracking to bring widths closer
                    # Negative tracking makes text tighter, positive makes it looser
                    if width_ratio > 1.05:  # new text is too wide
                        current_tracking = current_tracking - 20
                    elif width_ratio < 0.95:  # new text is too narrow
                        current_tracking = current_tracking + 20
                    else:
                        # Close enough, stop adjusting
                        current_tracking = best_tracking
                        break

                # Clamp tracking to reasonable range
                current_tracking = max(-100, min(200, current_tracking))
                try:
                    ti.Tracking = current_tracking
                except Exception:
                    pass

                new_w_after = get_w()
                tracking_diff = abs(new_w_after - orig_w) if orig_w > 0 else 0

                log_entry = (
                    f"[track {track_iter:02d}] tracking={current_tracking:.1f} "
                    f"-> w={new_w_after:.2f}px orig_w={orig_w:.2f}px diff={tracking_diff:.2f}px"
                )
                iterations_log.append(log_entry)

                if tracking_diff < best_tracking_diff:
                    best_tracking_diff = tracking_diff
                    best_tracking = current_tracking

                # If width is close enough, stop
                if tracking_diff < 5.0:
                    break

                # If tracking adjustment is not helping, try reducing size instead
                if track_iter == 5 and tracking_diff > 10.0:
                    try:
                        ti.Tracking = record.tracking  # restore original tracking
                        new_size = current_size * 0.95
                        ti.Size = new_size
                        log_entry = f"[track {track_iter:02d} fallback] restored tracking, reduced size to {new_size:.4f}pt"
                        iterations_log.append(log_entry)
                    except Exception:
                        pass

            except Exception as e:
                log_entry = f"[track {track_iter:02d}] error: {str(e)}"
                iterations_log.append(log_entry)

        # Apply best tracking found
        try:
            ti.Tracking = best_tracking
        except Exception:
            pass

        # Capture final state
        final_h = get_h()
        try:
            final_size_pt = float(safe_get(ti, "Size", last_mid) or last_mid)
        except Exception:
            final_size_pt = last_mid

        final_auto_leading = bool(safe_get(ti, "UseAutoLeading", True))
        final_leading_pt = 0.0
        if not final_auto_leading:
            final_leading_pt = float(safe_get(ti, "Leading", 0.0) or 0.0)

        final_size_px = pt_to_px(final_size_pt, dpi)
        final_leading_px = pt_to_px(final_leading_pt, dpi)
        converged = abs(final_h - target_h) < 2.0

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
            tracking=best_tracking,
            final_bounds_h_px=final_h,
            target_h_px=target_h,
            converged=converged,
            iterations_log=iterations_log,
        )
