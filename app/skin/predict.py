"""
skin 자극성 — 신규 제형(원료 1개 이상) 추론.

원료 1개만 입력해도 되고(전체 학습자료의 61%가 원료 1개짜리 제형), 여러 개를 입력하면
투입비율(amount_pct)로 가중평균해서 하나의 제형으로 합친 뒤 예측한다.

feature 계산은 skin_vectorized.csv를 만든 원래 노트북(skin_feature_expand_full.ipynb)과
동일한 방식을 그대로 따른다:
  - descriptor(공통 AromaticProportion + RDKit 217개)는 염 제거 후 최대 프래그먼트 기준
  - Morgan fingerprint(2,048비트, radius=2)는 염 포함 원본 분자 기준
  - 여러 원료는 투입비율 가중평균으로 합침(desc는 NaN-aware, FP는 일반 가중평균)

입력 JSON 형식은 pretraining/mixture_predictor.py와 동일하게 맞췄다(다른 endpoint와
같은 스키마 재사용 가능):
    {
      "components": [
        {"component_id": "...", "name": "...", "canonical_smiles": "...", "amount_pct": 100.0}
      ]
    }

사용법:
    py predict.py --input my_formulation.json
    py predict.py --input my_formulation.json --checkpoint skin_rf_checkpoint.joblib
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import joblib
import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors, rdFingerprintGenerator
from rdkit import DataStructs

_FULL_DESC_LIST = Descriptors._descList
_MORGAN_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def get_largest_fragment(mol):
    frags = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    if len(frags) == 1:
        return mol
    return max(frags, key=lambda m: m.GetNumHeavyAtoms())


def compute_aromatic_proportion(mol):
    n_heavy = mol.GetNumHeavyAtoms()
    n_aromatic = sum(1 for a in mol.GetAtoms() if a.GetIsAromatic())
    return n_aromatic / n_heavy if n_heavy > 0 else 0.0


def compute_full_descriptors(mol):
    out = {}
    for name, func in _FULL_DESC_LIST:
        try:
            val = func(mol)
            if not np.isfinite(val):
                val = np.nan
        except Exception:
            val = np.nan
        out[f"desc_{name}"] = val
    return out


def compute_morgan_fp(mol):
    fp = _MORGAN_GEN.GetFingerprint(mol)
    arr = np.zeros(2048, dtype=np.int8)
    DataStructs.ConvertToNumpyArray(fp, arr)
    return {f"fp_w_{i}": int(v) for i, v in enumerate(arr)}


def compute_component_features(smiles):
    """원료 1개의 raw feature dict(AromaticProportion + desc_* + fp_w_*)를 계산.
    구조를 못 읽으면 None을 반환(학습 때 unresolved 성분을 제외한 것과 동일하게 처리)."""
    mol_orig = Chem.MolFromSmiles(smiles)
    if mol_orig is None:
        return None
    mol_stripped = get_largest_fragment(mol_orig)

    row = {"AromaticProportion": compute_aromatic_proportion(mol_stripped)}
    row.update(compute_full_descriptors(mol_stripped))
    row.update(compute_morgan_fp(mol_orig))  # FP는 염 포함(원본) 기준
    return row


def weighted_mean_nan_aware(pct, mat):
    result = np.full(mat.shape[1], np.nan)
    for j in range(mat.shape[1]):
        col = mat[:, j]
        mask = ~np.isnan(col)
        if not mask.any():
            continue
        w = pct[mask]
        if w.sum() == 0:
            w = np.ones_like(w)
        result[j] = (w * col[mask]).sum() / w.sum()
    return result


def weighted_mean_plain(pct, mat):
    w = pct.copy()
    if w.sum() == 0:
        w = np.ones_like(w)
    return (w[:, None] * mat).sum(axis=0) / w.sum()


def aggregate_formulation(components, feature_cols):
    """components: [{"canonical_smiles":..., "amount_pct":...}, ...] -> feature_cols 순서의 1xN 배열."""
    rows, pcts = [], []
    skipped = []
    for c in components:
        smiles = c.get("canonical_smiles")
        if not smiles:
            skipped.append(c.get("name", c.get("component_id", "?")))
            continue
        feats = compute_component_features(smiles)
        if feats is None:
            skipped.append(c.get("name", c.get("component_id", "?")))
            continue
        rows.append(feats)
        raw_pct = c.get("amount_pct", 1.0)
        raw_pct = 1.0 if raw_pct is None else float(raw_pct)
        if not np.isfinite(raw_pct) or raw_pct < 0 or raw_pct > 100:
            raise ValueError(
                f"amount_pct는 0~100 사이의 유한한 숫자여야 합니다 "
                f"(받은 값: {raw_pct}, 성분: {c.get('name', c.get('component_id', '?'))})"
            )
        pcts.append(raw_pct)

    if not rows:
        raise ValueError("구조를 읽을 수 있는 원료가 하나도 없습니다(canonical_smiles 확인 필요)")

    pct = np.array(pcts, dtype=float)
    desc_cols = [c for c in feature_cols if c.startswith("desc_")]
    fp_cols = [c for c in feature_cols if c.startswith("fp_w_")]
    # resolved_pct(2026-11-08부터 production feature)는 성분별 descriptor가 아니라 "구조를 읽은
    # 성분들의 투입비율 합"(pct.sum())이라 따로 계산한다 — 가중평균 대상에서 빠진다.
    common_cols = [c for c in feature_cols if c not in desc_cols and c not in fp_cols and c != "resolved_pct"]

    common_mat = np.array([[r[c] for c in common_cols] for r in rows])
    desc_mat = np.array([[r[c] for c in desc_cols] for r in rows])
    fp_mat = np.array([[r[c] for c in fp_cols] for r in rows])

    common_vec = weighted_mean_plain(pct, common_mat)
    desc_vec = weighted_mean_nan_aware(pct, desc_mat)
    fp_vec = weighted_mean_plain(pct, fp_mat)

    full = dict(zip(common_cols, common_vec))
    full.update(dict(zip(desc_cols, desc_vec)))
    full.update(dict(zip(fp_cols, fp_vec)))
    if "resolved_pct" in feature_cols:
        full["resolved_pct"] = float(pct.sum())

    x = np.array([[full[c] for c in feature_cols]], dtype=np.float32)
    return x, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON 파일 경로 (mixture_predictor.py와 동일 스키마)")
    parser.add_argument("--checkpoint",
                         default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                               "skin_rf_checkpoint.joblib"))
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        payload = json.load(f)
    components = payload.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("입력 JSON에 'components' 비어있지 않은 리스트가 필요합니다")

    ckpt = joblib.load(args.checkpoint)
    x, skipped = aggregate_formulation(components, ckpt["feature_cols"])
    if skipped:
        print(f"[경고] 구조를 못 읽어 제외된 원료: {skipped}")

    x_filtered = x[:, ckpt["nz_filter_keep"]]
    proba = ckpt["model"].predict_proba(x_filtered)[0, 1]
    pred = int(proba >= ckpt["threshold"])

    result = {
        "n_components_used": len(components) - len(skipped),
        "n_components_skipped": len(skipped),
        "probability_class1": round(float(proba), 4),
        "threshold": ckpt["threshold"],
        "predicted_label": pred,
        "predicted_label_meaning": "자극성 있음(EPA I/II/III 상당)" if pred == 1 else "자극성 낮음(EPA IV 상당)",
        "note": "참고용 추정치입니다. 화장품 외부검증이나 실제 안전성 판정이 아닙니다.",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
