# Eye 최종 모델 및 학습·평가 패키지

최종 안 자극성 Logistic Regression 모델의 **추론 및 실행 재현검사** 패키지입니다.
성분별 SMILES와 함량(%)을 받아 제형 단위 점수와 판정을 반환합니다.
`model/`에 최종 모델과 예측 코드, `training/`에 학습 재현 입력·코드,
`evaluation/`에 보존된 내부 평가 결과를 제공합니다.
**저장 모델의 실행 확인과 전체 재학습은 별도 절차이며, 내부 평가 결과는 독립 외부검증 성능이 아닙니다.**
전이학습과 앱은 각각 저장소의 [`transfer_learning/`](../transfer_learning/README.md),
[`app/`](../app/README.md)를 참고하세요.

## 설치

검증 환경: Windows / Python **3.14.6**. 저장소 루트에서 실행합니다.
Skin과 NumPy·RDKit 버전이 다르므로 별도 가상환경을 사용하세요.

```powershell
python -m venv eye/model/.venv
eye/model/.venv/Scripts/python -m pip install -r eye/model/requirements-lock.txt
eye/model/.venv/Scripts/python eye/model/verify.py
```

저장소 루트의 `requirements.txt`는 Skin 전용입니다.
Linux/macOS는 `eye/model/.venv/bin/python`을 사용합니다. 다른 운영체제와 새 환경에서의 설치·수치 일치는 별도 검사가 필요합니다.
이하 `python`은 Eye 환경의 Python입니다. 신뢰하는 출처의 joblib만 로드하세요.

## 실행

```bash
python eye/model/predict.py --input eye/model/examples/single_ingredient.json
python eye/model/predict.py --input eye/model/examples/two_component_formulation.json
python eye/model/predict.py --input input.json --checkpoint eye/model/eye_A_final.joblib
```

성분 JSON과 벡터화된 CSV를 지원합니다. `--model`은 `--checkpoint`와 같은 옵션입니다.

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
원료명으로 구조를 자동 검색하지 않습니다.

JSON 결과는 기본적으로 표준 출력에 표시합니다. 새 파일로 저장하려면 `--output`을 지정합니다.

```bash
python eye/model/predict.py --input eye/model/examples/two_component_formulation.json --output eye_result.json
python eye/model/predict.py --input input_features.csv --output eye_predictions.csv
```

CSV 입력에는 `model/feature_names.json`에 정의된 2,265개 특징 열이 필요합니다.
열 순서는 이름으로 정렬하며, `formulation_id`가 있으면 출력에 보존합니다.
CSV 입력에는 `--output`이 필수이고, 기존 출력 파일은 덮어쓰지 않습니다.

## 모델 및 출력

| 항목 | 값 |
|---|---|
| 모델 | LogisticRegression, C=0.0001, solver=lbfgs |
| 집계 | 함량 가중평균(wmean) |
| 구조 특징 | Morgan fingerprint 2,048개 + RDKit descriptor 217개 |
| 전처리 | 결측값 0 대체 → StandardScaler → LogisticRegression |
| 입력 차원 | 2,265 |
| 양성(1) | EPA I·II |
| 음성(0) | EPA III·IV |
| 최종 학습 / 내부 평가 고유 행 수 | 673 / 673 |
| 클래스 구성 | 양성 125행 / 음성 548행 |
| 임계값 | 0.48345327423625106 |

Descriptor는 최대 분자 조각, Morgan fingerprint는 염을 포함한 입력 구조에서 계산합니다.
특징 순서·전처리·모델·임계값은 체크포인트에 함께 있습니다. 학습 폴더는 추론에 필요하지 않습니다.
기본 임계값 0.5로 판정하는 대신 동봉한 예측 코드를 사용하세요.

- `eye_A_score`: 양성 클래스에 대한 모델 점수
- `eye_A_prediction`: 점수가 `decision_threshold` 이상이면 1, 미만이면 0
- `decision_threshold`: 저장된 판정 임계값
- `predicted_label_meaning`: JSON 출력의 판정 의미
- `n_components_used`, `represented_amount_pct`: JSON 출력의 사용 성분 수·명시한 함량 합
- `note`: JSON 출력의 연구용 결과 한계 안내

Skin의 양성 정의(I·II·III)와 다릅니다. 점수는 자극 강도나 보정된 개인 발병확률이 아니며,
음성에는 EPA III가 포함되므로 음성 판정이 자극의 부재나 안전성 보증을 뜻하지 않습니다.

### 내부 모델 비교

673행·388그룹을 대상으로 세 시드(42·202·777)의 그룹 기반 중첩 교차검증을 수행했습니다.
Outer 5-fold / inner 3-fold에서 LR·RF·XGB와 wmean·max의 여섯 조합을 비교하고,
시드별 전체 OOF MCC 평균을 우선하여 LR+wmean을 선택했습니다.

| 지표 | 선택된 LR+wmean의 시드별 전체 OOF 평균 |
|---|---:|
| 민감도 | 0.6907 |
| 특이도 | 0.6782 |
| MCC | 0.2943 |
| ROC-AUC | 0.7161 |

