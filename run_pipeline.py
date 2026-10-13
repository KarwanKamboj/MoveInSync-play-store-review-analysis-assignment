"""
Master CLI Entrypoint for MoveInSync Google Play Store Ratings Analysis Pipeline.

Usage:
  python run_pipeline.py --serve     # Launches the interactive Play Store Rating Intelligence & Report Generation web app
  python run_pipeline.py --analyze   # Re-runs preprocessing, classification, prioritization, & charts from saved raw data
  python run_pipeline.py --collect   # Fetches fresh public reviews & store metadata from Google Play
  python run_pipeline.py --all       # Runs full end-to-end collection + analysis + visualization
"""

import argparse
from pathlib import Path

from src.analyze_and_prioritize import run_analysis_and_prioritization
from src.collect import run_collection
from src.preprocess_and_classify import run_preprocessing_and_classification
from src.visualize import generate_all_charts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MoveInSync (com.moveinsync.ets) Google Play Store Review Analysis Pipeline & Dynamic Web System"
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Launch the dynamic Play Store Rating Intelligence & Report Generation web app (http://localhost:8000)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="HTTP port when running with --serve (default: 8000)",
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help="Fetch fresh reviews and metadata from Google Play Store into data/raw/",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Run preprocessing, windowing, classification, prioritization, and chart generation",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Execute both --collect and --analyze end-to-end",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent

    if args.serve:
        from app import run_server
        run_server(port=args.port)
        return

    if not (args.collect or args.analyze or args.all):
        # Default to --analyze if raw data already exists, otherwise --all
        if (base_dir / "data" / "raw" / "reviews_raw_latest.jsonl").exists():
            args.analyze = True
        else:
            args.all = True

    if args.collect or args.all:
        run_collection(base_dir)

    if args.analyze or args.all:
        run_preprocessing_and_classification(base_dir)
        run_analysis_and_prioritization(base_dir)
        generate_all_charts(base_dir)


if __name__ == "__main__":
    main()

