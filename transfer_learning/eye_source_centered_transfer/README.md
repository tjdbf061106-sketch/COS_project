# Eye 기존계수 기반 전이학습

673행 전체를 그룹 교차검증으로 평가한 Eye A 최종 모델(`eye_A_final.joblib`)을 출발점으로,
Gettings 1996 제형의 부분 조성에 맞춰 계수와 절편을 미세 조정한 재구성 실험입니다.
기반 모델의 imputer/scaler는 고정하며, 원본 체크포인트는 변경하지 않습니다.

## 결과

Gettings 1996의 16제형(양성 11 / 음성 5), 동일 부분특징 15그룹에 대한
leave-one-group-out OOF 성능입니다. 라벨은 원액 in vivo EPA I/II=1, III/IV=0입니다.

| 구분 | 적중 | MCC | AUC | 균형정확도 | TN/FP/FN/TP |
|---|---|---|---|---|---|
| 기존 Eye A 고정 | 11/16 | 0.0000 | 0.6909 | 0.5000 | 0/5/0/11 |
| **기존계수 기반 전이학습** | **14/16** | **0.7125** | **0.7636** | **0.8000** | **3/2/0/11** |
| 0 기준 대조군 | 14/16 | 0.7125 | 0.7818 | 0.8000 | 3/2/0/11 |

전이학습의 정확도는 **87.5%**입니다. 0 기준 대조군도 같은 MCC를 얻었으므로,
이 자료만으로 기존 계수를 출발점으로 삼은 추가 이점이 확인되지는 않았습니다.
15그룹 bootstrap 5,000회 중 두 클래스가 모두 있는 4,988회에서
MCC 95% 백분위 구간은 **[0.000, 1.000]**, AUC 구간은 **[0.333, 1.000]**입니다.

## 방법

25개 후보 중 모든 함량이 숫자이고 합계가 100±0.11%인 16개를 사용했습니다.
13개 성분의 고정 매핑으로 Morgan 2,048개와 RDKit descriptor 217개를 계산하고,
매핑된 성분의 함량 가중평균으로 2,265개 특징을 만듭니다.
매핑되지 않은 성분은 제외하며 누락 함량은 `coverage_audit.json`에 기록합니다.

```text
z        = 기존 Eye A의 고정 imputer/scaler로 변환한 특징
logit(p) = w·z + b
loss     = mean(클래스 균형 가중 logistic loss)
           + 0.5·λ·||(w,b) − (w_source,b_source)||²
```

λ=1이며 절편에도 벌점을 적용합니다. 클래스 가중치는 매 학습 fold에서 다시 계산하고,
전이학습 판정 임계값은 0.5로 고정합니다. 고정 기반 모델의 임계값은
저장된 0.48345327423625106을 사용합니다. 동일한 부분특징을 가진 행은 같은 그룹에 묶습니다.

OOF 평가 후 16행 전체로 예측용 `eye_transfer_final.joblib`을 별도 학습합니다.
이 최종 파일로 학습 제형을 다시 예측한 값은 OOF 성적과 구분합니다.
실제 학습 목적함수는 `common.py`에 있으며, 저장된 sklearn 객체의 `C` 등은
기반 모델에서 상속된 추론 컨테이너 설정입니다.

## 재현

저장소 루트에서 **Eye 전용 환경**으로 실행합니다. 확인 환경은 Windows / Python 3.14.6이며,
Skin과 NumPy 버전이 다르므로 `transfer_learning/requirements.txt`와 함께 설치하지 않습니다.
학습·예측에는 인터넷이나 개인 PC의 원본 경로가 필요하지 않습니다.

```bash
python -m pip install -r transfer_learning/eye_source_centered_transfer/requirements.txt
python transfer_learning/eye_source_centered_transfer/verify.py
python transfer_learning/eye_source_centered_transfer/run_eye_source_centered_transfer.py
python transfer_learning/eye_source_centered_transfer/verify.py --output-dir transfer_learning/eye_source_centered_transfer/reproduced
```

