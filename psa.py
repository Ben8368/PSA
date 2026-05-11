#!/usr/bin/env python3
from __future__ import annotations
import argparse
import datetime
import json
import os
import sys

from psa_models import TextLayerRecord
from psa_utils import get_app, get_active_doc, PSAError, PSNotRunningError, NoActiveDocumentError
from psa_scanner import scan_document
from psa_applier import apply_workorder
from psa_logger import PSALogger


def _make_log_path(psd_path: str) -> str:
    base = os.path.splitext(psd_path)[0]
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{base}_{ts}.log"


def _make_workorder_path(psd_path: str) -> str:
    base = os.path.splitext(psd_path)[0]
    return base + "_workorder.json"


def cmd_scan(args):
    app = get_app()

    if args.psd:
        psd_path = os.path.abspath(args.psd)
        try:
            doc = app.Open(psd_path)
            opened_here = True
        except Exception as e:
            print(f"ERROR: Failed to open '{psd_path}': {e}", file=sys.stderr)
            sys.exit(1)
    else:
        doc = get_active_doc(app)
        psd_path = doc.FullName
        opened_here = False

    log_path = _make_log_path(psd_path)
    logger = PSALogger(log_path)

    try:
        records = scan_document(app, doc, logger)

        output_path = args.output or _make_workorder_path(psd_path)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in records], f, ensure_ascii=False, indent=2)

        logger.log_info(f"Work order written: {output_path}")
        print(f"Scanned {len(records)} text layers.")
        print(f"Work order: {output_path}")
        print(f"Log: {log_path}")

    finally:
        logger.close()
        if opened_here:
            try:
                doc.Close(2)
            except Exception:
                pass


def cmd_apply(args):
    psd_path = os.path.abspath(args.psd)
    workorder_path = os.path.abspath(args.workorder)

    if not os.path.exists(psd_path):
        print(f"ERROR: PSD not found: {psd_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(workorder_path):
        print(f"ERROR: Work order not found: {workorder_path}", file=sys.stderr)
        sys.exit(1)

    with open(workorder_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    records = [TextLayerRecord.from_dict(d) for d in raw]

    enabled_count = sum(1 for r in records if r.enabled)
    log_path = _make_log_path(psd_path)
    logger = PSALogger(log_path)

    try:
        logger.log_workorder_import(workorder_path, len(records), enabled_count)

        app = get_app()
        auto_path = apply_workorder(app, psd_path, records, logger)

        if auto_path:
            print(f"Done. Auto document: {auto_path}")
        print(f"Log: {log_path}")
    finally:
        logger.close()


def cmd_run(args):
    psd_path = os.path.abspath(args.psd)
    workorder_path = os.path.abspath(args.workorder)

    if not os.path.exists(psd_path):
        print(f"ERROR: PSD not found: {psd_path}", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(workorder_path):
        print(f"ERROR: Work order not found: {workorder_path}", file=sys.stderr)
        sys.exit(1)

    with open(workorder_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    records = [TextLayerRecord.from_dict(d) for d in raw]

    enabled_count = sum(1 for r in records if r.enabled)
    log_path = _make_log_path(psd_path)
    logger = PSALogger(log_path)

    try:
        logger.log_workorder_import(workorder_path, len(records), enabled_count)

        app = get_app()

        # If no records have data from scan (no bounds_h_px), do a fresh scan
        needs_scan = any(r.bounds_h_px == 0.0 for r in records if r.enabled)
        if needs_scan:
            logger.log_info("bounds_h_px missing for some enabled layers — running scan first.")
            try:
                doc = app.Open(psd_path)
                fresh_records = scan_document(app, doc, logger)
                doc.Close(2)
                # Merge scan data into records
                scan_by_id = {r.layer_id: r for r in fresh_records}
                for r in records:
                    if r.layer_id in scan_by_id:
                        scanned = scan_by_id[r.layer_id]
                        r.bounds_h_px = scanned.bounds_h_px
                        r.dpi = scanned.dpi
                        r.size_pt = scanned.size_pt
                        r.size_px = scanned.size_px
                        r.auto_leading = scanned.auto_leading
                        r.leading_pt = scanned.leading_pt
                        r.leading_px = scanned.leading_px
                        r.so_layer_id = scanned.so_layer_id
                        r.so_layer_path = scanned.so_layer_path
                        r.so_psb_name = scanned.so_psb_name
            except Exception as e:
                logger.log_error("scan during run", e)

        auto_path = apply_workorder(app, psd_path, records, logger)

        if auto_path:
            print(f"Done. Auto document: {auto_path}")
        print(f"Log: {log_path}")
    finally:
        logger.close()


def main():
    parser = argparse.ArgumentParser(
        prog="psa",
        description="PSA — Photoshop COM Automation Tool",
    )
    sub = parser.add_subparsers(dest="command")

    scan_p = sub.add_parser("scan", help="Scan PSD text layers and export work order JSON")
    scan_p.add_argument("--psd", help="Path to PSD file (uses active doc if omitted)")
    scan_p.add_argument("--output", help="Output work order JSON path")

    apply_p = sub.add_parser("apply", help="Apply work order changes to PSD")
    apply_p.add_argument("--psd", required=True, help="Path to source PSD file")
    apply_p.add_argument("--workorder", required=True, help="Path to work order JSON")

    run_p = sub.add_parser("run", help="Scan and apply (if work order already has enabled entries)")
    run_p.add_argument("--psd", required=True, help="Path to source PSD file")
    run_p.add_argument("--workorder", required=True, help="Path to work order JSON")

    # Support legacy-style: python psa.py --psd X --workorder Y  (maps to run)
    if len(sys.argv) > 1 and sys.argv[1].startswith("--"):
        legacy_parser = argparse.ArgumentParser(add_help=False)
        legacy_parser.add_argument("--psd")
        legacy_parser.add_argument("--workorder")
        legacy_args, _ = legacy_parser.parse_known_args()
        if legacy_args.psd and legacy_args.workorder:
            sys.argv = [sys.argv[0], "run"] + sys.argv[1:]

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    try:
        if args.command == "scan":
            cmd_scan(args)
        elif args.command == "apply":
            cmd_apply(args)
        elif args.command == "run":
            cmd_run(args)
    except (PSNotRunningError, NoActiveDocumentError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except PSAError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
