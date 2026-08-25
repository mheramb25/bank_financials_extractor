"""CLI entry point.

    python -m arx.run --pdfs ./input_pdfs \
                      --template ./FinancialData_Verified_1.xlsx \
                      --out ./FinancialData_Filled.xlsx

Exit codes: 0 = every PDF processed; 1 = at least one PDF failed (the rest were
still written); 2 = nothing to do / bad arguments.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from arx import load_config, setup_logging
from arx.excel_writer import build_blank_template
from arx.pipeline import discover_pdfs, run_batch

log = logging.getLogger("arx.run")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m arx.run",
        description=(
            "Extract metrics from Indian bank / NBFC annual report PDFs into an "
            "existing Excel template, fully offline, with a confidence and audit "
            "layer. A wrong number is worse than a missing number."
        ),
    )
    p.add_argument(
        "--pdfs",
        required=False,
        help="folder of annual report PDFs (or a single .pdf file)",
    )
    p.add_argument(
        "--template",
        required=True,
        help="the Excel template to fill (never modified; a copy is written)",
    )
    p.add_argument("--out", required=True, help="output .xlsx path")
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        help="parallel PDF workers (default: runtime.workers in config.yaml)",
    )
    p.add_argument(
        "--no-cache",
        action="store_true",
        help="ignore the parse cache and re-read every PDF from scratch",
    )
    p.add_argument(
        "--init-template",
        action="store_true",
        help="create a blank template at --template if it does not exist, then exit",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    p.add_argument("--quiet", "-q", action="store_true", help="no progress bars")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    cfg = load_config()

    template = Path(args.template)
    if args.init_template:
        if template.exists():
            log.info("template already exists: %s", template)
        else:
            build_blank_template(template)
            log.info("created blank template: %s", template)
        return 0

    if not template.exists():
        log.error(
            "template not found: %s (run with --init-template to create a blank one)",
            template,
        )
        return 2

    pdfs = []
    src = Path(args.pdfs) if args.pdfs else None
    if src is not None:
        if src.is_file() and src.suffix.lower() == ".pdf":
            pdfs = [src]
        elif src.is_dir():
            pdfs = discover_pdfs(src, recursive=True)
        else:
            log.error("--pdfs must be a folder or a .pdf file: %s", src)
            return 2
    else:
        # Auto mode: discover PDFs from the most common roots in this workspace.
        roots = [Path("./input_pdfs"), Path("./reports"), Path(".")]
        seen = set()
        for root in roots:
            for pdf in discover_pdfs(root, recursive=True):
                key = str(pdf.resolve())
                if key in seen:
                    continue
                seen.add(key)
                pdfs.append(pdf)

    if not pdfs:
        if src is not None:
            log.error("no PDFs found in %s", src)
        else:
            log.error("no PDFs found in auto-discovery roots: ./input_pdfs, ./reports, .")
        return 2

    workers = args.workers if args.workers is not None else int(cfg["runtime"]["workers"])
    log.info("processing %d PDF(s) with %d worker(s)", len(pdfs), workers)

    written, results, failures = run_batch(
        pdfs=pdfs,
        template=template,
        out_path=Path(args.out),
        workers=workers,
        cfg=cfg,
        use_cache=not args.no_cache,
        progress=not args.quiet,
    )

    print()
    print(f"Workbook written: {written}")
    print(f"Audit JSON:       {cfg['runtime']['audit_dir']}/")
    for r in sorted(results, key=lambda r: (r.fiscal_year, r.institution)):
        filled = sum(1 for c in r.cells if c.is_written_number)
        nd = sum(1 for c in r.cells if c.sentinel == "ND")
        na = sum(1 for c in r.cells if c.sentinel == "NA")
        mean_conf = (
            sum(c.confidence for c in r.cells if c.is_written_number) / filled
            if filled
            else 0.0
        )
        print(
            f"  {r.institution:<45s} {r.fiscal_year}  "
            f"filled {filled:>2d}  ND {nd:>2d}  NA {na:>2d}  mean conf {mean_conf:5.1f}"
        )

    if failures:
        print(f"\n{len(failures)} PDF(s) FAILED:")
        for f in failures:
            print(f"  {Path(f['path']).name}: {f['error']}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
