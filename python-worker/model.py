"""
model.py — Tox21 inference module

Extracted from tox_model.ipynb. Provides:
  - smiles_to_features(smiles)  → np.ndarray  (2061-dim)
  - load_pipeline(path)         → dict (the saved pickle)
  - predict_toxicity(smiles, pipeline) → {"tox_score", "tox_class", "llm_explanation"}
"""

from __future__ import annotations

import pickle
import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ── Constants (must match training) ───────────────────────────────────────────
# The notebook splits at num_features=12:
#   continuous (scaled):  MolWt … LogS + Lip + Gh (12 features)
#   binary (unscaled):    Veb, Eg, Mue, BBB, FP_0 … FP_2047
# ALL_COLUMNS defines the full column ordering used during training.
NUM_CONTINUOUS_FEATURES = 12
MORGAN_RADIUS = 2
MORGAN_FP_SIZE = 2048
TOX_THRESHOLD_HIGH = 0.7
TOX_THRESHOLD_MOD  = 0.3

DESCRIPTOR_NAMES = [
    "MolWt", "Mol_Refract", "TPSA", "NumHAcceptors",
    "NumHDonors", "LogP", "LogS", "Lip", "Gh", "Veb", "Eg", "Mue", "BBB",
]
FINGERPRINT_NAMES = [f"FP_{i}" for i in range(MORGAN_FP_SIZE)]
ALL_COLUMNS = DESCRIPTOR_NAMES + FINGERPRINT_NAMES


# ── RDKit feature helpers (mirrors notebook cells 1–2, 5) ────────────────────

def _compute_esol(mol) -> float:
    from rdkit.Chem import Descriptors
    logp = Descriptors.MolLogP(mol)
    mw   = Descriptors.MolWt(mol)
    rot  = Descriptors.NumRotatableBonds(mol)
    aromatic = Descriptors.NumAromaticRings(mol)
    return 0.16 - 0.63 * logp - 0.0062 * mw + 0.066 * rot - 0.74 * aromatic


def _lipinski(mol) -> int:
    from rdkit.Chem import Descriptors
    violations = sum([
        Descriptors.MolWt(mol)   > 500,
        Descriptors.MolLogP(mol) > 5,
        Descriptors.NumHDonors(mol) > 5,
        Descriptors.NumHAcceptors(mol) > 10,
    ])
    return violations


def _ghose(mol) -> int:
    from rdkit.Chem import Descriptors
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
    from rdkit.Chem import Descriptors
    return 1 if (Descriptors.NumRotatableBonds(mol) <= 10
                 and Descriptors.TPSA(mol) <= 140) else 0


def _egan(mol) -> int:
    from rdkit.Chem import Descriptors
    return 1 if (Descriptors.MolLogP(mol) <= 5.88
                 and Descriptors.TPSA(mol) <= 131.6) else 0


def _muegge(mol) -> int:
    from rdkit.Chem import Descriptors
    mw   = Descriptors.MolWt(mol)
    logp = Descriptors.MolLogP(mol)
    tpsa = Descriptors.TPSA(mol)
    rings = Descriptors.RingCount(mol)
    return 1 if (200 <= mw <= 600 and logp <= 5
                 and tpsa <= 150 and rings <= 7) else 0


def smiles_to_features(smiles: str) -> np.ndarray | None:
    """
    Convert a SMILES string to a 2061-dimensional feature vector.
    Returns None if the SMILES is invalid.
    """
    try:
        from rdkit import Chem
        from rdkit.Chem import Descriptors
        from rdkit.Chem.rdFingerprintGenerator import GetMorganGenerator

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None

        morgan_gen = GetMorganGenerator(radius=MORGAN_RADIUS, fpSize=MORGAN_FP_SIZE)

        mw   = Descriptors.MolWt(mol)
        tpsa = Descriptors.TPSA(mol)
        logp = Descriptors.MolLogP(mol)
        bbb  = 1 if (tpsa < 90 and 1 < logp < 4 and mw < 450) else 0

        continuous = [
            mw,
            Descriptors.MolMR(mol),
            tpsa,
            Descriptors.NumHAcceptors(mol),
            Descriptors.NumHDonors(mol),
            logp,
            _compute_esol(mol),
            _lipinski(mol),
            _ghose(mol),
            _veber(mol),
            _egan(mol),
            _muegge(mol),
            bbb,
        ]

        fp = np.array(morgan_gen.GetFingerprint(mol))
        return np.concatenate([continuous, fp])

    except Exception as exc:
        log.warning(f"Feature extraction failed for '{smiles}': {exc}")
        return None


