"""caution 모듈 재현 검사.

examples/*.json을 읽어 CautionMatcher.evaluate()를 실행하고, 예상되는 태그가
실제로 검출되는지 확인합니다. skin/verify.py, eye/verify.py와 동일하게
'패키지 실행 재현 검사'이며 임상적 타당성 검증이 아닙니다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from match import CautionMatcher  # noqa: E402

CONDITION_EXPECTATIONS = {
    "atopic_fragrance_mix.json": {
        "atopic_dermatitis": {
            "fragrance_named_allergen",
            "isothiazolinone_preservative",
            "anionic_surfactant_irritant",
            "alcohol_high_conc",
        },
        "acne_prone": set(),
    },
    "glaucoma_bak_mix.json": {
        "dry_eye_disease": {"benzalkonium_chloride"},
        "glaucoma_chronic_drops": {"benzalkonium_chloride"},
    },
    "medication_isotretinoin_mix.json": {
        "acne_prone": set(),  # 레티놀/알코올/BPO는 acne_prone 질환 규칙(comedogenic_high)과 무관
    },
}

MEDICATION_EXPECTATIONS = {
    "medication_isotretinoin_mix.json": {
        "isotretinoin_oral": {"topical_retinoid_cosmetic", "alcohol_high_conc"},
        "topical_retinoid_rx": {"topical_retinoid_cosmetic", "benzoyl_peroxide"},
    },
}


def main() -> None:
    matcher = CautionMatcher()
    failures = []

    all_files = sorted(set(CONDITION_EXPECTATIONS) | set(MEDICATION_EXPECTATIONS))
    for filename in all_files:
        payload = json.loads((ROOT / "examples" / filename).read_text(encoding="utf-8"))
        output = matcher.evaluate(
            payload["components"],
            payload.get("selected_conditions", []),
            payload.get("selected_medications", []),
        )

        for condition_id, expected_tags in CONDITION_EXPECTATIONS.get(filename, {}).items():
            actual_tags = {c["tag"] for c in output["results"][condition_id]["cautions"]}
            status = "OK" if actual_tags == expected_tags else "FAIL"
            if status == "FAIL":
                failures.append((filename, condition_id, expected_tags, actual_tags))
            print(
                f"[{status}] {filename} :: condition={condition_id} "
                f"expected={sorted(expected_tags)} actual={sorted(actual_tags)}"
            )

        for medication_id, expected_tags in MEDICATION_EXPECTATIONS.get(filename, {}).items():
            actual_tags = {
                i["tag"] for i in output["medication_results"][medication_id]["interactions"]
            }
            status = "OK" if actual_tags == expected_tags else "FAIL"
            if status == "FAIL":
                failures.append((filename, medication_id, expected_tags, actual_tags))
            print(
                f"[{status}] {filename} :: medication={medication_id} "
                f"expected={sorted(expected_tags)} actual={sorted(actual_tags)}"
            )

        # cetyl alcohol(지방알코올)이 alcohol_high_conc에 오탐되지 않는지 확인
        if filename == "atopic_fragrance_mix.json":
            cetyl_flagged = any(
                any(m["name"] == "Cetyl Alcohol" for m in c["matched_components"])
                for c in output["results"]["atopic_dermatitis"]["cautions"]
            )
            status = "OK" if not cetyl_flagged else "FAIL"
            if status == "FAIL":
                failures.append((filename, "cetyl_alcohol_false_positive", set(), {"flagged"}))
            print(f"[{status}] {filename} :: cetyl alcohol 오탐 없음 확인")

        # 10%w/w 알코올은 질환 규칙(15% 임계값)에서는 걸리지 않지만,
        # isotretinoin_oral 의약품 규칙은 ignore_concentration_threshold로 걸려야 함
        if filename == "medication_isotretinoin_mix.json":
            below_threshold_caught = any(
                i["tag"] == "alcohol_high_conc"
                for i in output["medication_results"]["isotretinoin_oral"]["interactions"]
            )
            status = "OK" if below_threshold_caught else "FAIL"
            if status == "FAIL":
                failures.append((filename, "alcohol_threshold_override", {"caught"}, set()))
            print(f"[{status}] {filename} :: 10%w/w 알코올이 이소트레티노인 규칙(임계값 무시)에서 검출됨")

    if failures:
        print(f"\n{len(failures)}건 실패:")
        for item in failures:
            print(" ", item)
        sys.exit(1)

    print("\n모든 재현 검사 통과.")


if __name__ == "__main__":
    main()
