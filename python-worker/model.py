"""
model.py — Tox21 inference module
"""

from __future__ import annotations

import pickle
import logging
import numpy as np
import pandas as pd
from rdkit import Chem
from rdkit.Chem import Descriptors
from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
# FIX: NUM_CONTINUOUS_FEATURES is now 9. 
# The first 9 features are continuous/counts. The last 4 (Veb, Eg, Mue, BBB) are binary.
NUM_CONTINUOUS_FEATURES = 9 
MORGAN_RADIUS = 2
MORGAN_FP_SIZE = 2048
TOX_THRESHOLD_HIGH = 0.7
TOX_THRESHOLD_MOD  = 0.3

_morgan_gen = GetMorganGenerator(radius=MORGAN_RADIUS, fpSize=MORGAN_FP_SIZE)

DESCRIPTOR_NAMES = [
    "MolWt", "Mol_Refract", "TPSA", "NumHAcceptors",
    "NumHDonors", "LogP", "LogS", "Lip", "Gh", "Veb", "Eg", "Mue", "BBB",
]
FINGERPRINT_NAMES = [f"FP_{i}" for i in range(MORGAN_FP_SIZE)]
ALL_COLUMNS = DESCRIPTOR_NAMES + FINGERPRINT_NAMES


# ── RDKit feature helpers ────────────────────────────────────────────────────

def _compute_esol(mol) -> float:
    logp = Descriptors.MolLogP(mol)
    mw   = Descriptors.MolWt(mol)
    rot  = Descriptors.NumRotatableBonds(mol)
    aromatic = Descriptors.NumAromaticRings(mol)
    return 0.16 - 0.63 * logp - 0.0062 * mw + 0.066 * rot - 0.74 * aromatic

def _lipinski(mol) -> int:
    violations = sum([
        Descriptors.MolWt(mol)   > 500,
        Descriptors.MolLogP(mol) > 5,
        Descriptors.NumHDonors(mol) > 5,
        Descriptors.NumHAcceptors(mol) > 10,
    ])
    return violations

def _ghose(mol) -> int:
    mw    = Descriptors.MolWt(mol)
    logp  = Descriptors.MolLogP(mol)
    mr    = Descriptors.MolMR(mol)
    atoms = mol.GetNumAtoms()
    violations = sum([
        not (160 <= mw    <= 480),
        not (-0.4 <= logp <= 5.6),
        not (40   <= mr   <= 130),
        not (20   <= atoms <= 70),
    ])
    return violations

def _veber(mol) -> int:
    return 1 if (Descriptors.NumRotatableBonds(mol) <= 10
                 and Descriptors.TPSA(mol) <= 140) else 0

def _egan(mol) -> int:
    return 1 if (Descriptors.MolLogP(mol) <= 5.88
                 and Descriptors.TPSA(mol) <= 131.6) else 0

def _muegge(mol) -> int:
    mw   = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    rings = Descriptors.RingCount(mol)
    return 1 if (200 <= mw <= 600 and logp <= 5
                 and tpsa <= 150 and rings <= 7) else 0

def smiles_to_features(smiles: str) -> np.ndarray | None:
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        mw   = Descriptors.MolWt(mol)
        tpsa = Descriptors.TPSA(mol)
        logp = Descriptors.MolLogP(mol)
        bbb  = 1 if (tpsa < 90 and 1 < logp < 4 and mw < 450) else 0

        features = []
        # Continuous / Counts (Indices 0-8)
        features.append(mw)
        features.append(Descriptors.MolMR(mol))
        features.append(tpsa)
        features.append(Descriptors.NumHAcceptors(mol))
        features.append(Descriptors.NumHDonors(mol))
        features.append(logp)
        features.append(_compute_esol(mol)) # FIX: added underscores to helpers
        features.append(_lipinski(mol))
        features.append(_ghose(mol))
        
        # Binary Descriptors (Indices 9-12)
        features.append(_veber(mol))
        features.append(_egan(mol))
        features.append(_muegge(mol))
        features.append(bbb)

        # Fingerprints (Indices 13+)
        fp = np.array(_morgan_gen.GetFingerprint(mol))
        features.extend(fp)
        return np.array(features)

    except Exception as exc:
        log.warning(f"Feature extraction failed for '{smiles}': {exc}")
        return None


# ── Pipeline I/O ──────────────────────────────────────────────────────────────

def load_pipeline(path: str) -> dict:
    with open(path, "rb") as f:
        pipeline = pickle.load(f)
    log.info(f"✅ Loaded toxicity pipeline from {path}")
    return pipeline


