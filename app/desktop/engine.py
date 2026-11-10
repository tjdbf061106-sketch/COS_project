"""One-request JSON worker, independently frozen for each model environment."""
import sys
import json
import traceback
import importlib.util
import hashlib
import io
import contextlib
import base64
from pathlib import Path

# Explicit imports are intentional: the freeze step collects these inference dependencies.
import numpy as np
import joblib
import sklearn.ensemble
import sklearn.linear_model
import sklearn.impute
import sklearn.preprocessing
import sklearn.pipeline
import sklearn.utils._cython_blas
from rdkit import Chem, rdBase
from rdkit.Chem import Draw

from desktop.paths import resources
from desktop.validation import validate


def chemistry(smiles):
    if not isinstance(smiles, str) or not smiles.strip():
        raise ValueError("분자 구조를 입력해 주세요.")
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumAtoms() == 0:
        raise ValueError("해석할 수 없는 SMILES입니다. 원료 구조를 다시 확인해 주세요.")
    if mol.GetNumAtoms() > 1000:
        raise ValueError("이 버전은 원자 수 1,000개 이하의 구조를 지원합니다.")
    return mol


def describe(smiles):
    mol = chemistry(smiles)
    image = Draw.MolToImage(mol, size=(460, 230))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return {"canonical_smiles": Chem.MolToSmiles(mol),
            "preview": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}


def module_for(endpoint):
    path = resources() / endpoint / "predict.py"
    spec = importlib.util.spec_from_file_location("cos_" + endpoint + "_predict", path)
    module = importlib.util.module_from_spec(spec)
    # Legacy skin module reconfigures stdout; a redirected StringIO has no reconfigure.
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(module)
    return module


def run(request):
    action = request.get("action", "predict")
    if action == "structure":
        return describe(request.get("smiles"))
    if action == "canonicalize":
        values = request.get("smiles")
        if not isinstance(values, list) or len(values) > 1200:
            raise ValueError("구조 확인 목록이 올바르지 않습니다.")
        results = []
        for value in values:
            try:
                mol = chemistry(value)
                # Atom-map labels are bookkeeping; preserve salts, charge, isotopes and stereochemistry.
                for atom in mol.GetAtoms():
                    atom.SetAtomMapNum(0)
                results.append({"canonical_smiles": Chem.MolToSmiles(mol, isomericSmiles=True)})
            except (ValueError, TypeError) as exc:
                results.append({"error": str(exc)})
        return results
    if action == "evidence":
        from desktop.evidence import describe_evidence
        return describe_evidence(request.get("smiles"))
    if action != "predict":
        raise ValueError("지원하지 않는 작업입니다.")
    endpoint = request.get("endpoint")
    if endpoint not in ("skin", "eye"):
        raise ValueError("모델을 선택해 주세요.")
    payload = request.get("payload")
    checked = validate(payload)
    if not checked["valid"]:
        raise ValueError("\n".join(i["message"] for i in checked["issues"]))
    rows = checked["active"]
    for i, row in enumerate(rows):
        try:
            chemistry(row["canonical_smiles"])
        except ValueError as exc:
            raise ValueError(f"{row.get('name') or str(i + 1) + '번 원료'}: {exc}") from exc
    metadata = json.loads((resources() / endpoint / "metadata.json").read_text(encoding="utf-8"))
    filename = "skin_rf_checkpoint.joblib" if endpoint == "skin" else "eye_A_final.joblib"
    model_path = resources() / endpoint / filename
    file_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if endpoint == "skin":
        expected = metadata["checkpoint_sha256"]
    else:
        expected = json.loads((resources() / "eye" / "checksums.json").read_text(encoding="utf-8"))["files"][filename]
    if file_hash != expected:
        raise ValueError("모델 파일의 검증값이 다릅니다. 원본 패키지를 다시 확인해 주세요.")
    module = module_for(endpoint)
    if endpoint == "skin":
        bundle = joblib.load(model_path)
        features, skipped = module.aggregate_formulation(rows, bundle["feature_cols"])
        if skipped:
            raise ValueError("구조를 확인하지 못한 원료가 있어 피부 예측을 보류합니다.")
        values = features[:, bundle["nz_filter_keep"]]
        score = float(bundle["model"].predict_proba(values)[0, 1])
        threshold = float(bundle["threshold"])
        label = "EPA I·II·III" if score >= threshold else "EPA IV"
        model_name = "Random Forest"
        concentration = "구조가 확인된 성분의 함량 합과 상대 함량을 사용합니다."
    else:
        bundle = module.load_bundle(model_path)
        result = module.predict_components(bundle, {"components": rows})
        score, threshold = result["eye_A_score"], result["decision_threshold"]
        label = "EPA I·II" if score >= threshold else "EPA III·IV"
        model_name = "Logistic Regression"
        concentration = "상대 함량을 사용합니다. 원료 한 개만 입력하면 함량을 바꿔도 같은 결과입니다."
    if not np.isfinite(score):
        raise ValueError("모델이 유효한 점수를 반환하지 않았습니다.")
    return {"status": "complete", "endpoint": endpoint, "score": score,
            "threshold": threshold, "predicted_class": int(score >= threshold), "label_text": label,
            "model_name": model_name, "model_id": endpoint + "-" + file_hash[:12],
            "model_sha256": file_hash, "n_components": len(rows), "concentration_note": concentration,
            "note": "학습된 EPA 분류의 모델 점수입니다. 개인의 발병 확률이나 질환별 사용 허가가 아닙니다."}


def main():
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        raw = sys.stdin.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("입력 크기가 허용 범위를 넘었습니다.")
        request = json.loads(raw)
        with contextlib.redirect_stdout(io.StringIO()):
            result = run(request)
        response = {"ok": True, "result": result}
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        response = {"ok": False, "error": str(exc)}
    print(json.dumps(response, ensure_ascii=False, allow_nan=False))
    return 0 if response["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