# ── Pipeline I/O ──────────────────────────────────────────────────────────────

def load_pipeline(path: str) -> dict:
    """Load the trained pipeline from a pickle file."""
    with open(path, "rb") as f:
        pipeline = pickle.load(f)
    log.info(f"✅ Loaded toxicity pipeline from {path}")
    return pipeline


# ── Inference ─────────────────────────────────────────────────────────────────

def predict_toxicity(smiles: str, pipeline: dict) -> dict:
    """
    Run real ensemble inference for a SMILES string.

    Returns:
        {
            "tox_score":       float,  # 0.0–1.0
            "tox_class":       str,    # "Non-toxic" | "Low" | "Moderate" | "High"
            "llm_explanation": str,
        }

    Raises ValueError if SMILES is invalid.
    """
    models          = pipeline["models"]       # LightGBM
    xgb_models      = pipeline["xgb_models"]  # XGBoost
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

    # 2. Preprocessing (mirrors notebook cells 12, 15–18, 20)
    X_cont = X_new.iloc[:, :num_features]
    X_bin  = X_new.iloc[:, num_features:]
    X_cont_scaled = scaler.transform(X_cont)
    X_processed = np.hstack([X_cont_scaled, X_bin.values])
    X_processed_df = pd.DataFrame(X_processed, columns=all_columns)
    X_selected = selector.transform(X_processed_df)
    X_selected_df = pd.DataFrame(X_selected, columns=selected_columns)

    # 3. Ensemble prediction (mirrors notebook cell 39)
    predictions: dict[str, float] = {}
    for label in labels:
        lgb_pred = models[label].predict_proba(X_selected_df)[0][1]
        xgb_pred = xgb_models[label].predict_proba(X_selected_df)[0][1]
        predictions[label] = (lgb_pred + xgb_pred) / 2.0

    pred_df = pd.DataFrame([predictions])

    # 4. Aggregation into NR / SR axes
    NR_labels = [c for c in labels if c.startswith("NR")]
    SR_labels = [c for c in labels if c.startswith("SR")]
    pred_df["NR_toxicity"] = pred_df[NR_labels].max(axis=1)
    pred_df["SR_toxicity"] = pred_df[SR_labels].max(axis=1)
    prob = float(max(pred_df["NR_toxicity"].values[0],
                     pred_df["SR_toxicity"].values[0]))
    tox_score = round(prob, 4)

    # 5. Classification + explanation
    if tox_score > TOX_THRESHOLD_HIGH:
        tox_class = "High"
        expl = (
            f"The compound {smiles[:30]}… shows HIGH predicted toxicity "
            f"(score {tox_score}). Hazardous — handle under strict lab conditions."
        )
    elif tox_score > TOX_THRESHOLD_MOD:
        tox_class = "Moderate"
        expl = (
            f"The compound {smiles[:30]}… shows MODERATE predicted toxicity "
            f"(score {tox_score}). Handle with care."
        )
    elif tox_score > 0.1:
        tox_class = "Low"
        expl = (
            f"The compound {smiles[:30]}… shows LOW predicted toxicity "
            f"(score {tox_score}). Monitor dosage."
        )
    else:
        tox_class = "Non-toxic"
        expl = (
            f"The compound {smiles[:30]}… shows very low predicted toxicity "
            f"(score {tox_score})."
        )

    # Append SHAP-based natural-language explanation for top driver
    try:
        import shap
        model      = models["SR-MMP"]
        explainer  = shap.TreeExplainer(model)
        shap_vals  = explainer.shap_values(X_selected_df)[0]
        top_idx    = int(np.argsort(np.abs(shap_vals))[::-1][0])
        top_feat   = selected_columns[top_idx]
        top_impact = shap_vals[top_idx]

        if top_feat == "LogP":
            driver = ("High lipophilicity increases toxicity"
                      if top_impact > 0 else "Low lipophilicity reduces toxicity")
        elif top_feat == "LogS":
            driver = ("Low solubility increases toxicity"
                      if top_impact > 0 else "High solubility reduces toxicity")
        elif top_feat == "TPSA":
            driver = ("Low polarity increases toxicity"
                      if top_impact > 0 else "High polarity reduces toxicity")
        elif "FP_" in top_feat:
            driver = f"Structural fragment ({top_feat}) affects toxicity"
        else:
            driver = f"{top_feat} influences toxicity"

        expl += f" Key driver: {driver}."
    except Exception as shap_exc:
        log.debug(f"SHAP explanation skipped: {shap_exc}")

    return {
        "tox_score":       tox_score,
        "tox_class":       tox_class,
        "llm_explanation": expl,
    }
