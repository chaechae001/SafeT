"""공동 위험 카드의 DB 적재와 근거 조회."""
import json
from pathlib import Path

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[2]
EQUIPMENT_IDS = frozenset(json.loads(
    (ROOT / "contracts/assessment_authoring/v1/reference/equipment_ids.json").read_text(encoding="utf-8")
))
SCENARIO_IDS = frozenset(row["id"] for row in json.loads(
    (ROOT / "contracts/catalog_risk/catalog.json").read_text(encoding="utf-8")
)["scenarios"])

JSON_COLUMNS = ("card_data", "hazard_tags", "unresolved_scenario_refs")
SELECT_CARD = """
    SELECT c.*,
        COALESCE((SELECT JSON_ARRAYAGG(e.equipment_id ORDER BY e.equipment_id)
                  FROM risk_card_equipment e WHERE e.evidence_id = c.evidence_id), '[]') AS equipment_ids,
        COALESCE((SELECT JSON_ARRAYAGG(s.scenario_id ORDER BY s.scenario_id)
                  FROM risk_card_scenario s WHERE s.evidence_id = c.evidence_id), '[]') AS scenario_ids
    FROM risk_card c
"""


def decode(row):
    result = dict(row)
    for key in (*JSON_COLUMNS, "equipment_ids", "scenario_ids"):
        result[key] = json.loads(result[key])
    return result


def load_cards(db, *, equipment_id=None, scenario_id=None, limit=50):
    filters = []
    if equipment_id is not None:
        filters.append("""EXISTS (SELECT 1 FROM risk_card_equipment e
                     WHERE e.equipment_id = :equipment_id AND e.evidence_id = c.evidence_id)""")
    if scenario_id is not None:
        filters.append("""EXISTS (SELECT 1 FROM risk_card_scenario s
                     WHERE s.scenario_id = :scenario_id AND s.evidence_id = c.evidence_id)""")
    if not filters:
        raise ValueError("기기 ID 또는 시나리오 ID가 필요합니다.")
    sql = SELECT_CARD + " WHERE " + " AND ".join(filters) + " ORDER BY c.evidence_id LIMIT :limit"
    params = {"equipment_id": equipment_id, "scenario_id": scenario_id, "limit": limit}
    return [decode(row) for row in db.execute(text(sql), params).mappings()]


def save_cards(db, cards):
    """호출자 트랜잭션에서 새 ID만 적재하고, 같은 ID의 다른 데이터는 거절한다."""
    inserted = 0
    for card in sorted(cards, key=lambda item: item["evidence_id"]):
        previous = db.execute(text(SELECT_CARD + " WHERE c.evidence_id = :evidence_id FOR UPDATE"),
                              {"evidence_id": card["evidence_id"]}).mappings().one_or_none()
        if previous is not None:
            existing = decode(previous)
            if any(existing[key] != value for key, value in card.items()):
                raise ValueError(f"기존 카드 또는 연결과 충돌합니다. {card['evidence_id']}")
            continue
        values = dict(card, **{key: json.dumps(card[key], ensure_ascii=False) for key in JSON_COLUMNS})
        db.execute(text("""
            INSERT INTO risk_card
                (evidence_id, card_id, kind, title, source_code, source_page,
                 card_data, hazard_tags, unresolved_scenario_refs)
            VALUES (:evidence_id, :card_id, :kind, :title, :source_code, :source_page,
                    :card_data, :hazard_tags, :unresolved_scenario_refs)
        """), values)
        if card["equipment_ids"]:
            db.execute(text("""
                INSERT INTO risk_card_equipment (equipment_id, evidence_id) VALUES (:id, :evidence_id)
            """), [{"id": item, "evidence_id": card["evidence_id"]} for item in card["equipment_ids"]])
        if card["scenario_ids"]:
            db.execute(text("""
                INSERT INTO risk_card_scenario (scenario_id, evidence_id) VALUES (:id, :evidence_id)
            """), [{"id": item, "evidence_id": card["evidence_id"]} for item in card["scenario_ids"]])
        inserted += 1
    return inserted
