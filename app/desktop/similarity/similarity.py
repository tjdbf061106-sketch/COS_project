"""향료/향미제 유사도, 계면활성제 유사도 '보조점수' 모듈.

skin/eye 자극성 모델, caution/ 모듈과도 분리된 **세 번째 경로**입니다. 학습된
분류기가 아니라 순수 화학정보학 계산(RDKit)만 사용하며, 새로 라벨링된 학습
데이터나 모델 체크포인트가 필요 없습니다.

- 향료 유사도: EU 화장품규정이 지정한 향료 알레르겐 20종(fragrance_reference.json)과의
  Morgan fingerprint(radius=2, fpSize=2048, skin/predict.py와 동일 설정) Tanimoto
  최근접이웃 유사도. "향료 알레르겐과 구조적으로 얼마나 가까운가"를 재는 것이므로
  최근접이웃 방식이 적합합니다.
- 계면활성제 유사도: 최근접이웃 방식을 쓰지 않습니다. 계면활성제는 특정 성분과
  닮았는지가 아니라 '친수성 머리(이온성/극성기) + 소수성 꼬리(긴 지방족 사슬)'라는
  양친매성 패턴으로 정의되는 기능적 분류라서, SMARTS로 머리그룹을 검출하고 가장 긴
  지방족 사슬 길이와 결합한 규칙 기반 점수를 씁니다(surfactant_patterns.json).

pretraining/(FIFRA/ICE 농약 제형으로 추가 사전학습한 ChemBERTa)을 재사용하지
않은 이유는 README.md를 참고하세요.
"""
from __future__ import annotations

import json
from pathlib import Path

from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

ROOT = Path(__file__).resolve().parent

# skin/predict.py의 Morgan fingerprint 설정과 동일 (radius=2, fpSize=2048).
_MORGAN_GEN = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=2048)


def _load_json(name: str):
    with (ROOT / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _mol_from_smiles(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError(f"RDKit이 해석할 수 없는 SMILES입니다: {smiles!r}")
    return mol


class FragranceSimilarity:
    """향료 알레르겐 20종과의 Morgan fingerprint Tanimoto 최근접이웃 유사도."""

    def __init__(self) -> None:
        data = _load_json("fragrance_reference.json")["compounds"]
        self._refs = []
        for entry in data:
            mol = _mol_from_smiles(entry["smiles"])
            fp = _MORGAN_GEN.GetFingerprint(mol)
            self._refs.append({"name": entry["name"], "smiles": entry["smiles"], "fp": fp})

    def score(self, smiles: str, top_k: int = 3) -> dict:
        """반환값의 score는 [0, 1] 범위의 '향료 알레르겐 20종 중 가장 가까운 것과의
        구조 유사도'이며, 확률이나 알레르기 발생 가능성이 아닙니다."""
        mol = _mol_from_smiles(smiles)
        query_fp = _MORGAN_GEN.GetFingerprint(mol)

        scored = [
            {"name": ref["name"], "tanimoto": DataStructs.TanimotoSimilarity(query_fp, ref["fp"])}
            for ref in self._refs
        ]
        scored.sort(key=lambda r: r["tanimoto"], reverse=True)

        return {
            "score": scored[0]["tanimoto"] if scored else 0.0,
            "nearest": scored[0] if scored else None,
            "top_matches": scored[:top_k],
            "method": "morgan_fp_tanimoto_nearest_neighbor",
            "reference_set_size": len(self._refs),
        }


class SurfactantLikeness:
    """'친수성 머리 + 긴 소수성 꼬리' 양친매성 규칙 기반 점수. 최근접이웃 유사도가
    아닙니다(이유는 모듈 docstring 참고)."""

    def __init__(self) -> None:
        data = _load_json("surfactant_patterns.json")
        self._min_chain = data["min_hydrophobic_chain_length"]
        self._head_groups = []
        for entry in data["head_groups"]:
            patt = Chem.MolFromSmarts(entry["smarts"])
            if patt is None:
                raise ValueError(f"잘못된 SMARTS: {entry['id']}")
            self._head_groups.append({**entry, "_patt": patt})

    @staticmethod
    def _longest_aliphatic_chain(mol, atom_cap: int = 60) -> int:
        """방향족이 아닌 탄소 원자들로 이루어진 가장 긴 단순 경로 길이.
        atom_cap을 넘는 큰 분자는 조합 폭발을 피하기 위해 평가하지 않고 0을 반환합니다
        (이 모듈은 저분자 화장품 원료용이라 실제로는 거의 발생하지 않음)."""
        carbon_idxs = [
            atom.GetIdx() for atom in mol.GetAtoms()
            if atom.GetAtomicNum() == 6 and not atom.GetIsAromatic()
        ]
        if not carbon_idxs or len(carbon_idxs) > atom_cap:
            return 0

        carbon_set = set(carbon_idxs)
        adjacency: dict[int, list[int]] = {i: [] for i in carbon_idxs}
        for bond in mol.GetBonds():
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if a in carbon_set and b in carbon_set:
                adjacency[a].append(b)
                adjacency[b].append(a)

        best = 0

        def dfs(node: int, visited: frozenset[int]) -> None:
            nonlocal best
            best = max(best, len(visited))
            for nxt in adjacency[node]:
                if nxt not in visited:
                    dfs(nxt, visited | {nxt})

        for start in carbon_idxs:
            dfs(start, frozenset({start}))
        return best

    def score(self, smiles: str) -> dict:
        mol = _mol_from_smiles(smiles)
        matched_head_groups = [
            {"id": hg["id"], "class": hg["class"], "label_ko": hg["label_ko"]}
            for hg in self._head_groups
            if mol.HasSubstructMatch(hg["_patt"])
        ]
        chain_length = self._longest_aliphatic_chain(mol)
        has_head_group = len(matched_head_groups) > 0
        has_long_chain = chain_length >= self._min_chain

        if has_head_group and has_long_chain:
            score = 1.0
        elif has_head_group:
            score = 0.5  # 이온성/극성 머리는 있으나 소수성 꼬리가 기준보다 짧음
        elif has_long_chain:
            score = 0.3  # 긴 지방족 사슬은 있으나 이온성/극성 머리그룹 없음(예: 지방알코올)
        else:
            score = 0.0

        return {
            "score": score,
            "matched_head_groups": matched_head_groups,
            "longest_aliphatic_chain": chain_length,
            "min_hydrophobic_chain_length": self._min_chain,
            "method": "head_group_smarts_plus_chain_length_rule",
        }


def fragrance_similarity_score(smiles: str) -> dict:
    return FragranceSimilarity().score(smiles)


def surfactant_likeness_score(smiles: str) -> dict:
    return SurfactantLikeness().score(smiles)
