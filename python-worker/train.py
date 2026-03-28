"""
train.py — One-shot training script for the Tox21 toxicity pipeline.

Usage:
    python train.py --csv /path/to/tox21.csv [--out toxicity_model.pkl]

This mirrors the full training flow from tox_model.ipynb (cells 0–27, 41).
Run this once to produce toxicity_model.pkl, then start worker.py.
"""

from __future__ import annotations

import argparse
import pickle
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# Import feature helpers from our inference module
from model import (
    smiles_to_features,
    ALL_COLUMNS,
    NUM_CONTINUOUS_FEATURES,
)

NUM_FEATURES = NUM_CONTINUOUS_FEATURES  # 13 continuous features before FP


def load_dataset(csv_path: str):
    log.info(f"Loading dataset from {csv_path}")
    df = pd.read_csv(csv_path)
    log.info(f"Dataset shape: {df.shape}")
    return df


def build_features(df: pd.DataFrame):
    log.info("Extracting molecular features (this may take a while)…")
    features_list = []
    valid_indices = []

    for i, smi in enumerate(tqdm(df["smiles"], desc="SMILES→features")):
        feat = smiles_to_features(smi)
        if feat is not None:
            features_list.append(feat)
            valid_indices.append(i)

    X = np.array(features_list)
    df = df.iloc[valid_indices].reset_index(drop=True)
    log.info(f"Feature matrix shape: {X.shape} ({len(valid_indices)} valid molecules)")
    return X, df


def preprocess(X: np.ndarray):
    from sklearn.preprocessing import StandardScaler
    from sklearn.feature_selection import VarianceThreshold

    X_df = pd.DataFrame(X, columns=ALL_COLUMNS)

    # Split continuous and binary (fingerprint) parts
    X_cont = X_df.iloc[:, :NUM_FEATURES]
    X_bin  = X_df.iloc[:, NUM_FEATURES:]

    # Scale continuous features
    scaler = StandardScaler()
    X_cont_scaled = scaler.fit_transform(X_cont)

    # Recombine and rebuild DataFrame for selector
    X_combined = np.hstack([X_cont_scaled, X_bin.values])
    X_combined_df = pd.DataFrame(X_combined, columns=ALL_COLUMNS)

    # Variance threshold feature selection
    selector = VarianceThreshold(threshold=0.01)
    X_selected = selector.fit_transform(X_combined_df)
    selected_columns = X_combined_df.columns[selector.get_support()]

    log.info(f"After variance filter: {X_selected.shape}")
    X_selected_df = pd.DataFrame(X_selected, columns=selected_columns)

    return scaler, selector, X_selected_df, selected_columns


def train_models(X_selected_df: pd.DataFrame, y: pd.DataFrame, labels: list[str]):
    from lightgbm import LGBMClassifier
    from xgboost import XGBClassifier
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import roc_auc_score

    lgb_models = {}
    xgb_models = {}

    for label in labels:
        log.info(f"Training LightGBM for: {label}")
        mask      = y[label].notna()
        X_label   = X_selected_df[mask]
        y_label   = y.loc[mask, label]

        X_train, X_test, y_train, y_test = train_test_split(
            X_label, y_label, test_size=0.2, random_state=42, stratify=y_label
        )
        pos = sum(y_label)
        neg = len(y_label) - pos
        scale_pos = neg / pos if pos > 0 else 1.0

        lgb = LGBMClassifier(
            n_estimators=500,
            learning_rate=0.03,
            max_depth=-1,
            min_child_samples=20,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos,
            random_state=42,
            verbose=-1,
        )
        lgb.fit(X_train, y_train)
        auc = roc_auc_score(y_test, lgb.predict_proba(X_test)[:, 1])
        log.info(f"  LightGBM AUC ({label}): {auc:.4f}")
        lgb_models[label] = lgb

        log.info(f"Training XGBoost for: {label}")
        xgb = XGBClassifier(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=5,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos,
            eval_metric="logloss",
            random_state=42,
            verbosity=0,
        )
        xgb.fit(X_train, y_train)
        auc = roc_auc_score(y_test, xgb.predict_proba(X_test)[:, 1])
        log.info(f"  XGBoost   AUC ({label}): {auc:.4f}")
        xgb_models[label] = xgb

    return lgb_models, xgb_models


def save_pipeline(path: str, lgb_models, xgb_models, scaler, selector,
                  selected_columns, labels):
    pipeline = {
        "models":           lgb_models,
        "xgb_models":      xgb_models,
        "scaler":          scaler,
        "selector":        selector,
        "selected_columns": selected_columns,
        "all_columns":     ALL_COLUMNS,
        "num_features":    NUM_FEATURES,
        "labels":          labels,
    }
    with open(path, "wb") as f:
        pickle.dump(pipeline, f)
    size_mb = Path(path).stat().st_size / 1e6
    log.info(f"✅ Pipeline saved to {path} ({size_mb:.1f} MB)")


def main():
    parser = argparse.ArgumentParser(description="Train Tox21 toxicity models")
    parser.add_argument("--csv", required=True, help="Path to tox21.csv")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).parent / "toxicity_model.pkl"),
        help="Output pickle path (default: toxicity_model.pkl next to this script)",
    )
    args = parser.parse_args()

    # 1. Load
    df = load_dataset(args.csv)

    # 2. Separate labels
    label_cols = [c for c in df.columns if c not in ("smiles", "mol_id")]
    y = df[label_cols].copy()

    # 3. Feature extraction
    X, df = build_features(df)
    y = y.iloc[df.index].reset_index(drop=True) if hasattr(df, "index") else y

    # 4. Preprocess
    scaler, selector, X_selected_df, selected_columns = preprocess(X)

    # 5. Labels
    labels = y.columns.tolist()
    log.info(f"Tox21 labels: {labels}")

    # 6. Train
    lgb_models, xgb_models = train_models(X_selected_df, y, labels)

    # 7. Save
    save_pipeline(args.out, lgb_models, xgb_models, scaler, selector,
                  selected_columns, labels)


if __name__ == "__main__":
    main()
