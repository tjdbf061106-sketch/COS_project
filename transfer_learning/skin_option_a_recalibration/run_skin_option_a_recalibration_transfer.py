# -*- coding: utf-8 -*-
"""Skin Option A(frozen skin_rf, 10구조/41행 Lechuga 외부적용) 추가 실험:
frozen skin_rf의 확률 출력을 '출발점(anchor)'으로 삼아, 같은 41행 안에서
농도(concentration_pct) 정보를 더해 미세 보정(재적합)하는 게 도움이 되는지 확인.

방법은 eye의 source_centered_transfer와 동일한 수식(앵커된 L2 로지스틱 회귀):
  logit(p) = a*logit(frozen_prob) + b*conc_z + c
  loss = 가중 BCE + 0.5*||(a,b,c)-(1,0,0)||^2
anchor=(1,0,0) -> 데이터가 없으면 그대로 frozen Option A 출력과 동일.
LeaveOneGroupOut(구조 조합 단위, 11그룹)으로 OOF 평가. 재학습 대상은 이 새
3-파라미터 head뿐이며 skin_rf_checkpoint.joblib은 건드리지 않음(해시로 확인).
"""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit
from sklearn.metrics import (
    balanced_accuracy_score,
    confusion_matrix,
    matthews_corrcoef,
    roc_auc_score,
)
from sklearn.model_selection import LeaveOneGroupOut

HERE = Path(__file__).resolve().parent
R = HERE.parents[1]            # COS_project repository root
D = HERE / "data"
O = HERE / "results"
O.mkdir(exist_ok=True)

# production 체크포인트는 읽기 전용으로 해시만 확인한다(재학습 대상이 아님).
ck_path = R / "skin" / "skin_rf_checkpoint.joblib"
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
before = digest(ck_path)

d = pd.read_csv(D / "lechuga_external_validation_results.csv")
d["structure_group"] = d.product1.fillna("") + d.product2.apply(lambda v: ("|" + v) if pd.notna(v) else "")
y = d.true_binary.to_numpy(dtype=int)
frozen_p = d.pred_proba.to_numpy(dtype=float)
frozen_logit = logit(np.clip(frozen_p, 1e-6, 1 - 1e-6))
conc = d.concentration_pct.to_numpy(dtype=float)
groups = d.structure_group.to_numpy()

assert len(set(groups)) >= 2
n_groups = len(set(groups))


def fit_anchor(Z, t, center, lam=1.0):
    counts = np.bincount(t, minlength=2)
    assert counts.min() > 0
    weight = len(t) / (2 * counts[t])

    def fun(theta):
        logits = Z @ theta
        delta = theta - center
        loss = np.dot(weight, np.logaddexp(0, logits) - t * logits) + 0.5 * lam * np.dot(delta, delta)
        grad = Z.T @ (weight * (expit(logits) - t)) + lam * delta
        return loss, grad

    opt = minimize(fun, center.copy(), jac=True, method="L-BFGS-B",
                    options={"maxiter": 5000, "ftol": 1e-12, "gtol": 1e-7})
    if not opt.success:
        raise RuntimeError(opt.message)
    return opt.x


hlb = d.HLB_compost.to_numpy(dtype=float)

n = len(d)
oof = {"frozen_only_anchor": np.full(n, np.nan), "frozen_plus_conc": np.full(n, np.nan),
       "frozen_plus_hlb": np.full(n, np.nan), "frozen_plus_conc_hlb": np.full(n, np.nan)}
