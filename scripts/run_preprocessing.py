"""
CLI runner for the UNSW-NB15 preprocessing pipeline.

Wraps preprocess_unsw_nb15.py with argparse, validates the output schema
after saving, and prints a summary.

Usage:
    python scripts/run_preprocessing.py --dataset unsw --output data/preprocessed/
    python scripts/run_preprocessing.py  # uses defaults
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from preprocessing_utils import validate_schema

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURE_NAMES_PATH = REPO_ROOT / "unsw_feature_names.json"

SUPPORTED_DATASETS = ("unsw",)


def run_unsw(output_dir: Path) -> None:
    """Run the UNSW-NB15 preprocessing pipeline and validate output."""
    # Import and call the main pipeline from preprocess_unsw_nb15
    import importlib.util

    pipeline_path = Path(__file__).resolve().parent / "preprocess_unsw_nb15.py"
    spec = importlib.util.spec_from_file_location("preprocess_unsw_nb15", pipeline_path)
    module = importlib.util.module_from_spec(spec)

    # Override OUTPUT_DIR inside the module to the user-supplied path
    spec.loader.exec_module(module)
    # Re-run with the desired output dir if different from default
    if output_dir.resolve() != module.OUTPUT_DIR.resolve():
        module.OUTPUT_DIR = output_dir
        module.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        # Re-trigger main so it writes to the new path
        module.main()
    else:
        module.main()


def validate_outputs(output_dir: Path, feature_names: list) -> bool:
    """Load saved Parquet files and verify schema + basic stats."""
    train_path = output_dir / "unsw_train.parquet"
    test_path = output_dir / "unsw_test.parquet"

    ok = True
    for path in (train_path, test_path):
        if not path.exists():
            print(f"[validate] MISSING: {path}")
            ok = False
            continue

        df = pd.read_parquet(path)
        expected = feature_names + ["label"]
        schema_ok = validate_schema(df, expected)
        label_vals = sorted(df["label"].unique().tolist())

        print(f"\n[validate] {path.name}")
        print(f"  rows       : {len(df):,}")
        print(f"  columns    : {len(df.columns)}")
        print(f"  schema     : {'OK' if schema_ok else 'FAILED'}")
        print(f"  label vals : {label_vals}")
        print(f"  null count : {df.isnull().sum().sum()}")

        if not schema_ok:
            ok = False

    return ok


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the network intrusion dataset preprocessing pipeline."
    )
    parser.add_argument(
        "--dataset",
        choices=SUPPORTED_DATASETS,
        default="unsw",
        help="Which dataset to preprocess (default: unsw).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data" / "preprocessed",
        help="Output directory for Parquet files (default: data/preprocessed/).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir: Path = args.output.resolve()

    print(f"Dataset  : {args.dataset}")
    print(f"Output   : {output_dir}")
    print()

    if args.dataset == "unsw":
        run_unsw(output_dir)
    else:
        print(f"Unknown dataset: {args.dataset}")
        sys.exit(1)

    # --- Post-save validation ---
    print("\n" + "=" * 60)
    print("Post-save schema validation")
    print("=" * 60)

    with open(FEATURE_NAMES_PATH) as f:
        feature_names: list = json.load(f)

    all_ok = validate_outputs(output_dir, feature_names)

    if all_ok:
        print("\n✅ Validation passed — Parquet files are ready.")
    else:
        print("\n❌ Validation FAILED — check output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
