import copy
import csv
import io
import json
import math
import os
import subprocess
import sys
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

from desktop import VERSION
from desktop.paths import resources, installation
from desktop.validation import validate, digest
from desktop.identity import check_components, references, local_references

_CAUTION = None


def _caution_matcher():
    # Pure-stdlib literature module; independent of the skin/eye model scores.
    global _CAUTION
    if _CAUTION is None:
        from caution.match import CautionMatcher
        _CAUTION = CautionMatcher()
    return _CAUTION


def caution_options():
    matcher = _caution_matcher()
    pick = lambda item: {k: item.get(k) for k in ("id", "domain", "label_ko", "description_ko")}
    return {"conditions": [pick(c) for c in matcher.conditions.values()],
            "medications": [pick(m) for m in matcher.medications.values()]}


def caution(payload, active):
    selection = payload.get("caution") or {}
    conditions = [str(c) for c in selection.get("conditions") or []]
    medications = [str(m) for m in selection.get("medications") or []]
    matcher = _caution_matcher()
    components = []
    for row in active:
        # Match registered names/structures first, then the user's original name or alias.
        name = row.get("name") or ""
        query = row.get("query") or ""
        smiles = row.get("canonical_smiles") or ""
        display_name = name if name and name != "직접 입력 원료" else query or smiles or "이름 없는 원료"
        component = {"component_id": row.get("component_id"), "name": name,
                     "display_name": display_name, "canonical_smiles": smiles,
                     "aliases": row.get("identity_aliases", []),
                     "amount_pct": row.get("amount_pct")}
        if not matcher._tags_for_component(component) and query and query != component["name"]:
            alternative = dict(component, name=query)
            if matcher._tags_for_component(alternative):
                component = alternative
        components.append(component)
    result = matcher.evaluate(components, conditions, medications)
    result.update({"status": "complete" if conditions or medications else "not_selected",
                   "conditions": conditions, "medications": medications})
    return result

def worker_command(endpoint):
    base = installation()
    if getattr(sys, "frozen", False):
        return [str(base / "engines" / endpoint / ("COS-" + endpoint + "-engine.exe"))]
    interpreter = base / (".venv-skin" if endpoint == "skin" else ".venv-eye") / "Scripts" / "python.exe"
    if not interpreter.exists():
        raise RuntimeError(f"{endpoint} 실행 환경을 찾을 수 없습니다. 개발용 설치 안내를 확인해 주세요.")
    return [str(interpreter), str(base / "engine_entry.py")]


def call_worker(endpoint, request):
    process = subprocess.run(worker_command(endpoint), input=json.dumps(request, ensure_ascii=False),
                             capture_output=True, encoding="utf-8", errors="replace", timeout=100,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                             cwd=str(installation()))
    try:
        response = json.loads(process.stdout)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"{endpoint} 분석 엔진을 실행하지 못했습니다. 실행 패키지를 확인해 주세요.") from exc
    if not response.get("ok"):
        raise ValueError(response.get("error", "분석을 완료하지 못했습니다."))
    if process.returncode:
        raise RuntimeError("분석 엔진이 비정상 종료했습니다.")
    return response["result"]


def structure(smiles):
    return call_worker("eye", {"action": "structure", "smiles": smiles})


@lru_cache(maxsize=64)
def canonicalize(smiles):
    request = {"action": "canonicalize", "smiles": list(smiles)}
    try:
        result = call_worker("eye", request)
    except Exception:
        result = call_worker("skin", request)
    if not isinstance(result, list) or len(result) != len(smiles):
        raise ValueError("구조 확인 엔진의 응답이 올바르지 않습니다.")
    return result


def validate_ingredients(payload):
    checked = validate(payload)
    if not checked["valid"]:
        return checked
    try:
        identity = check_components(checked["active"], canonicalize)
    except Exception as exc:
        checked["issues"].append({"field": "canonical_smiles", "code": "identity_unavailable",
                                  "message": "원료의 이름·구조를 확인하지 못했습니다: " + str(exc)})
    else:
        checked["active"] = identity["active"]
        checked["identities"] = identity["identities"]
        checked["issues"].extend(identity["issues"])
    checked["valid"] = not checked["issues"]
    return checked


def evidence(smiles):
    return call_worker("eye", {"action": "evidence", "smiles": smiles})