folds = np.full(n, -1)
fold_log = []
logo = LeaveOneGroupOut()
for fold, (tr, te) in enumerate(logo.split(d, y, groups)):
    assert set(groups[tr]).isdisjoint(groups[te])
    if len(np.unique(y[tr])) < 2:
        continue  # cannot fit a balanced-weight logistic loss without both classes in train
    folds[te] = fold
    conc_mean, conc_std = conc[tr].mean(), conc[tr].std() if conc[tr].std() > 0 else 1.0
    conc_z = (conc - conc_mean) / conc_std

    # model 1: anchor-only re-centering of the frozen score alone (no new covariate)
    Z1 = np.column_stack([frozen_logit, np.ones(n)])
    theta1 = fit_anchor(Z1[tr], y[tr], center=np.array([1.0, 0.0]))
    oof["frozen_only_anchor"][te] = expit(Z1[te] @ theta1)

    # model 2: frozen score + concentration, anchored to "trust frozen, ignore conc by default"
    Z2 = np.column_stack([frozen_logit, conc_z, np.ones(n)])
    theta2 = fit_anchor(Z2[tr], y[tr], center=np.array([1.0, 0.0, 0.0]))
    oof["frozen_plus_conc"][te] = expit(Z2[te] @ theta2)

    # model 3: frozen score + HLB_compost (Lechuga's own surfactant-HLB covariate), anchored
    # train-only mean imputation for the 4 rows with no reported HLB (SLES/glutamates/Zn coco-sulfate)
    hlb_train_mean = np.nanmean(hlb[tr])
    hlb_filled = np.where(np.isnan(hlb), hlb_train_mean, hlb)
    hlb_mean, hlb_std = hlb_filled[tr].mean(), hlb_filled[tr].std() if hlb_filled[tr].std() > 0 else 1.0
    hlb_z = (hlb_filled - hlb_mean) / hlb_std
    Z3 = np.column_stack([frozen_logit, hlb_z, np.ones(n)])
    theta3 = fit_anchor(Z3[tr], y[tr], center=np.array([1.0, 0.0, 0.0]))
    oof["frozen_plus_hlb"][te] = expit(Z3[te] @ theta3)

    # model 4: frozen score + concentration + HLB_compost
    Z4 = np.column_stack([frozen_logit, conc_z, hlb_z, np.ones(n)])
    theta4 = fit_anchor(Z4[tr], y[tr], center=np.array([1.0, 0.0, 0.0, 0.0]))
    oof["frozen_plus_conc_hlb"][te] = expit(Z4[te] @ theta4)

    fold_log.append({"fold": fold, "test_group": groups[te][0], "train_rows": len(tr), "test_rows": len(te),
                      "theta_frozen_only": theta1.tolist(), "theta_frozen_plus_conc": theta2.tolist(),
                      "theta_frozen_plus_hlb": theta3.tolist(), "theta_frozen_plus_conc_hlb": theta4.tolist()})

covered = folds >= 0
print(f"{covered.sum()}/{n} rows covered by a fold whose train split had both classes "
      f"({n - covered.sum()} rows dropped: their group's removal left a single-class train split).")


