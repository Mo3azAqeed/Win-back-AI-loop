"""One command: run the simulation and write the report."""

import argparse
import dataclasses
from pathlib import Path

from winback.run import run_simulation
from winback.settings import load_settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="winback", description="Run the win-back simulation and write its report.")
    parser.add_argument("--settings", type=Path, default=Path("settings.toml"), help="settings file (default: settings.toml)")
    parser.add_argument("--start", type=int, help="run only this starting number of merchants (default: both sizes in the settings file)")
    parser.add_argument("--seed", type=int, default=1, help="random seed; the same seed gives the same report")
    parser.add_argument("--replays", type=int, help="how many times to replay the weeks (default: the number in the settings file)")
    parser.add_argument("--out", type=Path, default=Path("reports/report.md"), help="where to write the report")
    args = parser.parse_args(argv)

    settings = load_settings(args.settings)
    if args.start is not None:
        settings = dataclasses.replace(settings, start_sizes=(args.start,))
    result = run_simulation(settings, args.seed, args.replays)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(result.report)
    print(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
