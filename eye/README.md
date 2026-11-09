# Eye 최종 모델 실행 패키지

`skin/`과 같은 범위의 **최종 모델·예측 코드·실행 재현검사** 패키지입니다.
원본은 `최종/최종모델`이며, 학습이 끝난 Eye A Logistic Regression 모델을 사용합니다.
학습 데이터·학습 코드·비교실험·외부 검증·앱·백업은 포함하지 않습니다.
여기서 재현은 저장된 모델의 특징 계산과 예측 결과 재현이며, 전체 재학습 재현을 뜻하지 않습니다.

## 설치

검증 환경은 **Windows / Python 3.14.6**입니다. 저장소 루트에서 실행합니다.
skin과 NumPy·RDKit 버전이 다르므로 **eye 전용 가상환경**에 설치하세요.
저장소 루트의 `requirements.txt`는 skin용입니다.

```powershell
python -m venv eye/.venv
eye/.venv/Scripts/python -m pip install -r eye/requirements-lock.txt
eye/.venv/Scripts/python eye/verify.py
```

Linux/macOS에서는 `eye/.venv/Scripts/python` 대신 `eye/.venv/bin/python`을 사용합니다.
아래 `python` 명령은 eye 환경의 Python을 가리킵니다.
다른 운영체제에서의 수치 일치는 별도 확인이 필요합니다.

## 실행

skin과 같은 `components / canonical_smiles / amount_pct` JSON 형식을 받습니다.

```bash
python eye/predict.py --input eye/examples/single_ingredient.json
python eye/predict.py --input eye/examples/two_component_formulation.json
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
python eye/predict.py --input eye/examples/two_component_formulation.json --output eye_result.json
```

원본 코드의 벡터화 CSV 입력도 지원합니다. `feature_names.json`의 2,265개 열을 포함해야 하며,
열 순서는 이름으로 정렬합니다. `formulation_id`가 있으면 결과에 보존합니다.

```bash
python eye/predict.py --input input_features.csv --output eye_predictions.csv
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
| 판정 임계값 | 0.4814867474694138 |

fingerprint는 입력 분자 전체, descriptor는 가장 큰 분자 조각으로 계산합니다.
특징 순서·전처리·모델·임계값은 체크포인트에 함께 저장되어 있습니다.

- `eye_A_score`: 양성 클래스에 대한 모델 점수
- `eye_A_prediction`: 점수가 `decision_threshold` 이상이면 1, 미만이면 0
- `decision_threshold`: 저장된 고정 판정 임계값
- JSON에는 판정 의미, 사용 성분 수, 명시한 함량 합도 포함합니다.

`pipeline.predict()`의 기본 임계값 0.5 대신 동봉된 예측 코드를 사용해야 합니다.
skin의 양성 정의(EPA I·II·III)와 eye의 양성 정의(EPA I·II)는 다릅니다.
점수는 보정된 실제 자극 확률이 아니며, 음성이 모든 눈 자극의 부재를 뜻하지 않습니다.

## 재현검사

```bash
python eye/verify.py
```

파일 SHA-256, 고정 의존성 버전, 체크포인트와 메타데이터·특징 순서의 일치를 확인합니다.
원본에서 저장한 가상 입력 6개의 점수·판정을 대조하고, 별도 임시 폴더에서 CSV와 JSON 예측을 실행합니다.
JSON 예제 2개와 잘못된 JSON 입력 6개의 거부도 확인합니다.
검사에는 학습 폴더가 필요하지 않습니다. 이 검사는 소프트웨어 실행 재현검사이며 예측 성능 평가는 아닙니다.

모델 바이너리 SHA-256:
`d71394e691ac5072e4ce900a53b47ddbb65c8685961fe2c9536411acfbbc58a2`

원본 모델·특징 계산·점수 계산은 유지하고, skin과 같은 JSON 입력을 위한 CLI를 추가했습니다.
`metadata.json`의 학습 자료 해시는 출처 기록이며, 해당 자료는 예측 실행에 필요하지 않습니다.

## 파일 구성

```text
eye/
  .gitattributes
  README.md
  requirements-lock.txt
  eye_A_LR_wmean.joblib
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