def lookup(query, mode="name"):
    if not isinstance(query, str) or not query.strip() or len(query) > 1000:
        raise ValueError("성분명 또는 SMILES를 입력해 주세요.")
    query = query.strip()
    if mode == "smiles":
        result = structure(query)
        result.update({"name": "직접 입력 원료", "source": "직접 입력", "cas": ""})
        return [result]
    records = references(query)
    candidates = []
    for item in records:
        candidate = structure(item["smiles"])
        candidate.update({"name": item["name"], "cid": item["cid"], "cas": item.get("cas", ""),
                          "source": "로컬 원료 사전" if local_references(query) else "PubChem",
                          "source_url": item["source_url"]})
        candidates.append(candidate)
    if not candidates:
        raise ValueError("검색 결과에 사용할 수 있는 구조가 없습니다. SMILES로 직접 입력해 주세요.")
    return candidates


def caution_for_report(data):
    snapshot = copy.deepcopy(data.get("input") or {})
    snapshot.pop("caution", None)
    checked = validate_ingredients(snapshot)
    if not checked["valid"]:
        raise ValueError(" / ".join(issue["message"] for issue in checked["issues"]))
    return caution({"caution": data.get("caution")}, checked["active"])


def analyze(payload):
    snapshot = copy.deepcopy(payload)
    # The caution selection is chosen on the report page; keep it out of the model input and its hash.
    selection = snapshot.pop("caution", None) if isinstance(snapshot, dict) else None
    checked = validate_ingredients(snapshot)
    if not checked["valid"]:
        return {"status": "invalid", "validation": checked}
    # Each worker strictly parses every active structure before calling its model.
    # Keep failures independent: a missing eye runtime must not block skin.
    def one(endpoint):
        try:
            return call_worker(endpoint, {"action": "predict", "endpoint": endpoint, "payload": snapshot})
        except Exception as exc:
            return {"status": "held", "endpoint": endpoint, "score": None,
                    "predicted_class": None, "label_text": None, "reasons": [str(exc)]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        skin = pool.submit(one, "skin")
        eye = pool.submit(one, "eye")
        results = {"skin": skin.result(), "eye": eye.result()}
    total_active = sum(r["amount_pct"] for r in checked["active"])
    weights = [{"component_id": r.get("component_id"), "name": r.get("name", ""),
                "amount_pct": r["amount_pct"], "relative_weight": r["amount_pct"] / total_active}
               for r in checked["active"]]
    try:
        caution_result = caution({"caution": selection}, checked["active"])
    except Exception as exc:
        caution_result = {"status": "held", "reasons": [str(exc)]}
    return {"status": "complete", "schema_version": 1, "app_version": VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(), "input_hash": digest(snapshot),
            "input": snapshot, "validation": checked, "weights": weights, "results": results,
            "caution": caution_result}


def parse_csv(text):
    fields = {"name": ["name", "성분명", "원료명"], "canonical_smiles": ["canonical_smiles", "smiles", "SMILES"],
              "amount_pct": ["amount_pct", "함량", "함량(%)", "함량%", "percentage"]}
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    headers = reader.fieldnames or []
    selected = {key: next((h for h in aliases if h in headers), None) for key, aliases in fields.items()}
    if not selected["amount_pct"] or not (selected["name"] or selected["canonical_smiles"]):
        raise ValueError("CSV에는 name 또는 canonical_smiles와 amount_pct 열이 필요합니다.")
    rows = []
    for n, raw in enumerate(reader):
        if n >= 100:
            raise ValueError("CSV는 최대 100개 원료까지 불러올 수 있습니다.")
        row = {key: (raw.get(column) or "").strip() if column else "" for key, column in selected.items()}
        amount = row["amount_pct"]
        try:
            row["amount_pct"] = float(amount) if amount else None
            if row["amount_pct"] is not None and not math.isfinite(row["amount_pct"]):
                raise ValueError("non-finite amount")
        except ValueError:
            row["amount_pct"] = None
            row["amount_text"] = amount
        row.update({"component_id": "csv-" + str(n), "query": row["name"] or row["canonical_smiles"],
                    "mode": "name" if row["name"] else "smiles"})
        rows.append(row)
    if not rows:
        raise ValueError("CSV에 원료 행이 없습니다.")
    return rows


def export_csv(report):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    def safe(value):
        text = "" if value is None else str(value)
        return "'" + text if text.startswith(("=", "+", "-", "@", "\t", "\r")) else text
    writer.writerow(["kind", "name_or_endpoint", "smiles_or_label", "amount_pct_or_score",
                     "relative_weight_or_threshold", "model_id", "details"])
    weight_map = {w["component_id"]: w["relative_weight"] for w in report.get("weights", [])}
    for row in report["input"]["components"]:
        writer.writerow([safe(v) for v in ["ingredient", row.get("name"), row.get("canonical_smiles"),
                         row.get("amount_pct"), weight_map.get(row.get("component_id")), "", "원래 입력 함량"]])
    for endpoint, result in report["results"].items():
        writer.writerow([safe(v) for v in ["prediction", endpoint, result.get("label_text"), result.get("score"),
                         result.get("threshold"), result.get("model_id"), " / ".join(result.get("reasons", [result.get("note", "")]))]])
    for entry in report.get("validation", {}).get("identities", []):
        writer.writerow([safe(v) for v in ["identity", entry.get("name"), entry.get("canonical_smiles"),
                         entry.get("status"), "", "", " ; ".join(entry.get("source_urls", []))]])
    for component_id, detail in report.get("evidence", {}).items():
        for score in detail.get("scores", []):
            writer.writerow([safe(v) for v in ["auxiliary", component_id, score["label"], score["score"],
                             "", score["model_id"], json.dumps(score, ensure_ascii=False, allow_nan=False)]])
        for pattern in detail.get("patterns", []):
            writer.writerow([safe(v) for v in ["pattern", component_id, pattern["label"], "", "",
                             pattern["model_id"], json.dumps({k: v for k, v in pattern.items() if k != "preview"}, ensure_ascii=False)]])
        source = detail.get("source", {})
        writer.writerow([safe(v) for v in ["evidence_source", component_id, source.get("name"), source.get("version"),
                         "", source.get("sha256"), json.dumps(source, ensure_ascii=False)]])
        for annotation in detail.get("annotations", {}).get("entries", []):
            writer.writerow([safe(v) for v in ["annotation", component_id, annotation["source"], "", "", annotation["url"], annotation["text"]]])
    caution_report = report.get("caution") or {}
    if "recognized_component_count" in caution_report:
        writer.writerow(["caution_coverage", "recognized", "", caution_report["recognized_component_count"], "", "", "사전 확인 원료 수"])
        writer.writerow(["caution_coverage", "unmatched", "", len(caution_report.get("unmatched_components", [])), "", "", "사전 미확인 원료 수"])
    for component in caution_report.get("unmatched_components", []):
        writer.writerow([safe(v) for v in ["caution_unmatched", component.get("display_name") or component.get("name"),
                         component.get("canonical_smiles"), component.get("amount_pct"), "", "",
                         "사전에 없어서 확인하지 못한 원료"]])
    for group, key in (("results", "cautions"), ("medication_results", "interactions")):
        for target_id, entry in (caution_report.get(group) or {}).items():
            for item in entry.get(key, []):
                names = ", ".join(str(m.get("name")) for m in item.get("matched_components", []))
                writer.writerow([safe(v) for v in ["caution_" + ("condition" if group == "results" else "medication"),
                                 entry.get("label_ko"), item.get("label_ko"), names,
                                 item.get("evidence_tier") or item.get("interaction_type"), item.get("tag"),
                                 item.get("message_ko") + " | " + " ; ".join(c.get("url", "") for c in item.get("citations", []))]])
            if entry.get("no_findings"):
                writer.writerow([safe(v) for v in ["caution_" + ("condition" if group == "results" else "medication"),
                                 entry.get("label_ko"), "해당 성분 없음", "", "", "", "등록된 문헌 기반 성분이 검출되지 않음"]])
    writer.writerow(["summary", "total_pct", "", report["validation"]["total"], "", "", ""])
    writer.writerow(["summary", "unlisted_pct", "", report["validation"]["unlisted"], "", "", ""])
    writer.writerow(["metadata", "input_hash", report["input_hash"], "", "", "", report["created_at"]])
    return stream.getvalue()
