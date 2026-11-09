# Skin 최종 모델 실행 패키지

최종 피부자극성 RandomForest 모델의 **추론 및 실행 재현검사** 패키지입니다.
성분별 SMILES와 함량(%)을 받아 제형 단위 점수와 판정을 반환합니다.
학습 데이터·학습 코드·비교실험·외부검증·전이학습·앱은 포함하지 않습니다.
**저장된 모델의 예측은 재현할 수 있지만, 원자료부터 전체 재학습을 재현하는 패키지는 아닙니다.**

## 설치

검증 환경: Windows / Python **3.13.12**. 저장소 루트에서 실행합니다.
Eye와 NumPy·RDKit 버전이 다르므로 별도 가상환경을 사용하세요.

```powershell
python -m venv skin/.venv
skin/.venv/Scripts/python -m pip install -r requirements.txt
skin/.venv/Scripts/python skin/verify.py
```

`requirements.txt`는 저장소 루트의 skin 전용 고정 의존성 파일입니다.
Linux/macOS는 `skin/.venv/bin/python`을 사용합니다. 다른 운영체제와 새 환경에서의 설치·수치 일치는 별도 검사가 필요합니다.
이하 `python`은 skin 환경의 Python입니다. 신뢰하는 출처의 joblib만 로드하세요.

## 실행

```bash
python skin/predict.py --input skin/examples/single_ingredient.json
python skin/predict.py --input skin/examples/two_component_formulation.json
python skin/predict.py --input input.json --checkpoint skin/skin_rf_checkpoint.joblib
```

입력은 JSON만 지원합니다. Eye의 CSV 입력이나 `--output` 옵션은 skin에는 없습니다.

```json
{
  "components": [
    {"name": "Ethanol", "canonical_smiles": "CCO", "amount_pct": 20.0},
    {"name": "Water", "canonical_smiles": "O", "amount_pct": 80.0}
  ]
}
```

예시는 실행 확인용 가상 입력이며 처방 권고가 아닙니다.
`amount_pct=20.0`은 20%입니다. 모든 함량과 실제 원료에 대응하는 SMILES를 명시하세요.
UVCB 등 분포형 원료를 임의의 단일 구조로 바꾸면 실제 원료와 다른 입력이 됩니다.

## 모델 및 출력

| 항목 | 값 |
|---|---|
| 모델 | RandomForest, 500 trees, class_weight=balanced |
| 집계 | 함량 가중평균(wmean) |
| 구조 특징 | AromaticProportion + RDKit descriptor + Morgan fingerprint |
| 농도 특징 | 구조 계산에 사용된 성분의 함량 합 resolved_pct |
| 입력 / nz20 선택 후 | 2,267 / 524 |
| 양성(1) | EPA I·II·III |
| 음성(0) | EPA IV |
| 임계값 | 0.33 |

Descriptor는 최대 분자 조각, Morgan fingerprint는 염을 포함한 입력 구조에서 계산합니다.
특징 순서·선택 마스크·모델·임계값은 체크포인트에 함께 있습니다. 외부 CSV나 학습 폴더는 추론에 필요하지 않습니다.

- `probability_class1`: 양성 모델 점수(출력은 소수점 4자리 반올림)
- `predicted_label`: 반올림 전 점수가 `threshold` 이상이면 1, 미만이면 0
- `predicted_label_meaning`: 판정 의미
- `n_components_used`, `n_components_skipped`: 사용·제외된 성분 수
- `note`: 연구용 결과의 한계

Eye의 양성 정의(I·II)와 다릅니다. 점수는 자극 강도나 보정된 개인 발병확률이 아니며, 음성 판정은 안전성 보증이 아닙니다.

## 기존 입력 처리의 한계

원본 예측 동작을 보존했으며 Eye의 엄격한 입력 검증과 같지 않습니다.

- 함량 누락 또는 null은 1%로 처리합니다. 앱에서는 함량 입력을 필수로 하세요.
- 유효 구조에 대해 함량의 유한성 및 0~100 범위를 검사하지만, 전체 함량 합은 검사하지 않습니다.
- 사용 가능한 성분의 함량 합이 0이면 균등가중으로 계산합니다. 앱에서는 전부 0인 입력을 거부해야 합니다.
- 구조가 없거나 해석 불가하면 해당 성분이 제외될 수 있으며, 사용 가능한 구조가 하나도 없으면 오류입니다.
- 성분 제외 시 JSON 앞에 경고 문자열이 출력되므로 stdout 전체가 항상 순수 JSON은 아닙니다.
- 별도의 NaN 대치 단계를 이식하지 않았습니다. 지원하지 않는 구조·계산 불가 특징의 일반적 처리 보장은 없습니다.

## 재현검사

```bash
python skin/verify.py
```

검사 항목:
1. 고정 의존성 버전과 체크포인트 SHA-256
2. 메타데이터의 특징 수·임계값과 저장 모델의 일치
3. 예제 2개의 점수·판정 재현
4. 원본 연구 폴더가 없는 임시 디렉터리에 코드·모델·예제만 복사한 독립 실행
5. 유효 구조의 음수/100% 초과 함량, 빈 성분 목록, 전부 미해결 구조의 오류 종료

예제 기대값은 원본 skin 실행 코드와 대조했습니다. 이 검사는 실행 재현검사이며 화장품 예측 성능 평가가 아닙니다.
모델 SHA-256: `1ff0bd062fba0fab11c0407731ddb6996c7646bf033e07a4c501a391a2459e34`

## 파일 구성

```text
requirements.txt                 # 저장소 루트: skin 환경
skin/
  README.md
  predict.py
  skin_rf_checkpoint.joblib
  metadata.json
  smoke_test_cases.json
  verify.py
  examples/
    single_ingredient.json
    two_component_formulation.json
```

기존 COS 연구 저장소의 학습·평가 이력은 이 패키지와 별도로 보존합니다.
화장품·질환별 안전성, 알레르기 또는 아토피 악화 예측이 입증된 도구가 아니며 진단·처방을 대체하지 않습니다.
