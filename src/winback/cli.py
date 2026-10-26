"""One command: run the simulation and write the report."""

import argparse
import dataclasses
import os
from pathlib import Path

from winback.copywriter import openrouter, plumbing
from winback.run import run_simulation
from winback.settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="winback", description="Run the win-back simulation and write its report.")
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"), help="settings file (default: settings.toml)")
    parser.add_argument("--start", type=int, help="run only this starting number of merchants (default: both sizes in the settings file)")
    parser.add_argument("--seed", type=int, default=1, help="random seed; the same seed gives the same report")
    parser.add_argument("--replays", type=int, help="how many times to replay the weeks (default: the number in the settings file)")
    parser.add_argument("--out", type=Path, default=Path("reports/report.md"), help="where to write the report")
    parser.add_argument("--writer", choices=["stand-in", "ai"], default="stand-in", help="who writes the AI loop's words: the stand-in list, or the real writer and judge (needs OPENROUTER_API_KEY)")
    parser.add_argument("--plumbing", action="store_true", help="make one real write-and-judge round trip and print it (needs OPENROUTER_API_KEY)")
    args = parser.parse_args(argv)

    settings = load_settings(args.settings)
    if args.plumbing:
        print("\n".join(plumbing(settings, _key())))
        return
    if args.start is not None:
        settings = dataclasses.replace(settings, start_sizes=(args.start,))
    result = run_simulation(settings, args.seed, args.replays, openrouter(settings, _key()) if args.writer == "ai" else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(result.report)
    print(f"Report written to {args.out}")


def _key() -> str:
    """The OpenRouter key, from the environment; never from a file in the repository."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("Set OPENROUTER_API_KEY to use the AI writer.")
    return key


if __name__ == "__main__":
    main()
