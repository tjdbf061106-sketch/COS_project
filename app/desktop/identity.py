"""Exact compound references. Chemistry runs in the model workers, not the GUI process."""
import copy
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache

from desktop.paths import resources

_resolved_titles = {}


def name_key(value):
    # Preserve stereochemical signs, isotope labels and punctuation that can distinguish names.
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).strip()).casefold()


@lru_cache(maxsize=1)
def catalog():
    return json.loads((resources() / "desktop" / "identity_catalog.json").read_text(encoding="utf-8"))["compounds"]


def local_references(query):
    key = name_key(query)
    return [record for record in catalog() if key in {name_key(v) for v in [record["name"], *record["aliases"]]}]


@lru_cache(maxsize=256)
def references(query):
    local = local_references(query)
    if local:
        return local
    if name_key(query) in _resolved_titles:
        return _resolved_titles[name_key(query)]
    encoded = urllib.parse.quote(query, safe="")
    url = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/" + encoded
    url += "/property/Title,CanonicalSMILES,IsomericSMILES/JSON"
    request = urllib.request.Request(url, headers={"User-Agent": "COSLab/0.3 (compound identity)"})
    try:
        with urllib.request.urlopen(request, timeout=18) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("검색 결과가 너무 많습니다. CAS 번호로 다시 검색해 주세요.")
        properties = json.loads(raw).get("PropertyTable", {}).get("Properties", [])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError("등록된 이름을 찾지 못했습니다.") from exc
        raise ValueError("PubChem 조회가 지연되고 있습니다. 잠시 후 다시 확인해 주세요.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("이름 확인 서비스에 연결하지 못했습니다. 잠시 후 다시 확인해 주세요.") from exc
    if not properties or len(properties) > 5:
        raise ValueError("일치하는 원료를 특정하지 못했습니다. CAS 번호로 다시 검색해 주세요.")
    records = [{"name": p.get("Title", query), "aliases": [query],
             "smiles": p.get("SMILES") or p.get("IsomericSMILES") or p.get("ConnectivitySMILES") or p.get("CanonicalSMILES"),
             "cid": p["CID"], "cas": "", "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{p['CID']}"}
            for p in properties if p.get("SMILES") or p.get("ConnectivitySMILES") or p.get("CanonicalSMILES")]
    for record in records:
        title = name_key(record["name"])
        existing = _resolved_titles.setdefault(title, [])
        if not any(r["cid"] == record["cid"] for r in existing):
            existing.append(record)
    return records


def identifiers(row):
    values = []
    name = str(row.get("name") or "").strip()
    if name and name != "직접 입력 원료" and name != row.get("canonical_smiles"):
        values.append(name)
    if row.get("mode", "name") != "smiles":
        query = str(row.get("query") or "").strip()
        if query and query != row.get("canonical_smiles") and query != "직접 입력 원료":
            values.append(query)
    if row.get("cas"):
        values.append(str(row["cas"]).strip())
    return list(dict.fromkeys(values))


def check_components(rows, canonicalize):
    """Return verified copies, per-row issues and a compact audit; never rewrite original input."""
    reference_groups, errors = [], {}
    for index, row in enumerate(rows):
        groups = []
        for identifier in identifiers(row):
            try:
                found = references(identifier)
                if not found:
                    raise ValueError("일치하는 구조를 찾지 못했습니다.")
                groups.append(found)
            except ValueError as exc:
                errors[index] = str(exc)
                break
        reference_groups.append(groups)
    # Batch normalization keeps parsing independent of ingredient count and preserves full molecules.
    all_smiles = list(dict.fromkeys([row["canonical_smiles"] for row in rows]
        + [record["smiles"] for record in catalog()]
        + [record["smiles"] for groups in reference_groups for group in groups for record in group]))
    normalized = dict(zip(all_smiles, canonicalize(tuple(all_smiles))))
    verified, issues, audit = [], [], []
    for index, row in enumerate(rows):
        name = row.get("name") or row.get("query") or row["canonical_smiles"]
        actual = normalized[row["canonical_smiles"]]
        issue = errors.get(index)
        code = "identity_unverified"
        matching = []
        if not actual.get("canonical_smiles"):
            issue, code = actual.get("error", "구조를 해석하지 못했습니다."), "invalid_smiles"
        elif not issue:
            for group in reference_groups[index]:
                candidates = [record for record in group if normalized[record["smiles"]].get("canonical_smiles") == actual["canonical_smiles"]]
                if not candidates:
                    issue, code = "성분명과 SMILES가 일치하지 않습니다.", "name_structure_mismatch"
                    break
                matching.extend(candidates)
        if issue:
            issues.append({"component_id": row.get("component_id"), "field": "canonical_smiles", "code": code,
                           "message": f"{name}: {issue} 성분명으로 다시 검색하거나 이름을 지우고 SMILES만 입력해 주세요."})
            continue
        matching.extend(record for record in catalog()
                        if normalized[record["smiles"]].get("canonical_smiles") == actual["canonical_smiles"])
        aliases = list(dict.fromkeys(value for record in matching for value in [record["name"], *record["aliases"]]))
        component = copy.deepcopy(row)
        component.update(canonical_smiles=actual["canonical_smiles"], identity_aliases=aliases)
        verified.append(component)
        audit.append({"component_id": row.get("component_id"), "name": name,
                      "status": "verified" if reference_groups[index] else "structure_only",
                      "canonical_smiles": actual["canonical_smiles"],
                      "source_urls": sorted({r["source_url"] for r in matching})})
    return {"active": verified, "issues": issues, "identities": audit}
