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
                self._doc.Close(2)  # don't save
            except Exception:
                pass
            self._doc = None

    def find_adapted_params(
        self,
        record: TextLayerRecord,
        new_font_ps: str,
        new_text: str,
        logger=None,
    ) -> AdaptedParams:
        doc = self._doc
        if doc is None:
            raise AdaptationError("Lab document is not open.")

        dpi = self._resolution
        target_h = record.bounds_h_px
        is_multiline = "\r" in new_text or "\n" in new_text
        iterations_log: list[str] = []

        # Activate lab doc
        try:
            self._app.ActiveDocument = doc
        except Exception:
            pass

        # Create text layer
        try:
            lab_layer = doc.ArtLayers.Add()
            lab_layer.Kind = 2  # TextLayer
        except Exception as e:
            raise AdaptationError(f"Failed to create text layer in lab doc: {e}")

        ti = lab_layer.TextItem

        # Set initial properties
        try:
            ti.Font = new_font_ps
        except Exception:
            pass
        try:
            ti.Contents = new_text
        except Exception:
            pass
        try:
            ti.Tracking = record.tracking
        except Exception:
            pass
        try:
            ti.UseAutoLeading = True
        except Exception:
            pass
        try:
            ti.Size = 72.0  # initial size
        except Exception:
            pass

        def get_h() -> float:
            with PixelUnitsContext(self._app):
                try:
                    bounds = lab_layer.Bounds
                    return float(bounds[3]) - float(bounds[1])
                except Exception:
                    return 0.0

        # Phase 1: 10-iteration binary search on size
        lo, hi = 1.0, 500.0
        last_mid = 72.0
        for i in range(1, 11):
            mid = (lo + hi) / 2.0
            try:
                ti.Size = mid
            except Exception:
                pass
            last_mid = mid
            h = get_h()
            if logger:
                logger.log_iteration(i, "size", mid, h, target_h)
            log_entry = f"[iter {i:02d} size] tried={mid:.4f}pt → h={h:.2f}px target={target_h:.2f}px"
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

                # Sub-step A: binary search leading in [size*0.8, size*2.5]
                try:
                    current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                    lo_l = current_size * 0.8
                    hi_l = current_size * 2.5
                    for _ in range(7):
                        mid_l = (lo_l + hi_l) / 2.0
                        try:
                            ti.Leading = mid_l
                        except Exception:
                            pass
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
                    f" → h={h:.2f}px target={target_h:.2f}px"
                )
                iterations_log.append(log_entry)
                if logger:
                    logger.log_iteration(10 + prec_iter, "lead", current_leading, h, target_h)

                # Sub-step B: nudge size if still not converged
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

        # Tracking placeholder
        self.adjust_tracking(ti, record)

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

        # Clean up lab layer for reuse
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
            tracking=record.tracking,
            final_bounds_h_px=final_h,
            target_h_px=target_h,
            converged=converged,
            iterations_log=iterations_log,
        )

    def adjust_tracking(self, ti, record: TextLayerRecord) -> None:
        # Placeholder: preserves original tracking. No auto-adjustment currently.
        try:
            ti.Tracking = record.tracking
        except Exception:
            pass
