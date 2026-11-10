# Skin Option A 재보정 전이학습

frozen skin_rf의 Option A 출력을 출발점으로 삼아, 계면활성제 혼합물의 농도와 HLB를 더해 미세 재보정한
전이학습입니다. production 체크포인트(`skin/skin_rf_checkpoint.joblib`)는 재학습하지 않으며, 스크립트가
실행 전후 SHA-256을 비교해 무결성을 확인합니다.

## 결과

Lechuga 2025 계면활성제 Zein 자료(10구조 조합 · 11그룹 · 41행, 양성 18 / 음성 23)에 대해
구조 조합 단위 LeaveOneGroupOut으로 얻은 OOF 성능입니다.

| 구분 | MCC | AUC | 균형정확도 | TN/FP/FN/TP |
|---|---|---|---|---|
| Option A raw (frozen skin_rf) | 0.5684 | 0.8478 | 0.7862 | 17/6/3/15 |
| **+ 농도 + HLB 재보정 (최종)** | **0.6563** | **0.9046** | **0.8297** | 19/4/3/15 |

재보정으로 MCC는 0.568 → **0.656**, AUC는 0.848 → **0.905**로 향상되었습니다.

### 공변량 단계별 기여

| 단계 | MCC | AUC | 균형정확도 |
|---|---|---|---|
| raw frozen (원래 Option A) | 0.5684 | 0.8478 | 0.7862 |
| + 농도 | 0.5577 | 0.8466 | 0.7802 |
| + HLB | 0.6115 | 0.8913 | 0.8080 |
| **+ 농도 + HLB (최종)** | **0.6563** | **0.9046** | **0.8297** |

HLB를 더한 시점부터 성능이 뚜렷하게 올라갑니다. 11개 구조그룹을 5,000회 복원추출한 그룹 bootstrap에서
최종 모델은 **재표본의 90.5%에서 raw 대비 개선**되었고, 개선폭 중앙값은 0.091, MCC 95% 신뢰구간은
[0.307, 0.892](중앙값 0.646)입니다.

## 방법

```
logit(p) = a·logit(frozen 점수) + b·농도(표준화) + c·HLB(표준화) + d
loss     = 균형 로지스틱 손실 + 0.5·||(a,b,c,d) − (1,0,0,0)||²
```

앵커 `(1,0,0,0)`은 "보정하지 않으면 raw Option A 출력과 동일"을 뜻하며, 데이터가 뒷받침하는 만큼만
공변량 반영을 허용합니다. 재학습 대상은 이 4개 파라미터뿐입니다. HLB가 보고되지 않은 4개 구조는
학습 fold의 평균으로만 결측 대체해 정보 누수를 차단했습니다.

평가 라벨은 Zein Number ≥ 200 기준의 이진 라벨입니다.

## 재현

저장소 루트에서 실행합니다. RDKit은 필요하지 않습니다. (검증 환경: Windows / Python 3.13.12)

```bash
python -m pip install -r transfer_learning/requirements.txt
python transfer_learning/skin_option_a_recalibration/run_skin_option_a_recalibration_transfer.py
```

시드가 고정되어(seed=7, B=5,000) 위 표의 수치가 그대로 재현됩니다. bootstrap은 모델을 다시 적합하지 않고
저장된 OOF 점수만 재표본합니다. 실행하면 `results/`의 파일이 동일한 내용으로 재생성됩니다.

## 구성

```text
transfer_learning/
  requirements.txt
  skin_option_a_recalibration/
    run_skin_option_a_recalibration_transfer.py   # 전이학습 + bootstrap 전체 재현
    data/lechuga_external_validation_results.csv  # 입력 41행
    results/                                      # 아래 산출물
```

| 파일 | 내용 |
|---|---|
| `results/metrics.csv` | 단계별 MCC / AUC / 균형정확도 / 혼동행렬 |
| `results/predictions.csv` | 41행 입력과 단계별 OOF 예측 |
| `results/fold_log.csv` | fold별 테스트 그룹과 적합된 계수 θ |
| `results/protocol.json` | 프로토콜, 그룹 목록, 체크포인트 해시 대조 |
| `results/bootstrap_ci.csv` | 단계별 MCC / AUC bootstrap 신뢰구간 |
| `results/bootstrap_paired_delta.csv` | raw 대비 짝지은 MCC 차이와 개선 비율 |
