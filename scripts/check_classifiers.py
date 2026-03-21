"""
Standalone script to verify trained classifiers.
Loads sklearn models and runs inference on a few rows from sample.csv
"""

import sys
import pickle
import numpy as np
import pandas as pd
from pathlib import Path
import json

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config.config import UNSW_FEATURE_CONFIG

def main():
    print("=== Checking NIDS Classifiers (sklearn models) ===")
    
    models_dir = REPO_ROOT / "models"
    binary_model_path = models_dir / "binary_model.pkl"
    multiclass_model_path = models_dir / "multiclass_model.pkl"
    scaler_path = models_dir / "scaler.pkl"
    mapping_path = models_dir / "unsw_label_mapping.json"
    sample_path = REPO_ROOT / "data" / "UNSW-NB15" / "sample.csv"
    
    missing = [
        p for p in (binary_model_path, multiclass_model_path, scaler_path, sample_path)
        if not p.exists()
    ]
    if missing:
        print("ERROR: Missing dependencies:")
        for p in missing:
            print(f"  - {p}")
        sys.exit(1)

    print("Loading scaler and models...")
    with open(binary_model_path, "rb") as f:
        binary_model = pickle.load(f)
    with open(multiclass_model_path, "rb") as f:
        multiclass_model = pickle.load(f)
    with open(scaler_path, "rb") as f:
        scaler = pickle.load(f)
        
    print(f"Binary model: {type(binary_model).__name__}")
    print(f"Multiclass model: {type(multiclass_model).__name__}")
    
    if mapping_path.exists():
        with open(mapping_path, "r") as f:
            mapping = json.load(f)
        reverse_mapping = mapping.get("reverse_mapping", {})
    else:
        reverse_mapping = {}
        
    print(f"Loading sample data from {sample_path}...")
    df = pd.read_csv(sample_path)
    
    features = UNSW_FEATURE_CONFIG["numeric_features"]
    
    # Fill missing columns with 0
    for f in features:
        if f not in df.columns:
            df[f] = 0.0
            
    X = df[features].fillna(0).replace([np.inf, -np.inf], 0).astype(float)
    X_scaled = scaler.transform(X)
    
    print("\nRunning Binary Inference...")
    bin_preds = binary_model.predict(X_scaled)
    bin_probas = binary_model.predict_proba(X_scaled)
    
    attack_indices = np.where(bin_preds == 1)[0]
    print(f"Found {len(attack_indices)} attacks out of {len(X)} rows.")
    
    if len(attack_indices) > 0:
        print("\nRunning Multiclass Inference on detected attacks...")
        X_attacks = X_scaled[attack_indices]
        mc_preds = multiclass_model.predict(X_attacks)
        mc_probas = multiclass_model.predict_proba(X_attacks)
        
        print("\nSample Output (First 5 detected attacks):")
        for i, idx in enumerate(attack_indices[:5]):
            bin_conf = bin_probas[idx][1]
            pred_id = mc_preds[i]
            mc_conf = mc_probas[i].max()
            predicted_type = reverse_mapping.get(str(pred_id), f"Unknown ({pred_id})")
            
            actual_label = df.iloc[idx].get("label", "N/A")
            actual_cat = df.iloc[idx].get("attack_cat", "N/A")
            
            print(f"Row {idx}:")
            print(f"  Actual:   Label={actual_label}, Category={actual_cat}")
            print(f"  Binary:   Prediction=1 (Attack), Confidence={bin_conf:.4f}")
            print(f"  Multi:    Prediction={predicted_type}, Confidence={mc_conf:.4f}")
            print()
    else:
        print("\nNo attacks detected, skipping Multiclass Inference.")

    print("\n✅ Classifier check complete!")

if __name__ == "__main__":
    main()
