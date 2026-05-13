from __future__ import annotations
import win32com.client


class PSAError(Exception):
    pass


class PSNotRunningError(PSAError):
    pass


class NoActiveDocumentError(PSAError):
    pass


class LayerNotFoundError(PSAError):
    pass


class FontNotFoundError(PSAError):
    pass


class SOEnterError(PSAError):
    pass


class AdaptationError(PSAError):
    pass


def get_app():
    try:
        app = win32com.client.GetActiveObject("Photoshop.Application")
        return app
    except Exception:
        raise PSNotRunningError("Photoshop is not running. Please start Photoshop first.")


def get_active_doc(app):
    try:
        doc = app.ActiveDocument
        if doc is None:
            raise NoActiveDocumentError("No document is currently open in Photoshop.")
        return doc
    except PSAError:
        raise
    except Exception:
        raise NoActiveDocumentError("No document is currently open in Photoshop.")


class PixelUnitsContext:
    def __init__(self, app):
        self._app = app
        self._orig = None

    def __enter__(self):
        try:
            self._orig = self._app.Preferences.RulerUnits
        except Exception:
            self._orig = None
        try:
            self._app.Preferences.RulerUnits = 1  # psPixels
        except Exception:
            pass
        return self

    def __exit__(self, *args):
        if self._orig is not None:
            try:
                self._app.Preferences.RulerUnits = self._orig
            except Exception:
                pass


def safe_get(obj, attr, default=None):
    try:
        val = getattr(obj, attr)
        return val
    except Exception:
        return default


def layer_bounds_px(app, art_layer) -> tuple[float, float, float, float]:
    with PixelUnitsContext(app):
        try:
            bounds = art_layer.Bounds
            l = float(bounds[0])
            t = float(bounds[1])
            r = float(bounds[2])
            b = float(bounds[3])
            return (l, t, r, b)
        except Exception as e:
            raise PSAError(f"Failed to read layer bounds: {e}")


_JS_ENTER_SO = """
var idplacedLayerEditContents = stringIDToTypeID("placedLayerEditContents");
var desc = new ActionDescriptor();
executeAction(idplacedLayerEditContents, desc, DialogModes.NO);
"""


def enter_smart_object(app, so_layer):
    try:
        app.ActiveDocument.ActiveLayer = so_layer
        app.DoJavaScript(_JS_ENTER_SO)
        return app.ActiveDocument
    except Exception as e:
        raise SOEnterError(f"Failed to enter Smart Object '{so_layer.Name}': {e}")


def find_layer_by_id(container, layer_id: int):
    try:
        layers = container.Layers
    except Exception:
        return None
    for i in range(layers.Count):
        try:
            layer = layers[i]
        except Exception:
            continue
        try:
            if layer.id == layer_id:
                return layer
        except Exception:
            pass
        # recurse into layer sets
        try:
            kind = layer.Kind
        except Exception:
            kind = None
        if kind is None:
            # LayerSet has no Kind attr — try recurse
            result = find_layer_by_id(layer, layer_id)
            if result is not None:
                return result
        elif kind == 3:  # LayerKind.NormalLayer means it's a group in some PS versions
            result = find_layer_by_id(layer, layer_id)
            if result is not None:
                return result
        # Also check if it's a group by trying to access .Layers
        try:
            _ = layer.Layers
            result = find_layer_by_id(layer, layer_id)
            if result is not None:
                return result
        except Exception:
            pass
    return None


def find_layer_by_path(container, path_parts: list[str]):
    if not path_parts:
        return None
    name = path_parts[0]
    rest = path_parts[1:]
    try:
        layers = container.Layers
    except Exception:
        return None
    for i in range(layers.Count):
        try:
            layer = layers[i]
        except Exception:
            continue
        try:
            if layer.Name == name:
                if not rest:
                    return layer
                return find_layer_by_path(layer, rest)
        except Exception:
            continue
    return None


_JS_GET_SO_FILENAME = """
var lyr = app.activeDocument.activeLayer;
var ref = new ActionReference();
ref.putEnumerated(charIDToTypeID("Lyr "), charIDToTypeID("Ordn"), charIDToTypeID("Trgt"));
var desc = executeActionGet(ref);
var soDesc = desc.getObjectValue(stringIDToTypeID("smartObject"));
var fname = soDesc.getString(stringIDToTypeID("fileReference"));
fname;
"""

_JS_EXPAND_SO_CANVAS = """
// Expand the canvas of the current SO document.
// scale factor is injected from Python side.
var doc = app.activeDocument;
var origWidth = doc.width;
var origHeight = doc.height;
var newWidth = origWidth * {scale};
var newHeight = origHeight * {scale};
var offsetX = (newWidth - origWidth) / 2;
var offsetY = (newHeight - origHeight) / 2;

// Resize canvas
doc.resizeCanvas(newWidth, newHeight, AnchorPosition.MIDDLECENTER);
"""


def get_so_psb_name(app, so_layer) -> str:
    """Return the full fileReference path of a Smart Object layer.

    Uses ActionDescriptor to read the SO's embedded file path (absolute).
    The full path uniquely identifies the PSB even when multiple SOs
    in different directories share the same filename.
    """
    try:
        app.ActiveDocument.ActiveLayer = so_layer
        result = app.DoJavaScript(_JS_GET_SO_FILENAME)
        if result:
            return str(result).strip()
        return so_layer.Name
    except Exception:
        return so_layer.Name


def expand_so_canvas(app, so_doc, scale: float = 1.2) -> bool:
    """Expand the canvas of a Smart Object document to prevent text clipping.

    Args:
        scale: Expansion multiplier (e.g. 1.2 = 20% expansion on each side).
               Higher values are used when the new text is significantly larger.
    """
    try:
        app.DoJavaScript(_JS_EXPAND_SO_CANVAS.format(scale=scale))
        return True
    except Exception:
        return False


def pt_to_px(pt: float, dpi: float) -> float:
    return pt * (dpi / 72.0)


def px_to_pt(px: float, dpi: float) -> float:
    return px * (72.0 / dpi)
