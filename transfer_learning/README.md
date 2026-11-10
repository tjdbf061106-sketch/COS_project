# 전이학습 — Skin Option A 재보정 (최종)

보고서 *「Skin Option A 재보정 전이학습 · Eye 기존계수 기반 전이학습 — 과정과 결과」*(2026-11-10)에 실린
**skin 쪽 최종 전이학습**입니다. 중간 시도·탐색 실험은 포함하지 않습니다.

**production 모델은 재학습하지 않습니다.** 재학습 대상은 4개 파라미터짜리 작은 보정 head뿐이며,
`skin/skin_rf_checkpoint.joblib`은 실행 전후 SHA-256을 비교해 변경되지 않았음을 스크립트가 직접
단언(assert)합니다.

> **Eye 전이학습은 아직 포함되지 않았습니다.** 해당 실험이 출발점으로 삼은 소스 체크포인트
> (`eye_A_LR_wmean.joblib`)가 현재 저장소에 없기 때문입니다. 지금의 `eye/model/eye_A_final.joblib`은
> 같은 673행·같은 하이퍼파라미터로 적합됐지만 평가 설계가 바뀐(평가 606행 → 673행) 별도의 refit이고,
> 임계값과 파일 해시가 다릅니다. 두 모델의 계수가 실제로 동일한지 확인한 뒤에 추가할 예정입니다.

## 결과 요약

| 구분 | n | MCC | AUC | TN/FP/FN/TP |
|---|---|---|---|---|
| Option A raw (frozen skin_rf 그대로 적용) | 41 | 0.5684 | 0.8478 | 17/6/3/15 |
| **Option A + 농도 + HLB 재보정 (최종)** | 41 | **0.6563** | **0.9046** | 19/4/3/15 |

## 폴더 구성

```text
transfer_learning/
  requirements.txt
  skin_option_a_recalibration/
    run_skin_option_a_recalibration_transfer.py   # 전이학습 + bootstrap 전체 재현
    data/lechuga_external_validation_results.csv  # 입력(frozen skin_rf의 Option A 출력 41행)
    results/                                      # 보고서에 실린 산출물
```

`results/`의 파일은 아래 실행으로 그대로 덮어쓰여 재생성됩니다.

## 실행

저장소 루트에서 실행합니다. RDKit은 필요 없습니다(원 실험 검증 환경 Python 3.13.12).

```bash
python -m pip install -r transfer_learning/requirements.txt
python transfer_learning/skin_option_a_recalibration/run_skin_option_a_recalibration_transfer.py
```

bootstrap은 모델을 다시 적합하지 않고 저장된 OOF 점수만 재표본하며, 시드가 고정돼 있어(seed=7, B=5,000)
보고서의 신뢰구간 수치가 그대로 재현됩니다.

## 방법

frozen skin_rf의 Option A 확률 출력을 **출발점(앵커)** 으로 두고, Lechuga 2025 원 논문이 핵심으로 다루는
계면활성제 물성(혼합물 HLB)과 농도만 공변량으로 더해 미세 재보정합니다.

```
logit(p) = a·logit(frozen 점수) + b·농도(표준화) + c·HLB(표준화) + d
loss     = 균형 로지스틱 손실 + 0.5·||(a,b,c,d) − (1,0,0,0)||²
```

앵커 `(1,0,0,0)`은 "보정하지 않으면 raw Option A 출력과 완전히 같다"는 뜻이고, 정규화가 데이터를 압도하지
않는 만큼만 공변량 반영을 허용합니다. 구조 조합(11그룹) 단위 LeaveOneGroupOut으로 41행 전체 OOF 예측을
얻었습니다. HLB가 보고되지 않은 4개 구조는 **학습 fold의 평균**으로만 결측 대체합니다.

데이터는 `cosmetic_validation/lechuga_external_validation_results.csv`(10구조 조합, 11개 그룹, 41행,
양성 18 / 음성 23)입니다.

끼워맞추기로 보이지 않도록 공변량을 하나씩 더하는 4단계를 전부 실행하고 `results/metrics.csv`에 모두
남깁니다 — 최종 결과만 골라 제시한 것이 아닙니다.

| 단계 | MCC | AUC | 균형정확도 | TN | FP | FN | TP |
|---|---|---|---|---|---|---|---|
| raw frozen (원래 Option A) | 0.5684 | 0.8478 | 0.7862 | 17 | 6 | 3 | 15 |
| + 농도 | 0.5577 | 0.8466 | 0.7802 | 18 | 5 | 4 | 14 |
| + HLB | 0.6115 | 0.8913 | 0.8080 | 18 | 5 | 3 | 15 |
| **+ 농도 + HLB (최종)** | **0.6563** | **0.9046** | **0.8297** | 19 | 4 | 3 | 15 |

11개 구조그룹 복원추출 5,000회에서 최종 단계 MCC 95% 신뢰구간은 **[0.307, 0.892]**(중앙값 0.646),
raw 대비 개선되는 재표본 비율은 **90.5%**, 개선폭 중앙값 0.091입니다. 농도만 단독으로 더했을 때는 개선
방향조차 불확실했고(44.4%), HLB를 더한 뒤부터 개선 쪽으로 기울었습니다(65.1%) — 아무 변수나 더해서 생긴
우연이 아니라 HLB라는 특정 물성이 꾸준히 기여한 결과로 해석됩니다.

## 산출물

| 파일 | 내용 |
|---|---|
| `results/metrics.csv` | 4단계 전부의 MCC/AUC/균형정확도/혼동행렬 |
| `results/predictions.csv` | 41행 입력 + 단계별 OOF 예측 |
| `results/fold_log.csv` | fold별 테스트 그룹과 적합된 계수 θ |
| `results/protocol.json` | 프로토콜·그룹 목록·체크포인트 해시 전후 비교 |
| `results/bootstrap_ci.csv` | 단계별 MCC/AUC bootstrap 신뢰구간 |
| `results/bootstrap_paired_delta.csv` | raw 대비 짝지은 MCC 차이와 개선 비율 |

## 한계 — 인용 전 반드시 함께 읽을 것

- **탐색적 결과입니다.** 11구조그룹·41행이라는 자료 규모가 작아 신뢰구간이 넓습니다.
  production 성능 수치로 인용하지 않습니다.
- 최종 단계의 MCC 신뢰구간 하한도 0에 가깝습니다 — 0을 완전히 배제하지는 못하며, 자료가 더 모이기 전까지
  이 개선폭을 확정된 수치로 단정할 수 없습니다.
- **엔드포인트가 다릅니다.** 외부평가 라벨(Zein Number ≥ 200)은 production skin_rf의 학습 라벨
  (EPA Classification)과 다른 엔드포인트입니다. Lechuga 원자료에 EPA Classification이 없어, 데이터를 더
  모아도 새 1차 측정 없이는 이 불일치가 해소되지 않습니다. 이 실험은 Option A의 이 한계를 그대로 물려받습니다.
- `joblib` 파일은 신뢰하는 출처의 파일만 로드하세요.
