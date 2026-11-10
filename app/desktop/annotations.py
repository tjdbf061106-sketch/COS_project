"""Optional PubChem source excerpts; no clinical interpretation or silent lookup."""
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone


def _json(url, data=None):
    request = urllib.request.Request(url, data=data, headers={"User-Agent": "COSLab/0.2 PubChem annotation lookup"})
    with urllib.request.urlopen(request, timeout=18) as response:
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("주석 응답이 너무 큽니다. PubChem 원문을 확인해 주세요.")
    return json.loads(content)


def summarize_record(data, cid):
    record = data.get("Record", {})
    references = {item.get("ReferenceNumber"): item for item in record.get("Reference", [])}
    entries = []
    def visit(node):
        for item in node.get("Information", []):
            reference = references.get(item.get("ReferenceNumber"), {})
            for block in item.get("Value", {}).get("StringWithMarkup", []):
                text = block.get("String", "").strip()
                if not text or any(x["text"] == text for x in entries):
                    continue
                url = reference.get("URL", "")
                if not url.startswith("https://"):
                    url = f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}"
                entries.append({"text": text, "source": reference.get("SourceName", "PubChem"), "url": url})
        for section in node.get("Section", []):
            visit(section)
    visit(record)
    entries.sort(key=lambda item: not any("가" <= char <= "힣" for char in item["text"]))
    for item in entries:
        item["truncated"] = len(item["text"]) > 350
        item["text"] = item["text"][:350] + ("…" if item["truncated"] else "")
    return {"status": "complete" if entries else "empty", "cid": cid,
            "title": record.get("RecordTitle", ""), "entries": entries[:3],
            "source_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "note": "PubChem 물질 설명의 원문 발췌입니다. 자동 번역·독성 판정은 하지 않습니다."}


def fetch_annotations(smiles):
    if not isinstance(smiles, str) or not 1 <= len(smiles) <= 10000:
        raise ValueError("주석을 조회할 원료 구조가 필요합니다.")
    try:
        body = urllib.parse.urlencode({"smiles": smiles}).encode("ascii")
        data = _json("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/cids/JSON", body)
        identifiers = list(dict.fromkeys(data.get("IdentifierList", {}).get("CID", [])))
        if len(identifiers) != 1:
            return {"status": "unresolved", "entries": [], "note": "PubChem 물질을 하나로 확인하지 못했습니다. 여러 후보의 주석을 합치지 않았습니다."}
        cid = int(identifiers[0])
        data = _json(f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{cid}/JSON?heading=Record+Description")
        return summarize_record(data, cid)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"status": "empty", "entries": [], "note": "PubChem에 해당 구조 또는 공개 설명이 없습니다. 자료 없음은 안전 판정이 아닙니다."}
        raise ValueError("PubChem 주석을 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValueError("PubChem에 연결하지 못했습니다. 로컬 분석 결과는 계속 확인할 수 있습니다.") from exc
