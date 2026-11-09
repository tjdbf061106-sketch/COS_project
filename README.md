# COS Project — Skin / Eye 최종 모델

혼합물의 피부·눈 자극성을 예측하는 **최종 모델 실행 패키지**입니다.
`skin/`과 `eye/`에 최종 모델, 예측 코드, 예제와 실행 재현검사를 제공합니다.
학습 데이터·학습 코드·비교실험·외부 검증 산출물·앱·백업은 포함하지 않습니다.
재현검사는 저장된 모델의 예측 동작을 확인하며 전체 재학습이나 화장품 성능 검증은 아닙니다.

| 구분 | Skin | Eye |
|---|---|---|
| 최종 모델 | RandomForest | LogisticRegression |
| 성분 집계 | 함량 가중평균 | 함량 가중평균 |
| 양성 라벨 | EPA I·II·III | EPA I·II |
| 의존성 | `requirements.txt` | `eye/requirements-lock.txt` |
| 검증 Python | 3.13.12 | 3.14.6 |
| 실행검사 | `python skin/verify.py` | `python eye/verify.py` |

**두 패키지는 NumPy·RDKit 버전이 다르므로 별도 가상환경에서 사용하세요.**
루트 `requirements.txt`는 기존 skin 전용입니다.

## Eye 실행 안내

[Eye 설치·입력 형식·출력 해석·재현검사](eye/README.md)를 참고하세요.
Eye 환경을 설치한 후 저장소 루트에서 실행합니다.

```bash
python eye/predict.py --input eye/examples/single_ingredient.json
python eye/predict.py --input eye/examples/two_component_formulation.json
python eye/verify.py
```

## Skin 실행 안내

NTP ICE 혼합물 기반 최종 피부자극성 RandomForest 모델입니다.
성분별 SMILES와 함량(%)을 입력하면 제형의 예측점수와 이진 판정을 반환합니다.

### 설치

검증 환경: Windows / Python **3.13.12**. 저장소 루트에서 실행합니다. 다른 환경 및 새 가상환경에서의 설치는 별도 검증이 필요합니다.

```bash
python -m pip install -r requirements.txt
```

저장 모델은 scikit-learn 버전에 영향을 받으므로 지정된 의존성 버전을 사용하세요. `joblib` 파일은 신뢰하는 출처의 파일만 로드해야 합니다.

### 실행

```bash
python skin/predict.py --input skin/examples/single_ingredient.json
python skin/predict.py --input skin/examples/two_component_formulation.json
```

다른 위치의 체크포인트를 명시하려면 다음과 같이 실행합니다.

```bash
python skin/predict.py --input input.json --checkpoint skin/skin_rf_checkpoint.joblib
```

#### 입력 형식

```json
{
  "components": [
    {
      "component_id": "ingredient_1",
      "name": "Ethanol",
      "canonical_smiles": "CCO",
      "amount_pct": 5.0
    },
    {
      "component_id": "ingredient_2",
      "name": "Water",
      "canonical_smiles": "O",
      "amount_pct": 95.0
    }
  ]
}
```

- `canonical_smiles`: 실제 입력 원료를 나타내는 SMILES. 원료명으로 구조를 자동 검색하지 않습니다.
- `amount_pct`: 성분 함량(%). `5.0`은 5%입니다. 0~100의 유한한 숫자를 명시하세요.
- `name`, `component_id`: 성분 식별·경고 표시용 값입니다.
- 분포형 원료(UVCB 등)를 임의의 단일 구조로 바꾸면 실제 원료를 제대로 표현하지 못할 수 있습니다.
- 위 예시는 입력 형식 설명용이며 안전한 처방이나 사용 권고가 아닙니다.

#### 출력 해석

| 필드 | 의미 |
|---|---|
| `probability_class1` | 양성 클래스에 대한 모델 예측점수 |
| `threshold` | 고정 판정 임계값: 0.33 |
| `predicted_label` | 점수가 임계값 이상이면 1, 미만이면 0 |
| `predicted_label_meaning` | 판정의 의미 |
| `n_components_used` | 구조 계산에 사용된 성분 수 |
| `n_components_skipped` | 구조가 없거나 해석되지 않아 제외된 성분 수 |
| `note` | 결과의 적용 한계 안내 |

라벨은 **1 = EPA Category I·II·III**, **0 = EPA Category IV**입니다. 0은 모든 사용자에게 안전하다는 뜻이 아닙니다. 예측점수는 자극 강도나 개인의 실제 발병확률로 해석하면 안 됩니다.

### 모델 구성

| 항목 | 내용 |
|---|---|
| 모델 | RandomForest |
| 성분 집계 | 함량 가중평균(wmean) |
| 구조 특징 | AromaticProportion, RDKit descriptor, Morgan fingerprint |
| 농도 특징 | 구조 계산에 사용한 성분의 함량 합 `resolved_pct` |
| 입력 차원 | 2,267 |
| 저장된 특징 필터 적용 후 | 524 |
| 판정 임계값 | 0.33 |

descriptor는 가장 큰 분자 조각을 기준으로 계산하고, fingerprint는 염을 포함한 입력 구조를 사용합니다. 특징 순서와 선택 마스크는 체크포인트에 저장되어 있습니다. 이 패키지에서 모델을 재학습하지 않습니다.

### 검증

```bash
python skin/verify.py
```

체크포인트 SHA-256과 예제 2개의 저장된 예상 출력을 검사합니다. 제출 패키지를 준비할 때 원본 추론 코드와 예측 일치를 확인했습니다. 이는 **패키지 실행 재현 검사**이며 화장품에서의 예측 성능 검증은 아닙니다.

### 입력 처리의 알려진 한계

기존 모델과의 추론 동작을 보존했으므로 앱에서 연결할 때 다음을 별도로 검증해야 합니다.

- 함량이 누락되거나 `null`이면 현재 코드는 1%로 처리합니다. **실제 사용에서는 함량을 반드시 명시**하세요.
- 성분 함량의 총합은 검증하지 않습니다. 입력 단계에서 단위와 합계를 확인하세요.
- 구조 미해결 성분은 제외될 수 있습니다. 제외가 발생하면 JSON 앞에 경고 문장이 출력됩니다. 출력 전체가 항상 순수 JSON인 것은 아닙니다.
- 사용 가능한 성분이 없으면 오류가 발생합니다.
- 사용 성분의 함량이 모두 0이면 균등 가중으로 집계하는 기존 동작이 있습니다. 앱에서는 이러한 입력을 거부하는 것이 적절합니다.

### 연구 범위

이 모델의 개발 목적은 혼합물의 피부자극성 예측입니다. **화장품 도메인의 안전성, 알레르기, 아토피 악화 또는 질환별 사용 적합성이 입증된 모델은 아닙니다.** 연구용 예측값을 제공하며 진단·처방·제품 사용 허가를 대신하지 않습니다.

### 파일 구성

```text
requirements.txt
skin/
  predict.py                    # 추론 실행 코드
  skin_rf_checkpoint.joblib      # 최종 모델·특징 순서·필터·임계값
  metadata.json                 # 모델 정보와 체크포인트 해시
  verify.py                     # 패키지 재현 검사
  smoke_test_cases.json          # 예제별 예상 출력
  examples/
    single_ingredient.json
    two_component_formulation.json
```
