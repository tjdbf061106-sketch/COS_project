"""Shared validation. No chemistry or model dependencies here."""
import math
import copy
import hashlib
import json

TOLERANCE = 0.01
MAX_COMPONENTS = 100


def digest(payload):
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                    allow_nan=False).encode("utf-8")).hexdigest()


def validate(payload):
    issues, warnings, active = [], [], []
    if not isinstance(payload, dict):
        return {"valid": False, "issues": [{"message": "배합 정보 형식을 확인해 주세요."}],
                "warnings": [], "active": [], "total": 0, "unlisted": None}
    rows = payload.get("components", [])
    scope = payload.get("scope", "partial")
    if scope not in ("partial", "complete"):
        issues.append({"field": "scope", "message": "입력 범위를 선택해 주세요."})
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_COMPONENTS:
        issues.append({"field": "components", "message": "원료는 1~100개까지 입력할 수 있습니다."})
        rows = []
    total, missing_amount = 0.0, False
    seen_ids = set()
    for index, row in enumerate(rows):
        number = index + 1
        if not isinstance(row, dict):
            issues.append({"row": index, "message": f"{number}번 원료 형식이 올바르지 않습니다."})
            continue
        row_id = str(row.get("component_id", index))
        if row_id in seen_ids:
            issues.append({"row": index, "message": f"{number}번 원료의 식별자가 중복되었습니다."})
        seen_ids.add(row_id)
        value = row.get("amount_pct")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            issues.append({"row": index, "field": "amount_pct",
                           "message": f"{number}번 함량을 숫자로 입력해 주세요. 빈 값은 자동 대체하지 않습니다."})
            missing_amount = True
            continue
        if value < 0 or value > 100:
            issues.append({"row": index, "field": "amount_pct", "message": f"{number}번 함량은 0~100% 범위여야 합니다."})
            continue
        total += value
        if value == 0:
            warnings.append(f"{number}번 원료는 함량이 0%여서 계산에서 제외합니다.")
            continue
        smiles = row.get("canonical_smiles")
        if not isinstance(smiles, str) or not smiles.strip():
            issues.append({"row": index, "field": "canonical_smiles",
                           "message": f"{number}번 원료의 구조 확인이 필요합니다."})
            continue
        if len(smiles) > 10000:
            issues.append({"row": index, "message": f"{number}번 구조 입력이 너무 깁니다."})
            continue
        active.append(copy.deepcopy(row))
    # Never silently normalize an excess total, even within the completeness tolerance.
    if total > 100 + 1e-9:
        issues.append({"field": "total", "message": f"함량 합계가 {total:.4g}%입니다. 100% 이하로 수정해 주세요."})
    if not missing_amount and total <= 0:
        issues.append({"field": "total", "message": "함량이 0%보다 큰 원료를 입력해 주세요."})
    if scope == "complete" and not missing_amount and abs(total - 100) > TOLERANCE:
        issues.append({"field": "total", "message": f"전체 배합은 합계 100%가 필요합니다. 허용 오차는 {TOLERANCE}%p입니다."})
    if not active:
        issues.append({"field": "components", "message": "분석할 수 있는 원료가 없습니다."})
    unlisted = None if missing_amount else max(0, 100 - total)
    if scope == "partial" and unlisted and unlisted > TOLERANCE:
        warnings.append(f"미기재 {unlisted:.4g}%는 추정하거나 물로 채우지 않습니다.")
    return {"valid": not issues, "issues": issues, "warnings": warnings,
            "active": active, "total": total, "unlisted": unlisted}
