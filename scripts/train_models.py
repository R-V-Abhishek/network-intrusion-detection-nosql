"""
Train UNSW-NB15 models using scikit-learn (avoids PySpark 4.1.1 save bug on Windows).

Uses the official Training and Testing Sets with headers (45 columns).
Saves models as pickle files that the pipeline runner can load.

Produces:
    models/binary_model.pkl     — GradientBoosting binary classifier
    models/multiclass_model.pkl — RandomForest multiclass classifier  
    models/scaler.pkl           — StandardScaler
    models/unsw_label_mapping.json
    models/unsw_training_results.json
"""

import json, os, sys, time, pickle
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score, classification_report
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config.config import UNSW_FEATURE_CONFIG

FEATURE_NAMES = UNSW_FEATURE_CONFIG["numeric_features"]


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    models_dir = os.path.join(root, "models")
    os.makedirs(models_dir, exist_ok=True)
    sets_dir = os.path.join(root, "data", "UNSW-NB15", "Training and Testing Sets")

    train_csv = os.path.join(sets_dir, "UNSW_NB15_training-set.csv")
    test_csv = os.path.join(sets_dir, "UNSW_NB15_testing-set.csv")
    for p in (train_csv, test_csv):
        if not os.path.exists(p):
            print(f"ERROR: {p} not found")
            sys.exit(1)

    # ── Load Data ─────────────────────────────────────────────────────────
    print("[Train] Loading data...")
    train_df = pd.read_csv(train_csv, low_memory=False)
    test_df = pd.read_csv(test_csv, low_memory=False)

    # Clean column names
    train_df.columns = [c.strip().lower() for c in train_df.columns]
    test_df.columns = [c.strip().lower() for c in test_df.columns]

    print(f"[Train] Train: {len(train_df):,} rows, Test: {len(test_df):,} rows")
    print(f"[Train] Columns: {list(train_df.columns)}")

    # Clean attack_cat
    train_df["attack_cat"] = train_df["attack_cat"].fillna("Normal").str.strip()
    train_df.loc[train_df["attack_cat"] == "", "attack_cat"] = "Normal"
    test_df["attack_cat"] = test_df["attack_cat"].fillna("Normal").str.strip()
    test_df.loc[test_df["attack_cat"] == "", "attack_cat"] = "Normal"

    # Ensure label is integer
    train_df["label"] = train_df["label"].astype(int)
    test_df["label"] = test_df["label"].astype(int)

    print(f"\n[Train] Label distribution:")
    print(f"  Train: {dict(train_df['label'].value_counts())}")
    print(f"  Test:  {dict(test_df['label'].value_counts())}")

    attack_dist = train_df[train_df["label"] == 1]["attack_cat"].value_counts()
    print(f"\n[Train] Attack categories ({len(attack_dist)}):")
    for cat, count in attack_dist.items():
        print(f"  {cat}: {count:,}")

    # ── Feature Preparation ───────────────────────────────────────────────
    print(f"\n[Train] Using {len(FEATURE_NAMES)} features: {FEATURE_NAMES[:5]}...")

    # Handle missing features
    for col in FEATURE_NAMES:
        if col not in train_df.columns:
            print(f"  [WARN] '{col}' not in data, filling with 0")
            train_df[col] = 0.0
            test_df[col] = 0.0

    X_train = train_df[FEATURE_NAMES].fillna(0).replace([np.inf, -np.inf], 0).astype(float)
    X_test = test_df[FEATURE_NAMES].fillna(0).replace([np.inf, -np.inf], 0).astype(float)
    y_train = train_df["label"].values
    y_test = test_df["label"].values

    # ── StandardScaler ────────────────────────────────────────────────────
    print("[Train] Fitting StandardScaler...")
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    scaler_path = os.path.join(models_dir, "scaler.pkl")
    with open(scaler_path, "wb") as f:
        pickle.dump(scaler, f)
    print(f"[Train] Scaler saved → {scaler_path}")

    # ══════════════════════════════════════════════════════════════════════
    # STAGE 1 — Binary Classification (GradientBoosting)
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("[Train] STAGE 1: Binary GradientBoosting Classifier")
    print("=" * 60)

    t0 = time.time()
    gbt = GradientBoostingClassifier(
        n_estimators=200, max_depth=5, learning_rate=0.1,
        subsample=0.8, random_state=42, verbose=1
    )
    gbt.fit(X_train_scaled, y_train)
    train_time = time.time() - t0
    print(f"[Train] Training took {train_time:.1f}s")

    y_pred = gbt.predict(X_test_scaled)
    y_proba = gbt.predict_proba(X_test_scaled)[:, 1]

    acc = accuracy_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred, average="binary")
    auc = roc_auc_score(y_test, y_proba)
    print(f"[Train] AUC:      {auc:.4f}")
    print(f"[Train] Accuracy: {acc:.4f}")
    print(f"[Train] F1:       {f1:.4f}")

    gbt_path = os.path.join(models_dir, "binary_model.pkl")
    with open(gbt_path, "wb") as f:
        pickle.dump(gbt, f)
    print(f"[Train] Binary model saved → {gbt_path}")

    # ══════════════════════════════════════════════════════════════════════
    # STAGE 2 — Multiclass Classification (RandomForest)
    # ══════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("[Train] STAGE 2: Multiclass RandomForest Classifier")
    print("=" * 60)

    # Build label mapping from attack_cat
    cats = sorted(train_df[train_df["label"] == 1]["attack_cat"].unique())
    cats = [c for c in cats if c and c != "Normal"]
    label_map = {name: i for i, name in enumerate(cats)}
    reverse_map = {i: name for i, name in enumerate(cats)}
    print(f"[Train] Categories ({len(cats)}): {cats}")

    # Filter attack rows only
    train_attacks = train_df[train_df["label"] == 1].copy()
    test_attacks = test_df[test_df["label"] == 1].copy()

    # Map attack_cat to integer labels
    train_attacks["attack_cat_id"] = train_attacks["attack_cat"].map(label_map)
    test_attacks["attack_cat_id"] = test_attacks["attack_cat"].map(label_map)

    # Drop rows with unmapped categories
    train_attacks = train_attacks.dropna(subset=["attack_cat_id"])
    test_attacks = test_attacks.dropna(subset=["attack_cat_id"])
    train_attacks["attack_cat_id"] = train_attacks["attack_cat_id"].astype(int)
    test_attacks["attack_cat_id"] = test_attacks["attack_cat_id"].astype(int)

    X_train_mc = scaler.transform(
        train_attacks[FEATURE_NAMES].fillna(0).replace([np.inf, -np.inf], 0).astype(float)
    )
    X_test_mc = scaler.transform(
        test_attacks[FEATURE_NAMES].fillna(0).replace([np.inf, -np.inf], 0).astype(float)
    )
    y_train_mc = train_attacks["attack_cat_id"].values
    y_test_mc = test_attacks["attack_cat_id"].values
    print(f"[Train] Attack train: {len(y_train_mc):,}, Attack test: {len(y_test_mc):,}")

    t0 = time.time()
    rf = RandomForestClassifier(
        n_estimators=200, max_depth=15, random_state=42, n_jobs=-1, verbose=1
    )
    rf.fit(X_train_mc, y_train_mc)
    mc_train_time = time.time() - t0
    print(f"[Train] Training took {mc_train_time:.1f}s")

    y_pred_mc = rf.predict(X_test_mc)
    mc_acc = accuracy_score(y_test_mc, y_pred_mc)
    mc_f1 = f1_score(y_test_mc, y_pred_mc, average="weighted")
    print(f"[Train] Accuracy:    {mc_acc:.4f}")
    print(f"[Train] Weighted F1: {mc_f1:.4f}")
    print(f"\n[Train] Classification Report:")
    print(classification_report(y_test_mc, y_pred_mc, target_names=cats))

    rf_path = os.path.join(models_dir, "multiclass_model.pkl")
    with open(rf_path, "wb") as f:
        pickle.dump(rf, f)
    print(f"[Train] Multiclass model saved → {rf_path}")

    # ── Save Label Mapping ────────────────────────────────────────────────
    mapping_path = os.path.join(models_dir, "unsw_label_mapping.json")
    with open(mapping_path, "w") as f:
        json.dump({
            "attack_mapping": label_map,
            "reverse_mapping": {str(k): v for k, v in reverse_map.items()},
        }, f, indent=2)
    print(f"[Train] Label mapping saved → {mapping_path}")

    # ── Save Training Results ─────────────────────────────────────────────
    results_path = os.path.join(models_dir, "unsw_training_results.json")
    with open(results_path, "w") as f:
        json.dump({
            "dataset": {
                "train_csv": "UNSW_NB15_training-set.csv",
                "test_csv": "UNSW_NB15_testing-set.csv",
                "train_rows": len(train_df),
                "test_rows": len(test_df),
            },
            "binary": {
                "model": "GradientBoostingClassifier",
                "auc": round(auc, 4),
                "accuracy": round(acc, 4),
                "f1": round(f1, 4),
            },
            "multiclass": {
                "model": "RandomForestClassifier",
                "categories": cats,
                "num_categories": len(cats),
                "accuracy": round(mc_acc, 4),
                "weighted_f1": round(mc_f1, 4),
            },
        }, f, indent=2)
    print(f"[Train] Results saved → {results_path}")

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("[Train] TRAINING COMPLETE")
    print("=" * 60)
    print(f"  Data    — {len(train_df):,} train + {len(test_df):,} test")
    print(f"  Binary  — AUC: {auc:.4f}  Acc: {acc:.4f}  F1: {f1:.4f}")
    print(f"  Multi   — Acc: {mc_acc:.4f}  F1: {mc_f1:.4f}  ({len(cats)} categories)")
    print(f"  Models  → {models_dir}")
    print("=" * 60)


if __name__ == "__main__":
    main()
