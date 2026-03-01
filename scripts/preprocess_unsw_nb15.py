"""
Preprocessing pipeline for UNSW-NB15 dataset.

Loads all raw UNSW-NB15 CSVs, validates schema, handles nulls,
clips outliers, splits into train/test, and saves as Parquet.

Usage:
    python scripts/preprocess_unsw_nb15.py
"""

import json
import os
import sys
from pathlib import Path

import pandas as pd

# Allow imports from src/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from preprocessing_utils import (
    clip_outliers,
    split_train_test,
    validate_schema,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "UNSW-NB15"
OUTPUT_DIR = REPO_ROOT / "data" / "preprocessed"
FEATURE_NAMES_PATH = REPO_ROOT / "unsw_feature_names.json"

# Columns owned by Person 2 or not used as model features
DROP_COLS = ["id", "attack_cat"]


def load_unsw_csvs(data_dir: Path) -> pd.DataFrame:
    """Load and concatenate all UNSW-NB15 raw CSV files."""
    csv_files = sorted(data_dir.glob("UNSW_NB15_*.csv"))
    if not csv_files:
        # Fall back to numbered raw files
        csv_files = sorted(data_dir.glob("UNSW-NB15_[0-9].csv"))
    if not csv_files:
        raise FileNotFoundError(f"No UNSW-NB15 CSV files found in {data_dir}")

    dfs = []
    for f in csv_files:
        print(f"  Loading {f.name} ...")
        df = pd.read_csv(f, low_memory=False)
        dfs.append(df)

    combined = pd.concat(dfs, ignore_index=True)
    print(f"  Combined shape: {combined.shape}")
    return combined


def handle_nulls(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop rows where >50% of columns are null.
    Fill remaining numeric nulls with column median.
    """
    threshold = len(df.columns) * 0.5
    before = len(df)
    df = df.dropna(thresh=int(threshold))
    dropped = before - len(df)
    if dropped:
        print(f"  Dropped {dropped} rows with >50% nulls")

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
    return df


def main():
    print("=" * 60)
    print("UNSW-NB15 Preprocessing Pipeline")
    print("=" * 60)

    # 1. Load feature names
    with open(FEATURE_NAMES_PATH) as f:
        feature_names: list = json.load(f)
    print(f"\n[1] Feature names loaded: {len(feature_names)} features")

    # 2. Load raw CSVs
    print("\n[2] Loading raw UNSW-NB15 CSVs...")
    df = load_unsw_csvs(DATA_DIR)

    # Normalise column names to lowercase to match feature_names
    df.columns = [c.strip().lower() for c in df.columns]

    # 3. Drop unwanted columns (case-insensitive)
    cols_to_drop = [c for c in DROP_COLS if c.lower() in df.columns]
    df = df.drop(columns=cols_to_drop)
    print(f"\n[3] Dropped columns: {cols_to_drop}")

    # 4. Validate schema
    print("\n[4] Validating schema...")
    if not validate_schema(df, feature_names + ["label"]):
        print("  Schema validation FAILED — check column names.")
        sys.exit(1)
    print("  Schema OK")

    # 5. Handle nulls
    print("\n[5] Handling nulls...")
    df = handle_nulls(df)

    # 6. Clip outliers on numeric feature columns
    print("\n[6] Clipping outliers...")
    numeric_feature_cols = [
        c for c in feature_names if c in df.select_dtypes(include="number").columns
    ]
    df = clip_outliers(df, numeric_feature_cols)
    print(f"  Clipped {len(numeric_feature_cols)} numeric columns")

    # 7. Split train / test
    print("\n[7] Splitting train/test (80/20, stratified on 'label')...")
    train_df, test_df = split_train_test(df, test_size=0.2, stratify_col="label")
    print(f"  Train rows: {len(train_df)}")
    print(f"  Test rows:  {len(test_df)}")

    # 8. Save as Parquet
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    train_path = OUTPUT_DIR / "unsw_train.parquet"
    test_path = OUTPUT_DIR / "unsw_test.parquet"
    train_df.to_parquet(train_path, index=False)
    test_df.to_parquet(test_path, index=False)
    print(f"\n[8] Saved:")
    print(f"  {train_path}")
    print(f"  {test_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
