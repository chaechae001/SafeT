"""기기 직접 언급 근거만 원본 연결 행과 대조해 전달하는 보수적 검수 필터."""
import copy
from .contracts import require

def qualify_direct_evidence(response, link_rows):
    qualified = copy.deepcopy(response)
    exclusions = []
    for candidate in qualified["candidates"]:
        accepted = []
        for row in link_rows:
            if row["equipment_id"] not in candidate["equipment_ids"] or row["hazard_code"] != candidate["hazard_code"]:
                continue
            require(row["source_id"] in candidate["source_ids"], "link source absent from search")
            if (row.get("evidence_tier") != "A" or
                row.get("equipment_match", {}).get("where") != "위험요인 문장" or
                not row.get("standard_name") or
                row["standard_name"] not in row["hazard_text"] or
                row["source_id"].startswith("CASE-")):
                exclusions.append(dict(link_id=row["link_id"], reason="기기 직접 언급 근거 아님"))
                continue
            accepted.append({k:row[k] for k in ("link_id","hazard_text","source_id","source_file","pdf_pages")})
        candidate["source_evidence"] = accepted
        candidate["source_ids"] = list(dict.fromkeys(r["source_id"] for r in accepted))
        candidate["hazard_texts"] = list(dict.fromkeys(r["hazard_text"] for r in accepted))
        # 원래 대책 집계는 문장과 1:1 연결되지 않으므로 여기서 현장 대책 근거로 전달하지 않는다.
        candidate["measures"] = []
    return qualified, exclusions

