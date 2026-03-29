"""
model.py — Tox21 inference module based on new notebook logic
"""

from __future__ import annotations

import pickle
import logging
import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors, DataStructs, Draw, QED
from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator

log = logging.getLogger(__name__)

MORGAN_RADIUS = 2
MORGAN_FP_SIZE = 256

_morgan_gen = GetMorganGenerator(radius=MORGAN_RADIUS, fpSize=MORGAN_FP_SIZE)

# ── Pipeline I/O ──────────────────────────────────────────────────────────────

def load_pipeline(path: str) -> dict:
    with open(path, "rb") as f:
        pipeline = pickle.load(f)
    log.info(f"✅ Loaded toxicity pipeline from {path}")
    return pipeline

# ── Feature extraction ────────────────────────────────────────────────────────

def featurize(smiles: str, pipeline: dict) -> np.ndarray | None:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None

    descriptor_cols = pipeline.get("descriptor_cols", [])
    
    desc = []
    for col in descriptor_cols:
        try:
            val = getattr(Descriptors, col)(mol)
            if val is None or np.isnan(val) or np.isinf(val):
                val = 0.0
        except Exception:
            val = 0.0
        desc.append(val)

    fp = _morgan_gen.GetFingerprint(mol)
    fp_array = np.zeros((MORGAN_FP_SIZE,))
    DataStructs.ConvertToNumpyArray(fp, fp_array)

    feat = np.concatenate([desc, fp_array])
    feat = np.nan_to_num(feat)

    return feat

def ensemble_proba(X_input, pipeline: dict):
    xgb = pipeline["xgb"]
    lgb = pipeline["lgb"]
    cat = pipeline["cat"]
    return (
        0.4 * xgb.predict_proba(X_input) +
        0.3 * lgb.predict_proba(X_input) +
        0.3 * cat.predict_proba(X_input)
    )

# ── Inference ─────────────────────────────────────────────────────────────────

def predict_toxicity(smiles: str, pipeline: dict) -> dict:
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")

    scaler = pipeline["scaler"]
    selector = pipeline["selector"]
    selected_features = pipeline["selected_features"]
    descriptor_cols = pipeline["descriptor_cols"]

    # features
    feat = featurize(smiles, pipeline)
    if feat is None:
        raise ValueError(f"Invalid SMILES (could not featurize): {smiles!r}")
        
    feature_names = list(descriptor_cols) + [f"fp_{i}" for i in range(MORGAN_FP_SIZE)]
    feat_df_raw = pd.DataFrame([feat], columns=feature_names)

    feat_scaled = scaler.transform(feat_df_raw)
    feat_selected = selector.transform(pd.DataFrame(feat_scaled, columns=feature_names))
    feat_df = pd.DataFrame(feat_selected, columns=selected_features)
    
    # predictions
    probs = ensemble_proba(feat_df, pipeline)[0]
    pred = int(np.argmax(probs))
    confidence = float(np.max(probs))

    # properties
    mol_wt = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    h_donors = Descriptors.NumHDonors(mol)
    qed_score = QED.qed(mol)

    # Heuristics from notebook
    if mol_wt > 300 and h_donors >= 5 and logp < 1:
        pred = 2  # LOW

    safe_smiles = [
        "O", "[K+].[Cl-]",
        "[Na+].[Cl-]", "C(C1C(C(C(C(O1)O)O)O)O)O", "C(C(CO)O)O", "C(C(=O)O)C(CC(=O)O)(C(=O)O)O"
    ]

    if confidence < 0.6:
        if "C#N" in smiles and pred == 2:
            pred = 1
            
    if smiles in safe_smiles:
        pred = 2

    toxic_patterns = ["[C-]#N", "N=N", "[N+](=O)[O-]"]  # cyanide, azo, nitro
    if any(pattern in smiles for pattern in toxic_patterns):
        pred = 0

    if "C#N" in smiles:
        if pred == 2:
            pred = 1

    if qed_score > 0.7 and logp < 2 and pred == 0:
        pred = 1

    # Mapping to DB classes
    # 0 = High, 1 = Medium, 2 = Low/Non-toxic
    if pred == 2:
        tox_class = "Non-toxic"
    elif pred == 1:
        tox_class = "Moderate"
    else:
        tox_class = "High"

    explanation = (
        f"The compound {smiles[:30]}… shows {tox_class.upper()} predicted toxicity "
        f"(confidence {confidence:.2f}). "
    )
    if pred == 0:
        explanation += "Hazardous — handle under strict lab conditions. "
    elif pred == 1:
        explanation += "Handle with care. "
    else:
        explanation += "Generally safe, but monitor exposure. "

    explanation += f"Properties: MolWt={mol_wt:.1f}, LogP={logp:.2f}, QED={qed_score:.2f}."

    return {
        "tox_score": round(float(probs[0]), 4),
        "tox_class": tox_class,
        "llm_explanation": explanation,
        "extra_data": {
            "properties": {
                "mol_wt": round(float(mol_wt), 2),
                "logp": round(float(logp), 2),
                "h_donors": int(h_donors),
                "qed_score": round(float(qed_score), 2)
            },
            "probabilities": {
                "high": round(float(probs[0]), 4),
                "moderate": round(float(probs[1]), 4),
                "non_toxic": round(float(probs[2]), 4)
            }
        }
    }