"""기기 ID로 검수한 시나리오 연결과 문헌 근거를 조회한다."""
from sqlalchemy import bindparam, text


def for_equipment(db, equipment_ids):
    if not equipment_ids:
        return []
    query = text("""
        SELECT equipment_id, candidate_id, scenario_id, hazard_tag, hazard,
               evidence_id, document_id, pdf_page, locator, evidence_summary
        FROM risk_equipment_evidence
        WHERE equipment_id IN :equipment_ids
        ORDER BY equipment_id, candidate_id, evidence_id
    """).bindparams(bindparam("equipment_ids", expanding=True))
    return [dict(row) for row in db.execute(query, {"equipment_ids": equipment_ids}).mappings()]
