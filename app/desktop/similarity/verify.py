"""similarity 모듈 재현 검사.

알려진 양성/음성 예시로 fragrance_similarity_score / surfactant_likeness_score가
기대한 범위의 점수를 내는지 확인합니다. caution/verify.py와 동일하게 '패키지
실행 재현 검사'이며, 향료·계면활성제 여부를 임상적/규제적으로 확정하는
검증이 아닙니다.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from similarity import fragrance_similarity_score, surfactant_likeness_score  # noqa: E402

FRAGRANCE_CASES = [
    # (설명, SMILES, score 하한, score 상한, 기대 최근접 이름 또는 None)
    ("Limonene 자기 자신(참조 목록에 있음)", "CC1=CCC(CC1)C(=C)C", 0.99, 1.0, "Limonene"),
    ("alpha-Pinene(테르펜류지만 목록엔 없음)", "CC1=CCC2CC1C2(C)C", 0.10, 0.9, None),
    ("Glycerin(향료 아님)", "OCC(O)CO", 0.0, 0.3, None),
    ("Water(향료 아님)", "O", 0.0, 0.05, None),
]

SURFACTANT_CASES = [
    # (설명, SMILES, 기대 score)
    ("SLS(설페이트 머리 + C12 꼬리)", "CCCCCCCCCCCCOS(=O)(=O)[O-].[Na+]", 1.0),
    ("코카미도프로필베타인(양쪽성)", "CCCCCCCCCCCCC(=O)NCCC[N+](C)(C)CC(=O)[O-]", 1.0),
    ("세틸알코올(긴 사슬이나 이온성 머리 없음)", "CCCCCCCCCCCCCCCCO", 0.3),
    ("소듐메틸설페이트(머리는 있으나 사슬 1개뿐)", "COS(=O)(=O)[O-].[Na+]", 0.5),
    ("글리세린(둘 다 없음)", "OCC(O)CO", 0.0),
]


def main() -> None:
    failures = []

    for label, smiles, lo, hi, expected_nearest in FRAGRANCE_CASES:
        result = fragrance_similarity_score(smiles)
        score = result["score"]
        ok = lo <= score <= hi
        if expected_nearest is not None:
            ok = ok and result["nearest"]["name"] == expected_nearest
        status = "OK" if ok else "FAIL"
        if not ok:
            failures.append(("fragrance", label, result))
        nearest_name = result["nearest"]["name"] if result["nearest"] else None
        print(f"[{status}] fragrance :: {label} -> score={score:.3f} nearest={nearest_name}")

    for label, smiles, expected in SURFACTANT_CASES:
        result = surfactant_likeness_score(smiles)
        ok = abs(result["score"] - expected) < 1e-9
        status = "OK" if ok else "FAIL"
        if not ok:
            failures.append(("surfactant", label, result))
        heads = [h["id"] for h in result["matched_head_groups"]]
        print(
            f"[{status}] surfactant :: {label} -> score={result['score']:.2f} "
            f"(expected {expected}) chain={result['longest_aliphatic_chain']} heads={heads}"
        )

    if failures:
        print(f"\n{len(failures)}건 실패:")
        for item in failures:
            print(" ", item)
        sys.exit(1)

    print("\n모든 재현 검사 통과.")


if __name__ == "__main__":
    main()
