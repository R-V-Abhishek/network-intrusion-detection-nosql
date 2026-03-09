"""
Preprocessing utilities for UNSW-NB15 pipeline.

Shared by preprocess_unsw_nb15.py (Person 1) and the training notebooks (Person 2).
All functions operate on pandas DataFrames.
"""

from typing import Tuple

import pandas as pd
from sklearn.model_selection import train_test_split


def clip_outliers(df: pd.DataFrame, cols: list, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    """
    Clip numeric columns to [lower, upper] quantile range to remove extreme outliers.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame.
    cols : list
        List of column names to clip.
    lower : float
        Lower quantile threshold (default 0.01).
    upper : float
        Upper quantile threshold (default 0.99).

    Returns
    -------
    pd.DataFrame
        DataFrame with clipped values (original df is not mutated).
    """
    df = df.copy()
    for col in cols:
        if col in df.columns:
            low_val = df[col].quantile(lower)
            high_val = df[col].quantile(upper)
            df[col] = df[col].clip(lower=low_val, upper=high_val)
    return df


def encode_labels(df: pd.DataFrame, col: str) -> Tuple[pd.DataFrame, dict]:
    """
    Encode a categorical column to integer labels using a deterministic alphabetical mapping.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame.
    col : str
        Name of the column to encode.

    Returns
    -------
    Tuple[pd.DataFrame, dict]
        DataFrame with the column replaced by integer codes, and the mapping dict {str -> int}.
    """
    df = df.copy()
    categories = sorted(df[col].dropna().unique().tolist())
    mapping = {cat: idx for idx, cat in enumerate(categories)}
    df[col] = df[col].map(mapping)
    return df, mapping


def validate_schema(df: pd.DataFrame, expected_cols: list) -> bool:
    """
    Verify that all expected columns are present in the DataFrame.

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame to validate.
    expected_cols : list
        List of column names that must be present.

    Returns
    -------
    bool
        True if all expected columns are present, False otherwise.
        Prints the names of any missing columns.
    """
    missing = [col for col in expected_cols if col not in df.columns]
    if missing:
        print(f"[validate_schema] MISSING columns ({len(missing)}): {missing}")
        return False
    return True


def split_train_test(
    df: pd.DataFrame,
    test_size: float = 0.2,
    stratify_col: str = "label",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split DataFrame into stratified train and test sets.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame.
    test_size : float
        Fraction of data to reserve for the test set (default 0.2).
    stratify_col : str
        Column to use for stratified splitting (default 'label').

    Returns
    -------
    Tuple[pd.DataFrame, pd.DataFrame]
        (train_df, test_df)
    """
    stratify = df[stratify_col] if stratify_col in df.columns else None
    train_df, test_df = train_test_split(
        df,
        test_size=test_size,
        random_state=42,
        stratify=stratify,
    )
    return train_df.reset_index(drop=True), test_df.reset_index(drop=True)
