import argparse
import sys
import os
from mergemate.cli.analyze_cmd import run_analyze


def main():
    parser = argparse.ArgumentParser(
        prog="mergemate",
        description="Local Test Impact Analysis and Validation Planner for Maven projects",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- analyze subcommand ---
    analyze_p = subparsers.add_parser("analyze", help="Analyze impact without running Maven")
    analyze_p.add_argument("--source", default="HEAD", help="Source ref (default: HEAD)")
    analyze_p.add_argument("--target", required=False, help="Target ref (e.g. origin/premaster)")
    analyze_p.add_argument("--profiles", default="", help="Comma-separated Maven profiles")
    analyze_p.add_argument("--repo-dir", default=None, help="Repository directory (default: cwd)")
    analyze_p.add_argument("--json", action="store_true", help="Output JSON")

    # Stub subcommands (Phase 2+)
    for cmd in ("test", "compile", "verify"):
        p = subparsers.add_parser(cmd, help=f"Run {cmd} on affected modules")
        p.add_argument("--source", default="HEAD")
        p.add_argument("--target", required=False)
        p.add_argument("--profiles", default="")
        p.add_argument("--repo-dir", default=None)
        p.add_argument("--full", action="store_true", help="Force full build")

    args = parser.parse_args()

    if args.command == "analyze":
        run_analyze(args)
    else:
        print(f"Command '{args.command}' will be available in Phase 2.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
