"""
Adaptive text-fitting algorithm phases.

Extracted from LabDocument to keep per-file size manageable.
Each function receives the text item `ti`, measurement callbacks
(get_h, get_w), and phase-specific parameters.
"""
from __future__ import annotations
from psa_utils import safe_get


def phase1_binary_search(ti, get_h, target_h: float, iterations_log: list[str],
                         logger=None) -> float:
    """Phase 1: binary search on font size, max 10 iterations, early exit.

    Returns last_mid (best size in pt).
    """
    lo, hi = 1.0, 500.0
    last_mid = 72.0
    _safety = False
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
        if abs(hi - lo) < 2.0 or (h > 0 and abs(h - target_h) / target_h < 0.04):
            if _safety:
                break
            _safety = True
    return last_mid


def phase2_multiline(ti, get_h, target_h: float, phase2_threshold: float,
                     last_mid: float, iterations_log: list[str],
                     logger=None) -> float:
    """Phase 2: multiline leading+size precision, max 5 rounds, early exit.

    Returns updated last_mid.
    """
    try:
        ti.UseAutoLeading = False
        current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
        ti.Leading = current_size * 1.2
    except Exception:
        pass

    _safety = False
    for prec_iter in range(1, 6):
        h = get_h()
        if abs(h - target_h) < phase2_threshold:
            if _safety:
                break
            _safety = True

        try:
            current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
            lo_l = current_size * 0.8
            hi_l = current_size * 2.5
            for _ in range(5):
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
            logger.log_iteration(7 + prec_iter, "lead", current_leading, h, target_h)

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
    return last_mid


def phase2_singleline(ti, get_h, target_h: float, phase2_threshold: float,
                      last_mid: float, iterations_log: list[str],
                      logger=None) -> float:
    """Phase 2: singleline size-only binary search, max 5 rounds, early exit.

    Returns updated last_mid.
    """
    _safety = False
    for prec_iter in range(1, 6):
        h = get_h()
        if abs(h - target_h) < phase2_threshold:
            if _safety:
                break
            _safety = True
        try:
            current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
            lo_s = current_size * 0.95
            hi_s = current_size * 1.05
            for _ in range(5):
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
            logger.log_iteration(7 + prec_iter, "size", current_size, h, target_h)
    return last_mid


def width_precheck(ti, get_h, get_w, target_h: float, phase2_threshold: float,
                   orig_w: float, orig_size_pt: float, last_mid: float,
                   iterations_log: list[str], logger=None) -> float:
    """Level 1: width pre-check. If new width > 1.3x original, pre-scale size
    and re-run simplified Phase 2 (3 rounds, size-only).

    Returns updated last_mid.
    """
    if orig_w <= 1.0:
        return last_mid

    new_w = get_w()
    if new_w <= orig_w * 1.3:
        return last_mid

    prescale = orig_w / new_w
    current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
    new_size = current_size * prescale
    size_floor = orig_size_pt * 0.8
    if new_size < size_floor:
        new_size = size_floor
    try: ti.Size = new_size
    except Exception: pass
    last_mid = new_size

    log_entry = (
        f"[width pre-check] new_w={new_w:.1f}px orig_w={orig_w:.1f}px "
        f"ratio={new_w / orig_w:.2f} > 1.3 → prescale to {new_size:.4f}pt "
        f"(floor={size_floor:.1f}pt)"
    )
    iterations_log.append(log_entry)
    if logger:
        logger.log_info(log_entry)

    # Re-run simplified Phase 2 (size-only, 3 rounds)
    for prec_iter in range(1, 4):
        h = get_h()
        if abs(h - target_h) < phase2_threshold:
            break
        try:
            cs = float(safe_get(ti, "Size", last_mid) or last_mid)
            lo_s = cs * 0.95
            hi_s = cs * 1.05
            for _ in range(5):
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
            cs = float(safe_get(ti, "Size", last_mid) or last_mid)
        except Exception:
            cs = last_mid
        log_entry = (
            f"[width pre-scale p2 {prec_iter:02d}] size={cs:.4f}pt "
            f"-> h={h:.2f}px target={target_h:.2f}px"
        )
        iterations_log.append(log_entry)
        if logger:
            logger.log_iteration(90 + prec_iter, "prescale", cs, h, target_h)
    return last_mid


