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

        # Adaptive convergence threshold: 0.5% of target, min 1px (2px for faux bold)
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

        # Phase 2: 5 precision iterations
        # For multiline: alternate between leading and size adjustments
        # For singleline: only adjust size via binary search
        if is_multiline and not record.auto_leading:
            try:
                ti.UseAutoLeading = False
                current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                ti.Leading = current_size * 1.2
            except Exception:
                pass

            for prec_iter in range(1, 6):
                h = get_h()
                if abs(h - target_h) < phase2_threshold:
                    break

                # Step 1: Adjust leading (7-iteration binary search)
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

                # Step 2: If still not converged, adjust size and re-anchor leading
                if abs(h - target_h) >= phase2_threshold:
                    try:
                        current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                        if h > target_h:
                            new_size = current_size * 0.97
                        else:
                            new_size = current_size * 1.03
                        ti.Size = new_size
                        ti.Leading = new_size * 1.2
                        last_mid = new_size
                    except Exception:
                        pass
        else:
            # Singleline (or multiline with auto_leading): size-only binary search
            for prec_iter in range(1, 6):
                h = get_h()
                if abs(h - target_h) < phase2_threshold:
                    break
                try:
                    current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                    lo_s = current_size * 0.95
                    hi_s = current_size * 1.05
                    for _ in range(7):
                        mid_s = (lo_s + hi_s) / 2.0
                        try: ti.Size = mid_s
                        except Exception: pass
                        h_test = get_h()
                        if h_test < target_h:
                            lo_s = mid_s
                        else:
                            hi_s = mid_s
                    last_mid = (lo_s + hi_s) / 2.0
                    try: ti.Size = last_mid
                    except Exception: pass
                except Exception:
                    pass

                h = get_h()
                try:
                    current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                except Exception:
                    current_size = last_mid

                log_entry = (
                    f"[prec {prec_iter:02d} size] tried={current_size:.4f}pt"
                    f" -> h={h:.2f}px target={target_h:.2f}px"
                )
                iterations_log.append(log_entry)
                if logger:
                    logger.log_iteration(10 + prec_iter, "size", current_size, h, target_h)

        # Capture Phase 2 state for boundary protection
        phase2_h = get_h()
        try:
            phase2_leading = float(safe_get(ti, "Leading", 0.0) or 0.0) if not is_multiline else 0.0
        except Exception:
            phase2_leading = 0.0

        # Phase 3: 5 tracking/size micro-adjustment iterations
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
        tracking_adjustment_failed = False

        for track_iter in range(1, 6):
            try:
                current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                new_w = get_w()

                # Step 1: Try to adjust tracking to match original width
                if orig_w > 1.0 and not tracking_adjustment_failed:
                    width_diff = new_w - orig_w
                    # Binary search for optimal tracking
                    lo_t = current_tracking - 50
                    hi_t = current_tracking + 50
                    for _ in range(7):
                        mid_t = (lo_t + hi_t) / 2.0
                        try: ti.Tracking = mid_t
                        except Exception: pass
                        w_test = get_w()
                        if w_test < orig_w:
                            lo_t = mid_t
                        else:
                            hi_t = mid_t
                    current_tracking = (lo_t + hi_t) / 2.0
                    current_tracking = max(-100, min(200, current_tracking))
                    try: ti.Tracking = current_tracking
                    except Exception: pass

                new_w_after = get_w()
                tracking_diff = abs(new_w_after - orig_w) if orig_w > 0 else 0

                log_entry = (
                    f"[micro {track_iter:02d} track] tracking={current_tracking:.1f} "
                    f"-> w={new_w_after:.2f}px orig_w={orig_w:.2f}px diff={tracking_diff:.2f}px"
                )
                iterations_log.append(log_entry)

                if tracking_diff < best_tracking_diff:
                    best_tracking_diff = tracking_diff
                    best_tracking = current_tracking

                # If width is close enough, stop
                if tracking_diff < 5.0:
                    break

                # Step 2: If tracking adjustment not helping, try size adjustment
                if tracking_diff > 10.0 and not tracking_adjustment_failed:
                    try:
                        ti.Tracking = record.tracking  # restore original tracking
                        new_size = current_size * 0.95
                        ti.Size = new_size
                        last_mid = new_size
                        log_entry = f"[micro {track_iter:02d} size] restored tracking, reduced size to {new_size:.4f}pt"
                        iterations_log.append(log_entry)

                        # Check if Phase 2 leading is affected (multiline only)
                        if is_multiline:
                            new_h = get_h()
                            h_diff = abs(new_h - phase2_h)
                            if h_diff > 2.0:
                                log_entry = (
                                    f"[micro {track_iter:02d} boundary] WARNING: size reduction affected leading. "
                                    f"phase2_h={phase2_h:.2f}px new_h={new_h:.2f}px diff={h_diff:.2f}px. "
                                    f"Stopping tracking adjustment."
                                )
                                iterations_log.append(log_entry)
                                tracking_adjustment_failed = True
                                break

                        # Try tracking adjustment again with new size
                        current_tracking = record.tracking
                    except Exception:
                        pass

            except Exception as e:
                log_entry = f"[micro {track_iter:02d}] error: {str(e)}"
                iterations_log.append(log_entry)

        # Apply best tracking found
        try:
            ti.Tracking = best_tracking
        except Exception:
            pass

        if tracking_adjustment_failed:
            log_entry = (
                f"[phase3 final] Text width and original differ significantly. "
                f"Prioritized leading preservation over width matching."
            )
            iterations_log.append(log_entry)

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
            tracking=best_tracking,
            final_bounds_h_px=final_h,
            target_h_px=target_h,
            converged=converged,
            iterations_log=iterations_log,
        )
