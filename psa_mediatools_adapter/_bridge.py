"""
Bridge between MediaTools PhotoshopConnector and PSA's raw COM app.
Handles unit-safety so PSA's PixelUnitsContext doesn't fight the connector.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class ModifyResult:
    """Compatible with MediaTools ModifyResult for frontend consumption."""
    layer_path: str
    layer_name: str
    original_text: str
    new_text: str
    original_font: str
    new_font: str
    original_size_pt: float
    final_size_pt: float
    original_tracking: float
    final_tracking: float
    original_bounds_h: float
    final_bounds_h: float
    original_leading: float = -1.0
    final_leading: float = -1.0
    converged: bool = False
    skipped: bool = False
    message: str = ""


def extract_app(ps) -> Any:
    """Extract raw COM Application from a PhotoshopConnector instance or None.

    Returns the COM app object directly if ps is already one,
    or ps.app if it's a PhotoshopConnector.
    If ps is None, calls GetActiveObject to find running PS instance.
    """
    if ps is None:
        import win32com.client
        return win32com.client.GetActiveObject("Photoshop.Application")
    if hasattr(ps, 'app') and ps.app is not None:
        return ps.app
    return ps  # assume raw COM object


def connector_guard(ps):
    """Context manager that preserves connector unit state across PSA operations.

    PSA uses PixelUnitsContext internally, which saves/restores RulerUnits.
    The connector may have set TypeUnits globally. This guard ensures both
    are restored after PSA code runs.
    """
    return _ConnectorGuard(ps)


class _ConnectorGuard:
    def __init__(self, ps):
        self._ps = ps
        self._saved_type_units = None

    def __enter__(self):
        app = extract_app(self._ps)
        try:
            self._saved_type_units = app.Preferences.TypeUnits
        except Exception:
            pass
        return self

    def __exit__(self, *args):
        if self._saved_type_units is not None:
            app = extract_app(self._ps)
            try:
                app.Preferences.TypeUnits = self._saved_type_units
            except Exception:
                pass


def make_result(record, params=None, *, skipped: bool = False, message: str = "") -> ModifyResult:
    """Build a ModifyResult from a TextLayerRecord + optional AdaptedParams."""
    from psa_models import AdaptedParams

    if params is None:
        params = AdaptedParams(
            font_ps=record.font,
            size_pt=record.size_pt,
            size_px=record.size_px,
            auto_leading=record.auto_leading,
            leading_pt=record.leading_pt,
            leading_px=record.leading_px,
            tracking=record.tracking,
            final_bounds_h_px=record.bounds_h_px,
            target_h_px=record.bounds_h_px,
            converged=not skipped,
            iterations_log=[],
        )

    return ModifyResult(
        layer_path=record.layer_path,
        layer_name=record.layer_name,
        original_text=record.text,
        new_text=record.new_text or record.text,
        original_font=record.font,
        new_font=params.font_ps,
        original_size_pt=record.size_pt,
        final_size_pt=params.size_pt,
        original_tracking=record.tracking,
        final_tracking=params.tracking,
        original_bounds_h=record.bounds_h_px,
        final_bounds_h=params.final_bounds_h_px,
        original_leading=record.leading_pt,
        final_leading=params.leading_pt,
        converged=params.converged,
        skipped=skipped,
        message=message,
    )