# ── Inference ─────────────────────────────────────────────────────────────────

def predict_toxicity(smiles: str, pipeline: dict) -> dict:
    models          = pipeline["models"]       
    xgb_models      = pipeline["xgb_models"]  
    scaler          = pipeline["scaler"]
    selector        = pipeline["selector"]
    all_columns     = pipeline["all_columns"]
    selected_columns = pipeline["selected_columns"]
    num_features    = pipeline["num_features"]
    labels          = pipeline["labels"]

    # 1. Feature extraction
    raw = smiles_to_features(smiles)
    if raw is None:
        raise ValueError(f"Invalid SMILES: {smiles!r}")

    X_new = pd.DataFrame([raw], columns=all_columns)

    # 2. Preprocessing
    X_cont = X_new.iloc[:, :num_features]
    X_bin  = X_new.iloc[:, num_features:]
    X_cont_scaled = scaler.transform(X_cont)
    X_processed = np.hstack([X_cont_scaled, X_bin.values])
    X_processed_df = pd.DataFrame(X_processed, columns=all_columns)
    X_selected = selector.transform(X_processed_df)
    X_selected_df = pd.DataFrame(X_selected, columns=selected_columns)

    # 3. Ensemble prediction
    predictions: dict[str, float] = {}
    for label in labels:
        lgb_pred = models[label].predict_proba(X_selected_df)[0][1]
        xgb_pred = xgb_models[label].predict_proba(X_selected_df)[0][1]
        predictions[label] = (lgb_pred + xgb_pred) / 2.0

    pred_df = pd.DataFrame([predictions])

    # 4. Aggregation into NR / SR axes
    NR_labels = [c for c in labels if c.startswith("NR")]
    SR_labels = [c for c in labels if c.startswith("SR")]
    pred_df["NR_toxicity"] = pred_df[NR_labels].max(axis=1) if NR_labels else 0.0
    pred_df["SR_toxicity"] = pred_df[SR_labels].max(axis=1) if SR_labels else 0.0
    
    prob = float(max(pred_df["NR_toxicity"].values[0], pred_df["SR_toxicity"].values[0]))
    tox_score = round(prob, 4)

    # 5. Classification
    if tox_score > TOX_THRESHOLD_HIGH:
        tox_class = "High"
        expl = f"The compound {smiles[:30]}… shows HIGH predicted toxicity (score {tox_score}). Hazardous — handle under strict lab conditions."
    elif tox_score > TOX_THRESHOLD_MOD:
        tox_class = "Moderate"
        expl = f"The compound {smiles[:30]}… shows MODERATE predicted toxicity (score {tox_score}). Handle with care."
    elif tox_score > 0.1:
        tox_class = "Low"
        expl = f"The compound {smiles[:30]}… shows LOW predicted toxicity (score {tox_score}). Monitor dosage."
    else:
        tox_class = "Non-toxic"
        expl = f"The compound {smiles[:30]}… shows very low predicted toxicity (score {tox_score})."

    # 6. SHAP Explanation
    try:
        import shap
        # FIX: Dynamically find the label with the highest predicted probability to explain
        top_label = pred_df[labels].idxmax(axis=1).values[0]
        model     = models[top_label]
        
        explainer = shap.TreeExplainer(model)
        shap_vals = explainer.shap_values(X_selected_df)
        
        # Handle different SHAP output formats based on version/objective
        if isinstance(shap_vals, list):
            shap_vals = shap_vals[1][0] 
        else:
            shap_vals = shap_vals[0]
            
        top_idx    = int(np.argsort(np.abs(shap_vals))[::-1][0])
        top_feat   = selected_columns[top_idx]
        top_impact = shap_vals[top_idx]

        if top_feat == "LogP":
            driver = "High lipophilicity increases toxicity" if top_impact > 0 else "Low lipophilicity reduces toxicity"
        elif top_feat == "LogS":
            driver = "Low solubility increases toxicity" if top_impact > 0 else "High solubility reduces toxicity"
        elif top_feat == "TPSA":
            driver = "Low polarity increases toxicity" if top_impact > 0 else "High polarity reduces toxicity"
        elif "FP_" in top_feat:
            driver = f"Structural fragment ({top_feat}) affects toxicity"
        else:
            driver = f"{top_feat} influences toxicity"

        expl += f" Key driver ({top_label}): {driver}."
    except Exception as shap_exc:
        log.debug(f"SHAP explanation skipped: {shap_exc}")

    return {
        "tox_score":       tox_score,
        "tox_class":       tox_class,
        "llm_explanation": expl,
    }