모델 순위는 [`evaluation/ranking.csv`](evaluation/ranking.csv),
선택 기준은 [`evaluation/selected_model.json`](evaluation/selected_model.json)에 있습니다.
같은 비교 결과로 방법을 선택했으므로 이 수치는 **선택에 조건부인 내부 CV 추정치**입니다.
동일한 673행을 세 번 평가한 2,019개 예측은 2,019개의 독립 표본이 아닙니다.
전체 673행으로 재학습한 최종 저장 모델의 독립 외부 시험 결과와 구분해야 합니다.

## 기존 입력 처리의 한계

- JSON의 모든 성분에 유효한 `canonical_smiles`와 0~100의 유한한 숫자 `amount_pct`가 필요합니다. 함량 누락·null·잘못된 구조는 오류로 종료합니다.
- 명시한 함량 합은 0보다 크고 100 이하여야 합니다. 100% 미만의 부분 조성도 허용하지만, 미공개 성분을 추정하거나 보완하지 않습니다.
- 함량은 표현된 성분 사이에서 정규화합니다. 별도의 절대 농도 특징이 없어 단일 성분의 함량만 바꾸면 같은 구조 특징이 됩니다.
- 분자 서술자에서 계산 가능한 값만으로 특징별 가중평균을 계산하며, 남은 결측값은 저장된 전처리로 대체합니다. 이는 원료·조성 정보의 완전성을 보증하지 않습니다.
- 벡터화 CSV는 정의된 특징 이름과 계산 방식을 따라야 합니다. 무한대 값은 거부하며 NaN은 저장된 결측값 대체를 적용합니다.

## 재현검사

### 저장 모델 실행 확인

```bash
python eye/model/verify.py
```

검사 항목:

1. 패키지 파일 SHA-256과 고정 의존성 버전
2. 모델·메타데이터·특징 순서·임계값의 일치
3. 원본에서 저장한 가상 입력 6개의 점수·판정 재현
4. 별도 임시 폴더에서 JSON·CSV 예측의 독립 실행
5. JSON 예제 실행과 잘못된 입력의 거부

이 검사는 소프트웨어 실행 재현검사이며 화장품 예측 성능 평가가 아닙니다.
모델 SHA-256: `5d5c0532cd12fd00927c9564ee28dc9c95a8bb396a049c705c77dcafaf5b28e5`

### 보존된 학습·평가 자료 확인

Eye 환경에서 학습용 의존성을 추가로 설치한 뒤 실행합니다.

```bash
python -m pip install -r eye/training/requirements.txt
python eye/training/verify_published.py
```

입력·코드 해시, 12,114개 OOF 예측(673행 × 3시드 × 6조합)의 지표·순위,
기존 최종 모델의 673행 참조 예측을 확인합니다. 전체 중첩 CV를 다시 학습하는 검사는 아닙니다.
검증 코드에서 `assert`를 사용하므로 Python의 `-O` 옵션을 사용하지 마세요.

### 전체 학습 재실행

```bash
python eye/training/run_comparison.py --workers 6
python eye/training/verify_comparison.py
python eye/training/finalize_model.py --workers 6
python eye/training/verify_features.py
python eye/training/verify_final_model.py
python eye/training/finish_package.py
```

전체 비교에는 5,490회의 모델 적합과 추가 최종 설정 탐색이 필요합니다.
학습 결과는 `training/` 아래에 생성되며, `evaluation/`은 보존된 원본 평가 결과입니다.
다른 Python·OS 환경에서의 수치 일치나 모델 바이너리의 바이트 일치까지 보장하지 않습니다.
`source_config.json`의 원본 로컬 경로는 출처 기록이며 실행 시 해당 경로를 읽지 않습니다.
`evaluation/RESULTS.txt`는 원본 전체 실행 폴더의 기록이므로 공개 패키지 실행에는 위 경로와 순서를 따릅니다.

## 파일 구성

```text
eye/
  README.md
  model/                          # 최종 모델 추론 및 실행 재현검사
    README.md
    predict.py
    eye_A_final.joblib
    metadata.json
    feature_names.json
    requirements-lock.txt
    checksums.json
    smoke_test_cases.json
    verify.py
    examples/
      single_ingredient.json
      two_component_formulation.json
  training/                       # 학습 입력·코드·검증 및 의존성
    input_snapshot.csv
    component_linkage.csv
    wmean.npy
    max.npy
    feature_names.json
    source_config.json
    requirements.txt
    requirements-lock.txt
    run_comparison.py
    finalize_model.py
    finish_package.py
    verify_published.py
    ...
  evaluation/                     # 보존된 내부 평가 결과
    comparison_config.json
    ranking.csv
    metrics_summary.csv
    metrics_by_seed.csv
    metrics_by_fold.csv
    oof_predictions.csv
    selected_model.json
    selected_parameters.json
    refit_reference_predictions.csv
    ...
```

예측 전용 상세 안내는 [`model/README.md`](model/README.md)를 참고하세요.
화장품·질환별 안전성, 알레르기 또는 아토피 악화 예측이 입증된 도구가 아니며 진단·처방을 대체하지 않습니다.