# Return type for phase3_tracking
class Phase3Result:
    __slots__ = ("best_tracking", "last_mid", "tracking_adjustment_failed",
                 "width_hard_clamped")
    def __init__(self, best_tracking, last_mid, tracking_adjustment_failed,
                 width_hard_clamped):
        self.best_tracking = best_tracking
        self.last_mid = last_mid
        self.tracking_adjustment_failed = tracking_adjustment_failed
        self.width_hard_clamped = width_hard_clamped


def phase3_tracking(ti, get_h, get_w, phase2_h: float, orig_w: float,
                    record, last_mid: float, is_multiline: bool,
                    iterations_log: list[str], logger=None) -> Phase3Result:
    """Phase 3: tracking/size micro-adjustment, max 5 rounds, early exit.

    Returns Phase3Result with best_tracking, updated last_mid, and failure flags.
    """
    current_tracking = record.tracking
    best_tracking = current_tracking
    best_tracking_diff = float('inf')
    tracking_adjustment_failed = False
    width_hard_clamped = False

    _safety = False
    for track_iter in range(1, 6):
        try:
            current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
            new_w = get_w()

            # Step 1: Try to adjust tracking to match original width
            if orig_w > 1.0 and not tracking_adjustment_failed:
                lo_t = current_tracking - 50
                hi_t = current_tracking + 50
                for _ in range(5):
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

            if tracking_diff < 5.0:
                if _safety:
                    break
                _safety = True

            # Step 2: tracking at limit, binary-search size down to match width
            if tracking_diff > 10.0 and not tracking_adjustment_failed:
                try:
                    ti.Tracking = -100.0
                except Exception:
                    pass

                current_size = float(safe_get(ti, "Size", last_mid) or last_mid)
                size_floor = record.size_pt * 0.8
                lo_s = size_floor
                hi_s = current_size
                best_size = current_size
                best_w_diff = tracking_diff

                for _ in range(5):
                    mid_s = (lo_s + hi_s) / 2.0
                    try: ti.Size = mid_s
                    except Exception: pass
                    w_test = get_w()
                    wd = abs(w_test - orig_w) if orig_w > 0 else 0
                    if wd < best_w_diff:
                        best_w_diff = wd
                        best_size = mid_s
                    if w_test > orig_w:
                        lo_s = mid_s
                    else:
                        hi_s = mid_s

                # Check leading impact for multiline
                if is_multiline:
                    try: ti.Size = best_size
                    except Exception: pass
                    new_h = get_h()
                    h_diff = abs(new_h - phase2_h)
                    if h_diff > 3.0:
                        best_size = max(best_size, current_size * 0.85)
                        try: ti.Size = best_size
                        except Exception: pass
                        log_entry = (
                            f"[micro {track_iter:02d} boundary] WARNING: size reduction "
                            f"affecting leading. phase2_h={phase2_h:.2f}px "
                            f"new_h={new_h:.2f}px h_diff={h_diff:.2f}px. "
                            f"backing off to {best_size:.4f}pt."
                        )
                        iterations_log.append(log_entry)
                        tracking_adjustment_failed = True
                        last_mid = best_size
                        continue

                # Check hard floor
                if best_size <= size_floor:
                    best_size = size_floor
                    try: ti.Size = best_size
                    except Exception: pass
                    try: ti.Tracking = -100.0
                    except Exception: pass
                    last_mid = best_size
                    width_hard_clamped = True
                    tracking_adjustment_failed = True
                    log_entry = (
                        f"[micro {track_iter:02d} clamp] WARNING: size at 80% floor "
                        f"({record.size_pt:.1f}pt → {best_size:.4f}pt). "
                        f"width overflow, giving up width matching."
                    )
                    iterations_log.append(log_entry)
                    if logger:
                        logger.log_warning(log_entry)
                    break

                try: ti.Size = best_size
                except Exception: pass
                last_mid = best_size
                log_entry = (
                    f"[micro {track_iter:02d} size] binary-searched size to "
                    f"{best_size:.4f}pt floor={size_floor:.1f}pt w_diff={best_w_diff:.1f}px"
                )
                iterations_log.append(log_entry)
                current_tracking = -100.0

        except Exception as e:
            log_entry = f"[micro {track_iter:02d}] error: {str(e)}"
            iterations_log.append(log_entry)

    # Apply best tracking found
    try:
        ti.Tracking = best_tracking
    except Exception:
        pass

    return Phase3Result(best_tracking, last_mid, tracking_adjustment_failed,
                        width_hard_clamped)
