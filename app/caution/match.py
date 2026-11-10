"""문헌 기반 '주의정보' 매칭 모듈.

skin/eye 모델의 자극성 점수(predict.py)와는 완전히 분리된, 두 번째 경로입니다.
입력: 성분(성분명 + 함량%) 목록 + 사용자가 선택한 질환/상태.
출력: 선택한 질환별로, 해당 배합에서 발견된 '문헌 기반 주의사항' 목록.

이 모듈은 독성 점수를 계산하지 않고, 질환별 사용 가능 여부를 판정(처방)하지도
않습니다. 문헌에서 보고된 성분-상태 연관성을 그대로 안내할 뿐이며, 최종 판단은
사용자(또는 의료 전문가)의 몫입니다. 반드시 rules.json/citations.json에 근거가
있는 조합만 출력하며, 새 조건/성분을 추가하려면 먼저 문헌 근거를 citations.json에
등록해야 합니다.

데이터 파일:
    conditions.json      -- 지원하는 질환/상태 목록
    ingredient_tags.json -- 성분명(또는 SMILES) -> 주의 태그
    rules.json            -- 질환 x 태그 -> 안내 문구
    citations.json        -- 태그별 근거 문헌
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

DISCLAIMER_KO = (
    "이 안내는 피부/눈 자극성 예측 모델의 점수와 무관한 별도 문헌 조사 결과입니다. "
    "질환별 사용 가능 여부를 진단·처방하지 않으며, 보고된 성분-상태 연관성을 참고 정보로만 제공합니다. "
    "실제 사용 여부는 의료 전문가와 상담하세요."
)


def _load_json(name: str) -> Any:
    with (ROOT / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _normalize_name(name: str) -> str:
    """소문자화 + 공백/구두점 정리. 부분 문자열이 아닌 '완전 일치' 비교에만 사용합니다."""
    if not name:
        return ""
    value = unicodedata.normalize("NFKC", str(name)).strip().lower()
    value = re.sub(r"[\s_\-./]+", " ", value)
    value = re.sub(r"[^\w가-힣 ]+", "", value, flags=re.UNICODE)
    return value.strip()


@dataclass
class TagMatch:
    tag_id: str
    label_ko: str
    evidence_tier: str
    matched_components: list[dict] = field(default_factory=list)


class CautionMatcher:
    def __init__(self) -> None:
        self.conditions = {c["id"]: c for c in _load_json("conditions.json")["conditions"]}
        self.tags = {t["id"]: t for t in _load_json("ingredient_tags.json")["tags"]}
        rules_data = _load_json("rules.json")
        self.rules = rules_data["condition_rules"]
        self.medication_rules = rules_data.get("medication_rules", {})
        self.medications = {m["id"]: m for m in _load_json("medications.json")["medications"]}
        self.citations = _load_json("citations.json")["citations"]

        # 역색인: 정규화된 성분명 -> 태그 id 목록
        self._name_index: dict[str, list[str]] = {}
        # 역색인: canonical SMILES -> 태그 id 목록 (보조 수단)
        self._smiles_index: dict[str, list[str]] = {}
        for tag_id, tag in self.tags.items():
            for name in tag.get("names", []):
                key = _normalize_name(name)
                if key:
                    self._name_index.setdefault(key, []).append(tag_id)
            for smiles in tag.get("smiles", []):
                self._smiles_index.setdefault(smiles.strip(), []).append(tag_id)

    def _tags_for_component(self, component: dict) -> set[str]:
        found: set[str] = set()
        for name in [component.get("name", ""), *component.get("aliases", [])]:
            name_key = _normalize_name(name)
            if name_key in self._name_index:
                found.update(self._name_index[name_key])
        smiles = str(component.get("canonical_smiles") or "").strip()
        if smiles in self._smiles_index:
            found.update(self._smiles_index[smiles])
        return found

    def _collect_tag_hits(self, components: list[dict]) -> dict[str, list[dict]]:
        tag_hits: dict[str, list[dict]] = {}
        for component in components:
            for tag_id in self._tags_for_component(component):
                tag_hits.setdefault(tag_id, []).append(
                    {
                        "name": component.get("name"),
                        "amount_pct": component.get("amount_pct"),
                    }
                )
        return tag_hits

    def _hits_after_threshold(
        self, hits: list[dict], tag: dict, ignore_threshold: bool
    ) -> list[dict]:
        threshold = None if ignore_threshold else tag.get("concentration_threshold_pct")
        if threshold is None:
            return hits
        return [
            h for h in hits
            if h.get("amount_pct") is not None and h["amount_pct"] > threshold
        ]

    def _citations_for_tag(self, tag: dict) -> list[dict]:
        return [
            cite
            for cid in tag.get("citation_ids", [])
            for cite in self.citations.get(cid, [])
        ]

    def evaluate(
        self,
        components: list[dict],
        condition_ids: list[str],
        medication_ids: list[str] | None = None,
    ) -> dict:
        """components: COS_project predict.py와 동일한 스키마
        ([{"name":..., "canonical_smiles":..., "amount_pct":...}, ...]).
        condition_ids: conditions.json에 정의된 id 목록 중 사용자가 선택한 질환/상태.
        medication_ids: medications.json에 정의된 id 목록 중 사용자가 선택한
            '병행 중인 약물/치료'. 선택하지 않으면 약물 상호작용 쪽은 평가하지 않습니다.
        """
        medication_ids = medication_ids or []

        unknown_conditions = [c for c in condition_ids if c not in self.conditions]
        if unknown_conditions:
            raise ValueError(f"알 수 없는 condition id: {unknown_conditions}")
        unknown_medications = [m for m in medication_ids if m not in self.medications]
        if unknown_medications:
            raise ValueError(f"알 수 없는 medication id: {unknown_medications}")

        tag_hits = self._collect_tag_hits(components)
        # Dictionary coverage is independent of selected rules and concentration thresholds.
        unmatched_components = [dict(component) for component in components
                                if not self._tags_for_component(component)]

        results: dict[str, dict] = {}
        for condition_id in condition_ids:
            condition = self.conditions[condition_id]
            cautions = []
            for rule in self.rules.get(condition_id, []):
                tag_id = rule["tag"]
                hits = tag_hits.get(tag_id)
                if not hits:
                    continue
                tag = self.tags[tag_id]
                hits = self._hits_after_threshold(hits, tag, ignore_threshold=False)
                if not hits:
                    continue
                cautions.append(
                    {
                        "tag": tag_id,
                        "label_ko": tag["label_ko"],
                        "evidence_tier": tag["evidence_tier"],
                        "message_ko": rule["message_ko"],
                        "matched_components": hits,
                        "citations": self._citations_for_tag(tag),
                    }
                )
            results[condition_id] = {
                "label_ko": condition["label_ko"],
                "domain": condition["domain"],
                "cautions": cautions,
                "no_findings": len(cautions) == 0,
            }

        medication_results: dict[str, dict] = {}
        for medication_id in medication_ids:
            medication = self.medications[medication_id]
            interactions = []
            for rule in self.medication_rules.get(medication_id, []):
                tag_id = rule["tag"]
                hits = tag_hits.get(tag_id)
                if not hits:
                    continue
                tag = self.tags[tag_id]
                hits = self._hits_after_threshold(
                    hits, tag, ignore_threshold=bool(rule.get("ignore_concentration_threshold"))
                )
                if not hits:
                    continue
                interactions.append(
                    {
                        "tag": tag_id,
                        "label_ko": tag["label_ko"],
                        "interaction_type": rule["interaction_type"],
                        "message_ko": rule["message_ko"],
                        "matched_components": hits,
                        "citations": self._citations_for_tag(tag),
                    }
                )
            medication_results[medication_id] = {
                "label_ko": medication["label_ko"],
                "domain": medication["domain"],
                "interactions": interactions,
                "no_findings": len(interactions) == 0,
            }

        return {
            "disclaimer": DISCLAIMER_KO,
            "unmatched_components": unmatched_components,
            "recognized_component_count": len(components) - len(unmatched_components),
            "results": results,
            "medication_results": medication_results,
        }


def evaluate_caution(
    components: list[dict],
    condition_ids: list[str],
    medication_ids: list[str] | None = None,
) -> dict:
    """모듈 수준 헬퍼. GUI/백엔드에서 매 호출마다 새 매처를 만들지 않도록
    필요하면 CautionMatcher 인스턴스를 직접 재사용하세요."""
    return CautionMatcher().evaluate(components, condition_ids, medication_ids)
