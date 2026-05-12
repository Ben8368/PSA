from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class TextLayerRecord:
    layer_id: int
    layer_name: str
    layer_path: str

    in_smart_object: bool
    so_layer_id: int | None
    so_layer_path: str | None
    so_psb_name: str | None

    text: str
    font: str
    size_pt: float
    size_px: float
    tracking: float
    auto_leading: bool
    leading_pt: float
    leading_px: float

    bounds_left: float
    bounds_top: float
    bounds_right: float
    bounds_bottom: float
    bounds_h_px: float

    dpi: float

    faux_bold: bool = False
    faux_italic: bool = False
    justification: str = ""
    capitalization: str = ""
    anti_alias: str = ""
    auto_leading_amount: float = 0.0
    color_r: float = 0.0
    color_g: float = 0.0
    color_b: float = 0.0

    new_text: str | None = None
    new_font_family: str | None = None
    new_font_weight: str | None = None
    new_font_ps: str | None = None
    enabled: bool = False
    so_chain: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "layer_path": self.layer_path,
            "in_smart_object": self.in_smart_object,
            "so_layer_id": self.so_layer_id,
            "so_layer_path": self.so_layer_path,
            "so_psb_name": self.so_psb_name,
            "so_chain": self.so_chain,
            "text": self.text,
            "font": self.font,
            "size_pt": round(self.size_pt, 4),
            "size_px": round(self.size_px, 4),
            "tracking": self.tracking,
            "auto_leading": self.auto_leading,
            "leading_pt": round(self.leading_pt, 4),
            "leading_px": round(self.leading_px, 4),
            "bounds_left": round(self.bounds_left, 2),
            "bounds_top": round(self.bounds_top, 2),
            "bounds_right": round(self.bounds_right, 2),
            "bounds_bottom": round(self.bounds_bottom, 2),
            "bounds_h_px": round(self.bounds_h_px, 2),
            "dpi": self.dpi,
            "faux_bold": self.faux_bold,
            "faux_italic": self.faux_italic,
            "justification": self.justification,
            "capitalization": self.capitalization,
            "anti_alias": self.anti_alias,
            "auto_leading_amount": self.auto_leading_amount,
            "color_r": self.color_r,
            "color_g": self.color_g,
            "color_b": self.color_b,
            "enabled": self.enabled,
            "new_text": self.new_text,
            "new_font_family": self.new_font_family,
            "new_font_weight": self.new_font_weight,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TextLayerRecord":
        return cls(
            layer_id=d["layer_id"],
            layer_name=d["layer_name"],
            layer_path=d["layer_path"],
            in_smart_object=d["in_smart_object"],
            so_layer_id=d.get("so_layer_id"),
            so_layer_path=d.get("so_layer_path"),
            so_psb_name=d.get("so_psb_name"),
            text=d["text"],
            font=d["font"],
            size_pt=d["size_pt"],
            size_px=d["size_px"],
            tracking=d.get("tracking", 0.0),
            auto_leading=d.get("auto_leading", True),
            leading_pt=d.get("leading_pt", 0.0),
            leading_px=d.get("leading_px", 0.0),
            bounds_left=d.get("bounds_left", 0.0),
            bounds_top=d.get("bounds_top", 0.0),
            bounds_right=d.get("bounds_right", 0.0),
            bounds_bottom=d.get("bounds_bottom", 0.0),
            bounds_h_px=d.get("bounds_h_px", 0.0),
            dpi=d.get("dpi", 72.0),
            faux_bold=d.get("faux_bold", False),
            faux_italic=d.get("faux_italic", False),
            justification=d.get("justification", ""),
            capitalization=d.get("capitalization", ""),
            anti_alias=d.get("anti_alias", ""),
            auto_leading_amount=d.get("auto_leading_amount", 0.0),
            color_r=d.get("color_r", 0.0),
            color_g=d.get("color_g", 0.0),
            color_b=d.get("color_b", 0.0),
            new_text=d.get("new_text"),
            new_font_family=d.get("new_font_family"),
            new_font_weight=d.get("new_font_weight"),
            new_font_ps=d.get("new_font_ps"),
            enabled=d.get("enabled", False),
            so_chain=d.get("so_chain", []),
        )


@dataclass
class AdaptedParams:
    font_ps: str
    size_pt: float
    size_px: float
    auto_leading: bool
    leading_pt: float
    leading_px: float
    tracking: float
    final_bounds_h_px: float
    target_h_px: float
    converged: bool
    iterations_log: list[str] = field(default_factory=list)
