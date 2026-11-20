"""Local audit commands. Source cell values are never printed to the terminal."""

import argparse
import json
from pathlib import Path
import sys

from company_ai.data.ingestion import DataError, read_source
from company_ai.data.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 1 private CSV audit and preparation")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subcommands.add_parser("inspect", help="Show column profiles without printing source records")
    inspect_parser.add_argument("inputs", type=Path, nargs="+")
    prepare_parser = subcommands.add_parser("prepare", help="Preserve, normalize, group and audit local CSVs")
    prepare_parser.add_argument("inputs", type=Path, nargs="+")
    prepare_parser.add_argument("--output", type=Path, required=True, help="New private run directory; never overwritten")
    prepare_parser.add_argument("--mapping", type=Path, help="JSON object mapping logical field names to observed column names")
    prepare_parser.add_argument("--synthetic", action="store_true", help="Label all reports as synthetic fixture results")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            profiles = [read_source(path, index).profile for index, path in enumerate(args.inputs)]
            print(json.dumps({"sources": profiles}, ensure_ascii=False, indent=2))
        else:
            report = run_pipeline(args.inputs, args.output, args.mapping,
                                  "SYNTHETIC_FIXTURE" if args.synthetic else "SOURCE_DATA_UNVERIFIED")
            stats = report["global"]
            print(json.dumps({
                "data_kind": report["data_kind"], "records_preserved": stats["records"],
                "canonical_answer_groups": stats["canonical_answer_groups"],
                "quarantined_rows": stats["quarantined_rows"],
                "approved_answer_groups": stats["approved_answer_groups"],
                "output": str(args.output),
            }, indent=2))
    except (OSError, DataError) as exc:
        if isinstance(exc, DataError):
            print(f"Error: {exc}", file=sys.stderr)
        else:
            # Exception repr may contain private paths; display only a safe error class.
            print(f"Error: {type(exc).__name__}. Check input paths and output permissions.", file=sys.stderr)
        return 2
    return 0
