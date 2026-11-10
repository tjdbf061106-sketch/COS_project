"""Local fragrance/surfactant reference information, separate from irritation."""
import base64
import hashlib
import io
import json
from functools import lru_cache
from pathlib import Path

from rdkit import Chem, rdBase
from rdkit.Chem import Descriptors, Crippen, rdMolDescriptors, Draw

LABELS = {"fragrance_similarity": "향료 유사도", "surfactant_likeness": "계면활성제 구조점수"}


@lru_cache(maxsize=1)
def runtime():
    root = Path(__file__).parent / "similarity"
    metadata = json.loads((root / "SOURCE.json").read_text(encoding="utf-8"))
    for name, expected in metadata["files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError("보조점수 자료 검증에 실패했습니다. 배포 패키지를 확인해 주세요.")
    from desktop.similarity.similarity import FragranceSimilarity, SurfactantLikeness
    patterns = json.loads((root / "surfactant_patterns.json").read_text(encoding="utf-8"))
    return FragranceSimilarity(), SurfactantLikeness(), patterns, metadata


def png_url(molecule, atoms=(), bonds=(), size=(600, 330)):
    buffer = io.BytesIO()
    Draw.MolToImage(molecule, size=size, highlightAtoms=list(atoms), highlightBonds=list(bonds)).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def describe_evidence(smiles):
    if not isinstance(smiles, str) or not smiles.strip() or len(smiles) > 10000:
        raise ValueError("올바른 SMILES를 입력해 주세요.")
    with rdBase.BlockLogs():
        molecule = Chem.MolFromSmiles(smiles)
    if molecule is None or not 1 <= molecule.GetNumAtoms() <= 1000:
        raise ValueError("원료 구조를 해석하지 못했거나 지원 크기를 초과했습니다.")
    canonical = Chem.MolToSmiles(molecule)
    fragrance, surfactant, definitions, metadata = runtime()
    fragrance_result = fragrance.score(canonical)
    surfactant_result = surfactant.score(canonical)
    # The supplied module returns zero for an unexamined chain above its 60-carbon cap.
    # Keep the raw return value, but do not present an unexamined overall score as zero.
    carbon_count = sum(atom.GetAtomicNum() == 6 and not atom.GetIsAromatic() for atom in molecule.GetAtoms())
    chain_evaluated = carbon_count <= 60
    scores = [
        {"model_id": "fragrance_similarity", "label": LABELS["fragrance_similarity"],
         "status": "complete", **fragrance_result},
        {"model_id": "surfactant_likeness", "label": LABELS["surfactant_likeness"],
         **surfactant_result, "status": "complete" if chain_evaluated else "held",
         "score": surfactant_result["score"] if chain_evaluated else None,
         "raw_result": surfactant_result, "chain_evaluated": chain_evaluated,
         "reason": "" if chain_evaluated else "비방향족 탄소가 60개를 초과해 원본 모듈이 사슬 길이를 평가하지 않았습니다."},
    ]
    for score in scores:
        score["source_sha256"] = metadata["sha256"]
    patterns = []
    matched_ids = {item["id"] for item in surfactant_result["matched_head_groups"]}
    for definition in definitions["head_groups"]:
        if definition["id"] not in matched_ids:
            continue
        query = Chem.MolFromSmarts(definition["smarts"])
        matches = molecule.GetSubstructMatches(query)
        atoms = {atom for match in matches for atom in match}
        bonds = {molecule.GetBondBetweenAtoms(match[b.GetBeginAtomIdx()], match[b.GetEndAtomIdx()]).GetIdx()
                 for match in matches for b in query.GetBonds()}
        patterns.append({"model_id": "surfactant_likeness", "model_label": LABELS["surfactant_likeness"],
                         "pattern_id": definition["id"], "label": definition["label_ko"],
                         "kind": "친수성 머리 SMARTS", "smarts": definition["smarts"],
                         "explanation": "제공된 계면활성제 머리 구조 규칙과 일치합니다. 강조 부분은 실제 매칭 위치이며, 긴 사슬 유무는 별도로 계산합니다.",
                         "preview": png_url(molecule, atoms, bonds, size=(340, 200))})
    properties = {
        "formula": rdMolDescriptors.CalcMolFormula(molecule), "molecular_weight": Descriptors.MolWt(molecule),
        "logp": Crippen.MolLogP(molecule), "tpsa": rdMolDescriptors.CalcTPSA(molecule),
        "hbd": rdMolDescriptors.CalcNumHBD(molecule), "hba": rdMolDescriptors.CalcNumHBA(molecule),
        "aromatic_rings": rdMolDescriptors.CalcNumAromaticRings(molecule),
    }
    nearest = fragrance_result["nearest"]
    notes = [
        f"분자식 {properties['formula']}, 계산 분자량 {properties['molecular_weight']:.2f} g/mol인 구조입니다.",
        f"향료 참조 {fragrance_result['reference_set_size']}종과 비교한 최대 유사도입니다. Morgan 지문(radius 2, 2048비트)의 Tanimoto 유사도를 사용합니다.",
        f"가장 가까운 참조는 {nearest['name']}이며 유사도는 {nearest['tanimoto']:.4f}입니다. 향료 전체 목록과 비교한 점수는 아닙니다."
        if nearest and fragrance_result["score"] > 0 else "등록된 향료 참조 모두와 계산된 유사도가 0입니다.",
        f"계면활성제 머리 구조 {len(patterns)}종이 검출됐습니다. 서로 겹치는 머리 구조가 함께 표시될 수 있습니다."
        if patterns else "등록된 계면활성제 머리 구조가 검출되지 않았습니다. 패턴 미검출은 안전성의 근거가 아닙니다.",
        f"비방향족 탄소의 최장 경로는 {surfactant_result['longest_aliphatic_chain']}개이며, 긴 사슬 기준은 {surfactant_result['min_hydrophobic_chain_length']}개입니다. 고리의 탄소도 경로에 포함될 수 있습니다."
        if chain_evaluated else scores[1]["reason"],
        "계면활성제 점수는 머리+긴 사슬 1.0, 머리만 0.5, 긴 사슬만 0.3, 둘 다 없으면 0.0입니다. 당 고리형 비이온 계면활성제 등은 현재 머리 규칙에 포함되지 않습니다.",
        "두 보조점수는 개별 원료의 구조 참고값입니다. 함량·노출량을 반영하지 않으며, 독성·알레르기 확률이나 피부·눈 모델의 판정 근거가 아닙니다.",
    ]
    return {"status": "complete", "schema_version": 2, "canonical_smiles": canonical,
            "preview": png_url(molecule), "properties": properties, "scores": scores,
            "patterns": patterns, "notes": notes,
            "source": {"name": metadata["name"], "version": metadata["version"],
                       "directory": "similarity", "sha256": metadata["sha256"],
                       "files": metadata["files"], "rdkit": rdBase.rdkitVersion}}