첫 검사는 공개된 입력·모델 해시, 특징 계산, 지표와 그룹 분리를 확인합니다.
학습 명령은 `reproduced/`에 30개 fold 모델, OOF 예측, bootstrap과 전체 재학습 모델을 생성합니다.
마지막 검사는 저장된 `results/`와 재실행의 16개 예측 점수·지표를 대조하고
30개 fold 모델을 다시 불러옵니다. 공개 준비 시 점수 최대 차이 **0.0**을 확인했습니다.
bootstrap 시드는 20261110이며 저장된 OOF 점수를 재표본하고 모델은 재학습하지 않습니다.

이미 실행한 폴더를 덮어쓰지 않습니다. 다시 실행하려면
`--output-dir transfer_learning/eye_source_centered_transfer/reproduced_2`처럼 새 경로를 지정합니다.
검증에 `assert`를 사용하므로 Python의 `-O` 옵션을 사용하지 마세요.
새 가상환경 설치와 다른 OS·패키지 버전에서의 일치는 별도로 확인해야 합니다.

### 예측

```bash
python transfer_learning/eye_source_centered_transfer/predict.py --input transfer_learning/eye_source_centered_transfer/examples/CTFA1996_HZT.json
```

입력은 `components`에 `name`과 `amount_pct`를 담은 JSON입니다.
`data/mapping.json`의 이름과 별칭만 사용하며, 매핑된 양수 함량 성분이 없으면 거부합니다.
출력은 점수, 0/1 판정, 임계값과 성분별 매핑·누락 내역입니다.

## 구성

```text
eye_source_centered_transfer/
  run_eye_source_centered_transfer.py  # 특징 생성 + 15그룹 평가 + 전체 재학습 + bootstrap
  common.py / predict.py / verify.py
  requirements.txt / requirements-lock.txt
  data/                               # 16제형, 후보 선정 기록, 매핑·학습 조건
  source_model/                       # 673행 전체 평가 버전의 기반 모델·메타데이터
  results/                            # 아래 참조 산출물
  examples/                           # 실행 예제
```

| 파일 | 내용 |
|---|---|
| `results/metrics.csv`, `metrics.json` | 전이학습·대조군·기반 모델의 지표 |
| `results/predictions.csv` | 제형 ID, 라벨, 그룹과 16행 OOF 예측 |
| `results/fold_log.json` | 30개 적합의 학습·시험 ID와 수렴 기록 |
| `results/bootstrap_ci.json` | 그룹 재표본의 불확실성 구간 |
| `results/protocol.json` | 고정한 학습·평가 조건과 기반 모델 해시 |
| `results/eye_transfer_final.joblib`, `metadata.json` | 16행 전체로 학습한 예측용 모델 |
| `results/refit_predictions_NOT_validation.csv` | 전체 재학습 동작 확인용 예측 |
| `results/coverage_audit.json` | 부분 조성 매핑·누락 기록 |
| `input_manifest.json`, `source_manifest.json`, `checksums.json` | 재현 입력·참조 결과·공개 파일 해시 |

입력으로 쓰지 않는 보고서 PDF, 과거 이미지, 백업, 중복 fold 모델은 포함하지 않았습니다.
재현 범위는 제공된 추출 입력과 고정 매핑에서 특징·학습·평가를 다시 계산하는 것입니다.
원자료 출처는 [ICCVAM Appendix B4 배합표](https://ntp.niehs.nih.gov/sites/default/files/iccvam/docs/ocutox_docs/ocubrd/hetcam/hetcamappb.pdf)와
[Appendix D5 원액 EPA 등급](https://ntp.niehs.nih.gov/sites/default/files/iccvam/docs/ocutox_docs/ocubrd/hetcam/hetcamappd5.pdf)이며,
성분별 PubChem 조회 주소와 고정 구조는 `data/mapping.json`에 있습니다.

## 해석 범위

원본 전이학습의 성분 매핑표와 fold 모델이 없어 새로 재구성한 결과입니다.
이 패키지는 **14/16 결과의 재현**을 제공하며, 과거 그림의 13/16 결과 복구를 뜻하지 않습니다.
16제형과 기반 학습 673행의 중복을 배제하지 못했으므로 독립 외부검증이 아닙니다.
물 이외에 구조로 표현된 함량은 제형별 0~6.15%로 주요 성분의 누락이 크며,
모델 점수는 보정된 실제 자극 확률이나 제품의 안전성 판정이 아닙니다.
