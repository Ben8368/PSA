from __future__ import annotations
import datetime
import os
import sys


class PSALogger:
    def __init__(self, log_path: str):
        self._path = log_path
        self.log_path = log_path
        self._fh = open(log_path, "w", encoding="utf-8")
        self.iteration_buffer: list[str] = []

    def _ts(self) -> str:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _write(self, line: str, indent: int = 0):
        prefix = "  " * indent
        full = f"[{self._ts()}] {prefix}{line}" if indent == 0 else f"  {prefix}{line}"
        self._fh.write(full + "\n")
        self._fh.flush()
        print(full)

    def log_info(self, msg: str):
        self._write(f"INFO: {msg}")

    def log_warning(self, msg: str):
        self._write(f"WARN: {msg}")

    def log_error(self, context: str, exc: Exception):
        self._write(f"ERROR [{context}]: {exc}")

    def log_workorder_import(self, json_path: str, total: int, enabled: int):
        self._write(f"WORKORDER: Loaded {json_path} — {total} layers total, {enabled} enabled")

    def log_scan_start(self, doc_name: str, doc_path: str, dpi: float):
        self._write(f"SCAN START: doc={doc_name} path={doc_path} dpi={dpi}")

    def log_scan_layer(self, record):
        self._write(
            f"SCAN: [{record.layer_path}] font={record.font} "
            f"size_pt={record.size_pt:.2f} size_px={record.size_px:.2f} "
            f"tracking={record.tracking} auto_leading={record.auto_leading} "
            f"leading_pt={record.leading_pt:.2f} bounds_h={record.bounds_h_px:.2f}px "
            f"dpi={record.dpi}"
        )

    def log_scan_complete(self, count: int):
        self._write(f"SCAN COMPLETE: {count} text layers found")

    def log_apply_start(self, layer_path: str, target_h: float, font_resolved: str):
        self._write(
            f"APPLY: [{layer_path}] target_h={target_h:.2f}px font_resolved={font_resolved}"
        )
        self.iteration_buffer = []

    def log_iteration(
        self,
        iteration: int,
        kind: str,
        tried_value: float,
        result_h: float,
        target_h: float,
        extra: str = "",
    ):
        converged = abs(result_h - target_h) < 1.0
        tag = " CONVERGED" if converged else ""
        msg = (
            f"[iter {iteration:02d} {kind}] tried={tried_value:.4f} → h={result_h:.2f}px"
            f"  target={target_h:.2f}px{tag}{' ' + extra if extra else ''}"
        )
        self.iteration_buffer.append(msg)
        self._write(msg, indent=1)

    def log_apply_result(self, layer_path: str, params, record):
        converged_mark = "OK" if params.converged else "!!"
        self._write(
            f"RESULT [{layer_path}]: {converged_mark} "
            f"font={params.font_ps} size_pt={params.size_pt:.4f} "
            f"size_px={params.size_px:.4f} "
            f"auto_leading={params.auto_leading} leading_pt={params.leading_pt:.4f} "
            f"tracking={params.tracking} "
            f"final_h={params.final_bounds_h_px:.2f}px target_h={params.target_h_px:.2f}px"
        )

    def log_layer_before(self, record):
        self._write(
            f"BEFORE [{record.layer_path}]: text={repr(record.text)} "
            f"font={record.font} size_pt={record.size_pt:.4f} size_px={record.size_px:.4f} "
            f"tracking={record.tracking} auto_leading={record.auto_leading} "
            f"leading_pt={record.leading_pt:.4f} bounds_h={record.bounds_h_px:.2f}px"
        )

    def log_layer_after(self, record, params):
        converged = "OK" if params.converged else "!!"
        self._write(
            f"AFTER  [{record.layer_path}] [{converged}]: text={repr(record.new_text)} "
            f"font={params.font_ps} size_pt={params.size_pt:.4f} size_px={params.size_px:.4f} "
            f"tracking={params.tracking} auto_leading={params.auto_leading} "
            f"leading_pt={params.leading_pt:.4f} final_h={params.final_bounds_h_px:.2f}px"
        )

    def log_copy_created(self, src: str, dst: str):
        self._write(f"COPY: {src} → {dst}")

    def close(self):
        try:
            self._fh.close()
        except Exception:
            pass
