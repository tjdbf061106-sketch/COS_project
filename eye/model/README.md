# Eye 최종 모델 실행 패키지

`skin/`과 같은 범위의 **최종 모델·예측 코드·실행 재현검사** 패키지입니다.
원본은 `최종/최최종모델`이며, 673행 전체를 평가하고 재학습한 Eye A Logistic Regression 모델(`eye_A_final.joblib`)을 사용합니다.
학습 데이터·학습 코드·비교실험·외부 검증·앱·백업은 포함하지 않습니다.
여기서 재현은 저장된 모델의 특징 계산과 예측 결과 재현이며, 전체 재학습 재현을 뜻하지 않습니다.

## 설치

검증 환경은 **Windows / Python 3.14.6**입니다. 저장소 루트에서 실행합니다.
skin과 NumPy·RDKit 버전이 다르므로 **eye 전용 가상환경**에 설치하세요.
저장소 루트의 `requirements.txt`는 skin용입니다.

```powershell
python -m venv eye/model/.venv
eye/model/.venv/Scripts/python -m pip install -r eye/model/requirements-lock.txt
eye/model/.venv/Scripts/python eye/model/verify.py
```

Linux/macOS에서는 `eye/model/.venv/Scripts/python` 대신 `eye/model/.venv/bin/python`을 사용합니다.
아래 `python` 명령은 eye 환경의 Python을 가리킵니다.
다른 운영체제에서의 수치 일치는 별도 확인이 필요합니다.

## 실행

skin과 같은 `components / canonical_smiles / amount_pct` JSON 형식을 받습니다.

```bash
python eye/model/predict.py --input eye/model/examples/single_ingredient.json
python eye/model/predict.py --input eye/model/examples/two_component_formulation.json
```

```json
{
  "components": [
    {"name": "Ethanol", "canonical_smiles": "CCO", "amount_pct": 20.0},
    {"name": "Water", "canonical_smiles": "O", "amount_pct": 80.0}
  ]
}
```

모든 성분에 유효한 SMILES와 0~100의 유한한 함량(%)을 명시합니다.
명시한 함량의 합은 0보다 크고 100 이하여야 합니다. 구조나 함량이 잘못되면 오류로 종료합니다.
구조가 표현된 성분 사이에서 함량을 정규화하며, 누락된 성분을 추정하지 않습니다.
별도 절대 농도 특징이 없으므로 단일 성분은 함량을 바꿔도 같은 구조 특징이 됩니다.
예제는 실행 확인용 가상 입력입니다.

JSON 결과는 표준 출력으로 반환됩니다. 파일로 저장하려면 새 경로를 지정합니다.

```bash
python eye/model/predict.py --input eye/model/examples/two_component_formulation.json --output eye_result.json
```

원본 코드의 벡터화 CSV 입력도 지원합니다. `feature_names.json`의 2,265개 열을 포함해야 하며,
열 순서는 이름으로 정렬합니다. `formulation_id`가 있으면 결과에 보존합니다.

```bash
python eye/model/predict.py --input input_features.csv --output eye_predictions.csv
```

다른 체크포인트는 `--model` 또는 `--checkpoint`로 지정할 수 있습니다.
기존 출력 파일은 덮어쓰지 않습니다.

## 모델 및 출력

| 항목 | 값 |
|---|---|
| 모델 | LogisticRegression, C=0.0001 |
| 전처리 | 결측값 0 대체 → StandardScaler → LR |
| 성분 집계 | 함량 가중평균(wmean) |
| 특징 | Morgan 2,048개 + RDKit descriptor 217개 |
| 양성(1) | EPA I·II |
| 음성(0) | EPA III·IV |
| 최종 학습 행 수 | 673 |
| 평가 고유 행 수 | 673 |
| 판정 임계값 | 0.48345327423625106 |

fingerprint는 입력 분자 전체, descriptor는 가장 큰 분자 조각으로 계산합니다.
특징 순서·전처리·모델·임계값은 체크포인트에 함께 저장되어 있습니다.

- `eye_A_score`: 양성 클래스에 대한 모델 점수
- `eye_A_prediction`: 점수가 `decision_threshold` 이상이면 1, 미만이면 0
- `decision_threshold`: 저장된 고정 판정 임계값
- JSON에는 판정 의미, 사용 성분 수, 명시한 함량 합도 포함합니다.

`pipeline.predict()`의 기본 임계값 0.5 대신 동봉된 예측 코드를 사용해야 합니다.
skin의 양성 정의(EPA I·II·III)와 eye의 양성 정의(EPA I·II)는 다릅니다.
점수는 보정된 실제 자극 확률이 아니며, 음성이 모든 눈 자극의 부재를 뜻하지 않습니다.

## 평가 버전과 해석 한계

현재 all673 버전은 **평가 고유 행 673개와 최종 재학습 행 673개**를 사용합니다.
388개 그룹을 기준으로 3개 seed, outer 5-fold / inner 3-fold의 그룹 기반 nested CV를 수행했습니다.
LR·RF·XGB와 wmean·max의 조합인 6개 방법을 비교하고 MCC 기준으로 LR + wmean을 선택했습니다.

선택된 방법의 seed별 내부 nested CV 결과 평균은 다음과 같습니다.

| 지표 | 평균 |
|---|---|
| 민감도 (Sensitivity) | 0.6906666666666667 |
| 특이도 (Specificity) | 0.6782238442822385 |
| MCC | 0.2943424210330707 |
| ROC-AUC | 0.7160973236009731 |

같은 비교 결과로 최종 방법을 선택했으므로 이 수치는 **선택에 조건부인 내부 CV 추정치**이며,
독립적인 외부 시험 성능이 아닙니다. 최종 임계값도 개발 자료에서 정했습니다.
673행을 3회 반복 예측한 2,019개 예측은 **2,019개의 독립 표본이 아닙니다**.
위 CV 수치는 전체 673행으로 재학습한 최종 바이너리의 별도 외부 평가 결과가 아닙니다.

## 재현검사

```bash
python eye/model/verify.py
```

파일 SHA-256, 고정 의존성 버전, 체크포인트와 메타데이터·특징 순서의 일치를 확인합니다.
원본에서 저장한 가상 입력 6개의 점수·판정을 대조하고, 별도 임시 폴더에서 CSV와 JSON 예측을 실행합니다.
JSON 예제 2개와 잘못된 JSON 입력 6개의 거부도 확인합니다.
검사에는 학습 폴더가 필요하지 않습니다. 이 검사는 소프트웨어 실행 재현검사이며 예측 성능 평가는 아닙니다.

모델 바이너리 SHA-256:
`5d5c0532cd12fd00927c9564ee28dc9c95a8bb396a049c705c77dcafaf5b28e5`

all673 원본의 모델·특징 계산·점수 계산을 사용하며, skin과 같은 JSON 입력과 벡터화 CSV 입력을 지원합니다.
`metadata.json`은 모델 및 내부 평가 정보를 기록하며, 학습 자료는 예측 실행에 필요하지 않습니다.

## 파일 구성

```text
eye/model/
  .gitattributes
  README.md
  requirements-lock.txt
  eye_A_final.joblib
  predict.py
  metadata.json
  feature_names.json
  verify.py
  smoke_test_cases.json
  checksums.json
  examples/
    single_ingredient.json
    two_component_formulation.json
```
