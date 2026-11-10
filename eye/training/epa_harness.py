"""Reproducible EPA nested grouped CV; outer outcomes never select parameters."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_score,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedGroupKFold
from threadpoolctl import threadpool_limits

MODELS = ("lr", "rf", "et", "svm", "xgb", "lgbm")
CORE = ("sensitivity", "specificity", "MCC", "ROC-AUC")
ROOT = Path(__file__).resolve().parent
DEFAULT_RUN = "epa-production-20261106-no-catboost"


def _plain(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def hash_json(value):
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_plain,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, default=_plain)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def save_record(path, identity, payload):
    """Completed records are immutable and checksummed; never overwrite evidence."""
    path = Path(path)
    if path.exists():
        existing = load_record(path, identity)
        if hash_json(existing) != hash_json(payload):
            raise ValueError(
                f"Refusing to overwrite different completed record: {path}"
            )
        return
    atomic_json(
        path,
        {
            "identity": identity,
            "payload": payload,
            "payload_sha256": hash_json(payload),
        },
    )


def load_record(path, identity):
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    if record.get("identity") != identity:
        raise ValueError(f"Checkpoint identity mismatch: {path}")
    if record.get("payload_sha256") != hash_json(record["payload"]):
        raise ValueError(f"Checkpoint checksum mismatch: {path}")
    return record["payload"]


def epa_labels(values):
    y = np.asarray(values, dtype=float)
    if y.ndim != 1 or not np.isfinite(y).all() or not np.isin(y, [1, 2, 3, 4]).all():
        raise ValueError("EPA labels must be finite integer values 1,2,3,4")
    return {"A": (y <= 2).astype(int), "B": (y <= 3).astype(int)}


def feature_columns(header):
    fp = [c for c in header if c.startswith("fp_")]
    desc = [c for c in header if c.startswith("desc_")]
    if len(fp) != 2048 or len(desc) != 217 or len(set(fp + desc)) != 2265:
        raise ValueError(
            "Expected exactly 2048 unique fp_* and 217 unique desc_* columns"
        )
    return fp + desc


def load_csv(path):
    df = pd.read_csv(path, low_memory=False)
    cols = feature_columns(df.columns)
    if not {"final_label", "comp_group_id"}.issubset(df.columns):
        raise ValueError("Missing label/group fields")
    epa_labels(df.final_label)
    X = df[cols].apply(pd.to_numeric, errors="raise").to_numpy(dtype=float)
    if np.isinf(X).any():
        raise ValueError("Infinite feature values are forbidden")
    return df, X, cols


def connected_groups(df, endpoint):
    if endpoint not in ("skin", "eye"):
        raise ValueError(endpoint)
    parent = np.arange(len(df))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return int(i)

    for column in (
        ["comp_group_id"] if endpoint == "skin" else ["comp_group_id", "split_group_id"]
    ):
        if column not in df or df[column].isna().any():
            raise ValueError(f"Missing group identifier: {column}")
        seen = {}
        for i, value in enumerate(df[column].astype(str)):
            if not value.strip():
                raise ValueError(f"Empty group identifier: {column}")
            if value in seen:
                a, b = root(i), root(seen[value])
                parent[max(a, b)] = min(a, b)
            else:
                seen[value] = i
    return np.array([root(i) for i in range(len(df))])


def _check_partition(train, test, groups, labels):
    if set(train) & set(test) or set(groups[train]) & set(groups[test]):
        raise ValueError("Train/validation group or row leakage")
    for y in labels.values():
        for idx in (train, test):
            if set(np.unique(y[idx])) != {0, 1}:
                raise ValueError(
                    "Both classes required on each side of every actual fold"
                )


def nested_splits(epa, groups, seed=42):
    epa = np.asarray(epa)
    groups = np.asarray(groups)
    labels = epa_labels(epa)
    folds = []
    for train, test in StratifiedGroupKFold(5, shuffle=True, random_state=seed).split(
        epa, epa, groups
    ):
        _check_partition(train, test, groups, labels)
        inner = []
        for a, b in StratifiedGroupKFold(3, shuffle=True, random_state=seed).split(
            epa[train], epa[train], groups[train]
        ):
            a, b = train[a], train[b]
            _check_partition(a, b, groups, labels)
            inner.append({"train": a.tolist(), "validation": b.tolist()})
        if sorted(i for f in inner for i in f["validation"]) != sorted(train.tolist()):
            raise ValueError(
                "Inner validation does not cover outer training exactly once"
            )
        folds.append({"train": train.tolist(), "test": test.tolist(), "inner": inner})
    if sorted(i for f in folds for i in f["test"]) != list(range(len(epa))):
        raise ValueError("Outer test coverage invalid")
    return folds


def candidate_grid(model):
    if model == "lr":
        values = [
            dict(C=c, solver="lbfgs", max_iter=5000, tol=1e-4)
            for c in (
                0.0001,
                0.0003,
                0.001,
                0.003,
                0.01,
                0.03,
                0.1,
                0.3,
                1,
                3,
                10,
                30,
                100,
                300,
                1000,
                3000,
                10000,
                30000,
                100000,
                300000,
            )
        ]
    elif model in ("rf", "et"):
        values = [
            dict(n_estimators=500, max_depth=None, max_features=f, min_samples_leaf=l)
            for f in ("sqrt", 0.25, 0.5, 0.75)
            for l in (1, 2, 5, 10, 20)
        ]
    elif model == "svm":
        values = [
            dict(kernel="rbf", probability=False, C=c, gamma=g)
            for c in (0.01, 0.1, 1, 10, 100)
            for g in ("scale", 0.0001, 0.001, 0.01)
        ]
    elif model == "xgb":
        values = [
            dict(n_estimators=500, max_depth=d, learning_rate=r)
            for d in (2, 3, 4, 6, 8)
            for r in (0.01, 0.03, 0.1, 0.2)
        ]
    elif model == "lgbm":
        values = [
            dict(n_estimators=500, num_leaves=d, learning_rate=r)
            for d in (7, 15, 31, 63, 127)
            for r in (0.01, 0.03, 0.1, 0.2)
        ]
    elif model == "cat":
        values = [
            dict(iterations=500, depth=d, learning_rate=r)
            for d in (3, 4, 5, 6, 8)
            for r in (0.01, 0.03, 0.1, 0.2)
        ]
    else:
        raise ValueError(model)
    assert len(values) == len({hash_json(v) for v in values}) == 20
    return [
        {"candidate_id": f"{model}-{i:03d}", "params": p} for i, p in enumerate(values)
    ]


def balanced_weights(y):
    y = np.asarray(y)
    if set(np.unique(y)) != {0, 1}:
        raise ValueError("Both binary classes required")
    counts = np.bincount(y.astype(int), minlength=2)
    return len(y) / (2.0 * counts[y.astype(int)])


def build_estimator(model, params):
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    if model == "lr":
        from sklearn.linear_model import LogisticRegression

        est = LogisticRegression(random_state=42, class_weight=None, **params)
    elif model == "svm":
        from sklearn.svm import SVC

        est = SVC(random_state=42, class_weight=None, **params)
    elif model in ("rf", "et"):
        from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier

        est = (RandomForestClassifier if model == "rf" else ExtraTreesClassifier)(
            random_state=42, n_jobs=1, class_weight=None, **params
        )
    elif model == "xgb":
        from xgboost import XGBClassifier

        est = XGBClassifier(
            random_state=42,
            n_jobs=1,
            device="cpu",
            objective="binary:logistic",
            eval_metric="logloss",
            subsample=1,
            colsample_bytree=1,
            **params,
        )
    elif model == "lgbm":
        from lightgbm import LGBMClassifier

        est = LGBMClassifier(
            random_state=42,
            n_jobs=1,
            deterministic=True,
            force_col_wise=True,
            class_weight=None,
            verbosity=-1,
            **params,
        )
    elif model == "cat":
        from catboost import CatBoostClassifier

        est = CatBoostClassifier(
            random_seed=42,
            task_type="CPU",
            thread_count=1,
            verbose=False,
            allow_writing_files=False,
            **params,
        )
    else:
        raise ValueError(model)
    steps = [
        (
            "imputer",
            SimpleImputer(strategy="constant", fill_value=0, keep_empty_features=True),
        )
    ]
    if model in ("lr", "svm"):
        steps.append(("scaler", StandardScaler()))
    steps.append(("model", est))
    return Pipeline(steps)


def fit_weighted(est, X, y):
    weights = balanced_weights(y)
    with threadpool_limits(limits=1), warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        est.fit(X, y, model__sample_weight=weights)
    transformed = est[:-1].transform(X)
    if transformed.shape != X.shape or not np.isfinite(transformed).all():
        raise ValueError(
            "Transformed training matrix must preserve shape and be finite"
        )
    return est


def predict_scores(est, X, model):
    transformed = est[:-1].transform(X)
    if transformed.shape != X.shape or not np.isfinite(transformed).all():
        raise ValueError(
            "Transformed held-out matrix must preserve shape and be finite"
        )
    if list(est.classes_) != [0, 1]:
        raise ValueError("Unexpected estimator class orientation")
    with threadpool_limits(limits=1):
        scores = (
            est.decision_function(X) if model == "svm" else est.predict_proba(X)[:, 1]
        )
    scores = np.asarray(scores, dtype=float)
    if scores.shape != (len(X),) or not np.isfinite(scores).all():
        raise ValueError("Nonfinite or malformed prediction scores")
    return scores


def threshold(scores, y):
    scores, y = np.asarray(scores, dtype=float), np.asarray(y)
    if (
        scores.shape != y.shape
        or not np.isfinite(scores).all()
        or set(np.unique(y)) != {0, 1}
    ):
        raise ValueError("Finite aligned scores and both classes required")
    unique = np.unique(scores)
    if len(unique) < 2:
        raise ValueError("Constant inner scores: no nontrivial threshold")
    P, N = int((y == 1).sum()), int((y == 0).sum())
    best = None
    for a, b in zip(unique[:-1], unique[1:]):
        midpoint = a / 2.0 + b / 2.0
        t = float(midpoint if a < midpoint < b else b)
        pred = scores >= t
        if pred.all() or not pred.any():
            continue
        tp, tn = int(np.sum(pred & (y == 1))), int(np.sum(~pred & (y == 0)))
        fp, fn = N - tn, P - tp
        mcc = (tp * tn - fp * fn) / np.sqrt(float((tp + fp) * P * N * (tn + fn)))
        key = (abs(tp * N - tn * P), -mcc, t)
        if best is None or key < best:
            best = key
    if best is None:
        raise ValueError("No valid interior threshold")
    return best[2]


def compute_metrics(y, scores, predictions):
    y, scores, predictions = (
        np.asarray(y),
        np.asarray(scores, float),
        np.asarray(predictions),
    )
    if (
        y.shape != scores.shape
        or y.shape != predictions.shape
        or not np.isfinite(scores).all()
    ):
        raise ValueError("Invalid metric arrays")
    if set(np.unique(y)) != {0, 1} or not np.isin(predictions, [0, 1]).all():
        raise ValueError("Invalid binary target/predictions")
    cm = confusion_matrix(y, predictions, labels=[0, 1])
    tn, fp, fn, tp = (int(v) for v in cm.ravel())
    return {
        "sensitivity": tp / (tp + fn),
        "specificity": tn / (tn + fp),
        "MCC": float(matthews_corrcoef(y, predictions)),
        "ROC-AUC": float(roc_auc_score(y, scores)),
        "PR-AUC": float(average_precision_score(y, scores)),
        "precision": float(precision_score(y, predictions, zero_division=0)),
        "F1": float(f1_score(y, predictions, zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y, predictions)),
        "confusion_matrix": cm.tolist(),
        "positive_count": tp + fn,
        "negative_count": tn + fp,
    }


def _inner_scores(model, params, X, y, outer_train, inner):
    scores = np.full(len(y), np.nan)
    provenance, aucs = [], []
    for partition in inner:
        a, b = np.array(partition["train"]), np.array(partition["validation"])
        if set(a) & set(b) or not set(a).union(b).issubset(outer_train):
            raise ValueError("Invalid inner fit provenance")
        est = fit_weighted(build_estimator(model, params), X[a], y[a])
        scores[b] = predict_scores(est, X[b], model)
        aucs.append(float(roc_auc_score(y[b], scores[b])))
        provenance.append(
            {**partition, "train_class_counts": np.bincount(y[a], minlength=2).tolist()}
        )
    if not np.isfinite(scores[outer_train]).all():
        raise ValueError("Incomplete inner OOF")
    return {
        "row_ids": list(outer_train),
        "scores": scores[outer_train].tolist(),
        "fold_aucs": aucs,
        "mean_auc": float(np.mean(aucs)),
        "provenance": provenance,
    }


def _environment():
    names = (
        "numpy",
        "pandas",
        "scikit-learn",
        "scipy",
        "xgboost",
        "lightgbm",
        "catboost",
        "threadpoolctl",
    )
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {n: importlib.metadata.version(n) for n in names},
    }


def run_endpoint(endpoint, csv_path, output_dir=None, run_id=None):
    """Execute the selected endpoint combinations with immutable checkpoints."""
    started = time.monotonic()
    df, X, features = load_csv(csv_path)
    labels, groups = epa_labels(df.final_label), connected_groups(df, endpoint)
    splits = nested_splits(df.final_label.to_numpy(), groups)
    grids = {m: candidate_grid(m) for m in MODELS}
    root = Path(output_dir or ROOT).resolve()
    rid = run_id or os.getenv("EPA_RUN_ID", DEFAULT_RUN)
    if not rid or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        for c in rid
    ):
        raise ValueError("run_id must be a filesystem-safe identifier")
    config = {
        "endpoint": endpoint,
        "run_id": rid,
        "input": str(Path(csv_path).resolve()),
        "input_sha256": file_hash(csv_path),
        "code_sha256": file_hash(__file__),
        "environment": _environment(),
        "seed": 42,
        "threads": 1,
        "features": features,
        "grids": grids,
        "splits": splits,
        "groups": groups.tolist(),
        "epa": df.final_label.astype(int).tolist(),
        "threshold_rule": "integer_gap_then_MCC_then_smallest",
        "imputer": "constant_zero",
    }
    identity = hash_json(config)
    out = root / "runs" / rid / endpoint / identity[:16]
    out.mkdir(parents=True, exist_ok=True)
    save_record(out / "config.json", identity, config)
    save_record(out / "splits.json", identity, splits)
    print(
        f"{endpoint}: {len(df)} rows, {len(features)} features; artifacts={out}",
        flush=True,
    )
    rows = []
    context = {}
    try:
        for label, y in labels.items():
            for model in MODELS:
                score_all = np.full(len(y), np.nan)
                pred_all = np.full(len(y), -1, dtype=int)
                fold_metrics = []
                for fold_id, fold in enumerate(splits):
                    context = {
                        "endpoint": endpoint,
                        "label": label,
                        "model": model,
                        "fold": fold_id,
                    }
                    folder = out / label / model / f"fold-{fold_id}"
                    done = folder / "outer.json"
                    tr, te = np.array(fold["train"]), np.array(fold["test"])
                    if done.exists():
                        result = load_record(done, identity)
                    else:
                        candidates = []
                        for candidate in grids[model]:
                            cid = candidate["candidate_id"]
                            context["candidate"] = cid
                            path = folder / "candidates" / f"{cid}.json"
                            if path.exists():
                                result = load_record(path, identity)
                                if result["candidate"] != candidate:
                                    raise ValueError("Candidate checkpoint mismatch")
                            else:
                                result = {
                                    "candidate": candidate,
                                    **_inner_scores(
                                        model,
                                        candidate["params"],
                                        X,
                                        y,
                                        tr,
                                        fold["inner"],
                                    ),
                                }
                                save_record(path, identity, result)
                            candidates.append(result)
                            print(
                                f"{endpoint}/{label}/{model} fold={fold_id+1}/5 {cid} inner_auc={result['mean_auc']:.5f}",
                                flush=True,
                            )
                        selected = min(
                            candidates,
                            key=lambda r: (
                                -r["mean_auc"],
                                r["candidate"]["candidate_id"],
                            ),
                        )
                        # Fresh selected-candidate refits; NEVER use an outer-trained model for inner OOF.
                        oof = _inner_scores(
                            model,
                            selected["candidate"]["params"],
                            X,
                            y,
                            tr,
                            fold["inner"],
                        )
                        t = threshold(oof["scores"], y[tr])
                        save_record(
                            folder / "threshold.json",
                            identity,
                            {"candidate": selected["candidate"], "threshold": t, **oof},
                        )
                        est = fit_weighted(
                            build_estimator(model, selected["candidate"]["params"]),
                            X[tr],
                            y[tr],
                        )
                        scores = predict_scores(est, X[te], model)
                        predictions = (scores >= t).astype(int)
                        result = {
                            "row_ids": te.tolist(),
                            "y_true": y[te].tolist(),
                            "scores": scores.tolist(),
                            "predictions": predictions.tolist(),
                            "threshold": t,
                            "candidate": selected["candidate"],
                            "metrics": compute_metrics(y[te], scores, predictions),
                            "fit_row_ids": tr.tolist(),
                            "train_class_counts": np.bincount(
                                y[tr], minlength=2
                            ).tolist(),
                        }
                        save_record(done, identity, result)
                    if (
                        result["row_ids"] != te.tolist()
                        or result["y_true"] != y[te].tolist()
                    ):
                        raise ValueError("Outer checkpoint row/target mismatch")
                    score_all[te], pred_all[te] = (
                        result["scores"],
                        result["predictions"],
                    )
                    fold_metrics.append(result["metrics"])
                    print(
                        f"DONE {endpoint}/{label}/{model} outer={fold_id+1}/5 elapsed={time.monotonic()-started:.1f}s",
                        flush=True,
                    )
                # Crucial: pool actual held-out predictions with THEIR OWN inner-selected thresholds.
                pooled = compute_metrics(y, score_all, pred_all)
                row = {
                    "endpoint": endpoint,
                    "label": label,
                    "model": model,
                    **pooled,
                    "abs_gap": abs(pooled["sensitivity"] - pooled["specificity"]),
                    "fold_dispersion": {
                        k: float(np.std([r[k] for r in fold_metrics], ddof=1))
                        for k in CORE
                    },
                    "fold_metrics": fold_metrics,
                    "score_semantics": (
                        "uncalibrated_margin"
                        if model == "svm"
                        else "positive_probability"
                    ),
                    "pooled_ranking_caution": "OOF scores come from different fitted models; SVM margins are not cross-fold calibrated.",
                }
                save_record(
                    out / label / model / "oof.json",
                    identity,
                    {
                        "row_ids": list(range(len(y))),
                        "y_true": y.tolist(),
                        "scores": score_all.tolist(),
                        "predictions": pred_all.tolist(),
                        "report": row,
                    },
                )
                rows.append(row)
        save_record(out / "report.json", identity, rows)
        verify_endpoint(out)
        pointer = root / "runs" / rid / f"{endpoint}_completed.json"
        if pointer.exists():
            previous = json.loads(pointer.read_text(encoding="utf-8"))
            if previous["identity"] != identity:
                raise ValueError(
                    "Run ID already points to different completed identity; choose a new run ID"
                )
        else:
            atomic_json(pointer, {"identity": identity, "output_dir": str(out)})
        return {"run_id": rid, "output_dir": str(out), "report": rows}
    except Exception as exc:
        atomic_json(
            out / f"failure-{time.time_ns()}.json",
            {"context": context, "error": repr(exc)},
        )
        raise


def verify_endpoint(path):
    path = Path(path)
    config_envelope = json.loads((path / "config.json").read_text(encoding="utf-8"))
    identity = config_envelope["identity"]
    config = load_record(path / "config.json", identity)
    if hash_json(config) != identity:
        raise ValueError("Config identity mismatch")
    splits = load_record(path / "splits.json", identity)
    if splits != config["splits"]:
        raise ValueError("Split manifest mismatch")
    groups, labels = np.array(config["groups"]), epa_labels(config["epa"])
    rows = load_record(path / "report.json", identity)
    if {(r["label"], r["model"]) for r in rows} != {
        (l, m) for l in labels for m in MODELS
    } or len(rows) != len(labels) * len(MODELS):
        raise ValueError("Incomplete selected-model endpoint report")
    for label, y in labels.items():
        for model in MODELS:
            pooled_scores, pooled_preds = np.full(len(y), np.nan), np.full(len(y), -1)
            for i, fold in enumerate(splits):
                folder = path / label / model / f"fold-{i}"
                tr, te = np.array(fold["train"]), np.array(fold["test"])
                _check_partition(tr, te, groups, labels)
                candidates = []
                for candidate in config["grids"][model]:
                    record = load_record(
                        folder / "candidates" / f"{candidate['candidate_id']}.json",
                        identity,
                    )
                    if (
                        record["candidate"] != candidate
                        or record["row_ids"] != tr.tolist()
                    ):
                        raise ValueError("Candidate identity/rows invalid")
                    candidates.append(record)
                best = min(
                    candidates,
                    key=lambda r: (-r["mean_auc"], r["candidate"]["candidate_id"]),
                )
                inner = load_record(folder / "threshold.json", identity)
                if (
                    inner["candidate"] != best["candidate"]
                    or inner["row_ids"] != tr.tolist()
                ):
                    raise ValueError("Threshold candidate or rows differ")
                if threshold(inner["scores"], y[tr]) != inner["threshold"]:
                    raise ValueError("Threshold cannot be reproduced")
                for recorded, expected in zip(
                    inner["provenance"], fold["inner"], strict=True
                ):
                    if (
                        recorded["train"] != expected["train"]
                        or recorded["validation"] != expected["validation"]
                    ):
                        raise ValueError("OOF provenance mismatch")
                    _check_partition(
                        np.array(recorded["train"]),
                        np.array(recorded["validation"]),
                        groups,
                        labels,
                    )
                outer = load_record(folder / "outer.json", identity)
                if (
                    outer["row_ids"] != te.tolist()
                    or outer["fit_row_ids"] != tr.tolist()
                    or outer["y_true"] != y[te].tolist()
                ):
                    raise ValueError("Outer fit scope mismatch")
                scores, pred = np.array(outer["scores"]), np.array(outer["predictions"])
                if outer["threshold"] != inner["threshold"] or not np.array_equal(
                    pred, scores >= inner["threshold"]
                ):
                    raise ValueError(
                        "Held-out predictions not using internal threshold"
                    )
                if hash_json(compute_metrics(y[te], scores, pred)) != hash_json(
                    outer["metrics"]
                ):
                    raise ValueError("Fold metric mismatch")
                pooled_scores[te], pooled_preds[te] = scores, pred
            oof = load_record(path / label / model / "oof.json", identity)
            if oof["row_ids"] != list(range(len(y))) or oof["y_true"] != y.tolist():
                raise ValueError("Pooled OOF row or target metadata mismatch")
            if not np.array_equal(oof["scores"], pooled_scores) or not np.array_equal(
                oof["predictions"], pooled_preds
            ):
                raise ValueError("Pooled OOF differs from held-out fold predictions")
            expected = compute_metrics(y, pooled_scores, pooled_preds)
            report = next(
                r for r in rows if r["label"] == label and r["model"] == model
            )
            for key, value in expected.items():
                if report[key] != value:
                    raise ValueError(f"Pooled metric mismatch: {key}")
    return {
        "endpoint": config["endpoint"],
        "identity": identity,
        "combinations": len(labels) * len(MODELS),
        "outer_folds": len(labels) * len(MODELS) * len(splits),
        "status": "passed",
    }


def report_table(rows):
    columns = ["endpoint", "label", "model", *CORE, "abs_gap", "fold_dispersion"]
    return pd.DataFrame(rows).loc[:, columns]


def completed_pointer(root, endpoint):
    root = Path(root).resolve()
    pointer = json.loads(
        (root / f"{endpoint}_completed.json").read_text(encoding="utf-8")
    )
    output = Path(pointer["output_dir"]).resolve()
    expected = root / endpoint / pointer["identity"][:16]
    if output != expected.resolve() or not output.is_relative_to(root):
        raise ValueError("Completed pointer escapes requested run/endpoint")
    config = load_record(output / "config.json", pointer["identity"])
    if (
        config["endpoint"] != endpoint
        or config["run_id"] != root.name
        or hash_json(config) != pointer["identity"]
    ):
        raise ValueError("Completed pointer endpoint/run identity mismatch")
    return pointer


def compare_run(output_root=None, run_id=None):
    import matplotlib.pyplot as plt

    root = (
        Path(output_root or ROOT)
        / "runs"
        / (run_id or os.getenv("EPA_RUN_ID", DEFAULT_RUN))
    )
    rows = []
    identities = {}
    for endpoint in ("skin", "eye"):
        pointer = completed_pointer(root, endpoint)
        identities[endpoint] = pointer["identity"]
        verify_endpoint(pointer["output_dir"])
        rows.extend(
            load_record(
                Path(pointer["output_dir"]) / "report.json", pointer["identity"]
            )
        )
    if len(rows) != 4 * len(MODELS):
        raise ValueError("All 24 selected-model combinations are required")
    table = report_table(rows)
    csv_path = root / "comparison.csv"
    csv_content = table.to_csv(index=False, lineterminator="\n")
    if csv_path.exists() and csv_path.read_text(encoding="utf-8-sig") != csv_content:
        raise ValueError("Refusing to overwrite changed comparison")
    if not csv_path.exists():
        csv_path.write_text(csv_content, encoding="utf-8-sig", newline="")
    fig, axes = plt.subplots(2, 2, figsize=(13, 11), sharex=True, sharey=True)
    for ax, (endpoint, label) in zip(
        axes.ravel(), [(e, l) for e in ("skin", "eye") for l in ("A", "B")]
    ):
        subset = table[(table.endpoint == endpoint) & (table.label == label)]
        for _, row in subset.iterrows():
            ax.scatter(row.sensitivity, row.specificity)
            ax.annotate(row.model, (row.sensitivity, row.specificity))
        ax.plot([0, 1], [0, 1], "--", color="gray")
        ax.set(
            xlim=(0, 1),
            ylim=(0, 1),
            xlabel="Sensitivity",
            ylabel="Specificity",
            title=f"{endpoint} / EPA {label}",
        )
    fig.suptitle(
        "Joint balance: inspect absolute sensitivity/specificity, MCC, ROC-AUC and fold dispersion"
    )
    fig.tight_layout()
    image = root / "sensitivity_specificity.png"
    manifest_path = root / "comparison_manifest.json"
    if image.exists():
        if not manifest_path.exists():
            raise ValueError("Existing comparison image lacks integrity manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest["identities"] != identities
            or manifest["image_sha256"] != file_hash(image)
            or manifest["csv_sha256"] != file_hash(csv_path)
        ):
            raise ValueError("Comparison image/table integrity mismatch")
    else:
        fig.savefig(image, dpi=160)
        atomic_json(
            manifest_path,
            {
                "identities": identities,
                "image_sha256": file_hash(image),
                "csv_sha256": file_hash(csv_path),
            },
        )
    plt.show()
    return table