def metrics(y_true, p, threshold=0.5):
    pred = (p >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    return {
        "n": int(len(y_true)), "positive_n": int(y_true.sum()), "threshold": threshold,
        "MCC": float(matthews_corrcoef(y_true, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, pred)),
        "ROC_AUC": float(roc_auc_score(y_true, p)) if len(np.unique(y_true)) == 2 else None,
        "TN": int(tn), "FP": int(fp), "FN": int(fn), "TP": int(tp),
    }


rows = []
rows.append({"model": "option_a_raw_frozen", **metrics(y, frozen_p)})
for name in ["frozen_only_anchor", "frozen_plus_conc", "frozen_plus_hlb", "frozen_plus_conc_hlb"]:
    mask = covered
    rows.append({"model": name, **metrics(y[mask], oof[name][mask])})

metrics_df = pd.DataFrame(rows)
metrics_df.to_csv(O / "metrics.csv", index=False)

out = d.copy()
out["fold"] = folds
out["frozen_only_anchor"] = oof["frozen_only_anchor"]
out["frozen_plus_conc"] = oof["frozen_plus_conc"]
out["frozen_plus_hlb"] = oof["frozen_plus_hlb"]
out["frozen_plus_conc_hlb"] = oof["frozen_plus_conc_hlb"]
out.to_csv(O / "predictions.csv", index=False, encoding="utf-8-sig")
pd.DataFrame(fold_log).to_csv(O / "fold_log.csv", index=False, encoding="utf-8-sig")

protocol = {
    "status": "exploratory_recalibration_transfer_on_option_a",
    "purpose": "frozen skin_rf의 Option A 출력(10구조/41행)에 '전이학습식' 미세보정(앵커 L2 로지스틱)을 "
               "추가로 걸어봤을 때 raw frozen 적용보다 개선되는지 확인. production 체크포인트는 전혀 재학습하지 않음.",
    "anchor_rationale": "theta anchor=(1,0,...,0) -> 정규화가 데이터를 압도하면 그대로 raw frozen 출력과 동일. "
                        "데이터가 뒷받침하는 만큼만 偏差를 허용(eye의 source_centered_transfer와 동일한 lambda=1 L2 앵커 목적함수).",
    "n_rows": n, "n_groups": n_groups, "groups": sorted(set(groups.tolist())),
    "split": "LeaveOneGroupOut by declared structure combination (product1|product2); folds whose train split "
             "lost a class are excluded from both models' evaluation (reported above).",
    "endpoint_caveat": "Zein Number(ZN>=200) != production EPA Classification; 이 실험도 Option A와 동일한 "
                        "엔드포인트 불일치 한계를 그대로 물려받는다 (endpoint_alignment.json 참조).",
    "protected_hash_before": before,
}
after = digest(ck_path)
protocol["protected_hash_after"] = after
protocol["skin_rf_checkpoint_unchanged"] = before == after
assert before == after
(O / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")

print(metrics_df.to_string(index=False))

# ---- group-level bootstrap CI + paired delta vs raw frozen (B=5000, reuse stored OOF scores, no refit) ----
rng = np.random.default_rng(7)
uniq_groups = np.array(sorted(set(groups.tolist())))
scores_by_model = {"option_a_raw_frozen": frozen_p, **{k: oof[k] for k in oof}}
B = 5000
ci_rows = []
delta_rows = {k: [] for k in ["frozen_only_anchor", "frozen_plus_conc", "frozen_plus_hlb", "frozen_plus_conc_hlb"]}
boot_mcc = {k: [] for k in scores_by_model}
boot_auc = {k: [] for k in scores_by_model}
for b in range(B):
    sample_groups = rng.choice(uniq_groups, size=len(uniq_groups), replace=True)
    idx = np.concatenate([np.flatnonzero(groups == g) for g in sample_groups])
    yb = y[idx]
    if len(np.unique(yb)) < 2:
        continue
    base_pred = (frozen_p[idx] >= 0.5).astype(int)
    base_mcc = matthews_corrcoef(yb, base_pred)
    boot_mcc["option_a_raw_frozen"].append(base_mcc)
    boot_auc["option_a_raw_frozen"].append(roc_auc_score(yb, frozen_p[idx]))
    for name in ["frozen_only_anchor", "frozen_plus_conc", "frozen_plus_hlb", "frozen_plus_conc_hlb"]:
        pb = oof[name][idx]
        valid = np.isfinite(pb)
        if valid.sum() < len(pb) or len(np.unique(yb[valid])) < 2:
            continue
        mcc_b = matthews_corrcoef(yb, (pb >= 0.5).astype(int))
        boot_mcc[name].append(mcc_b)
        boot_auc[name].append(roc_auc_score(yb, pb))
        delta_rows[name].append(mcc_b - base_mcc)

for name in boot_mcc:
    mcc_vals = np.asarray(boot_mcc[name])
    auc_vals = np.asarray(boot_auc[name])
    ci_rows.append({"model": name, "n_valid_resamples": len(mcc_vals),
                     "MCC_median": float(np.median(mcc_vals)),
                     "MCC_p2.5": float(np.percentile(mcc_vals, 2.5)),
                     "MCC_p97.5": float(np.percentile(mcc_vals, 97.5)),
                     "AUC_median": float(np.median(auc_vals)),
                     "AUC_p2.5": float(np.percentile(auc_vals, 2.5)),
                     "AUC_p97.5": float(np.percentile(auc_vals, 97.5))})
pd.DataFrame(ci_rows).to_csv(O / "bootstrap_ci.csv", index=False)

delta_out = []
for name, vals in delta_rows.items():
    vals = np.asarray(vals)
    delta_out.append({"compare": f"{name} - option_a_raw_frozen", "n_valid_resamples": len(vals),
                       "delta_median": float(np.median(vals)),
                       "delta_p2.5": float(np.percentile(vals, 2.5)),
                       "delta_p97.5": float(np.percentile(vals, 97.5)),
                       "frac_resamples_improved": float((vals > 0).mean())})
pd.DataFrame(delta_out).to_csv(O / "bootstrap_paired_delta.csv", index=False)
print(pd.DataFrame(ci_rows).to_string(index=False))
print(pd.DataFrame(delta_out).to_string(index=False))
