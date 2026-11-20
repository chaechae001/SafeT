"""카드 JSONL과 기기·위험요인 ID 대조표를 MariaDB에 적재한다."""
import argparse
import json
import re
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from services.risk_cards import EQUIPMENT_IDS, SCENARIO_IDS, save_cards


KINDS = {"case": "case", "check": "checklist", "reference": "reference"}
MIGRATION = Path(__file__).resolve().parent / "migrations/20261119_risk_cards.sql"


def codes(value):
    return [] if value == "-" else sorted({part.strip().strip("`") for part in value.split(",")})


def load_inputs(cards_path, table_path):
    source = cards_path.read_text(encoding="utf-8-sig")
    blocks = re.findall(r"^\s*```jsonl\s*\n(.*?)^\s*```\s*$", source, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError("카드 파일에 JSONL 코드 블록 한 개가 필요합니다.")
    cards = {}
    for line in blocks[0].splitlines():
        if not line.strip():
            continue
        card = json.loads(line)
        card_id = card.get("id") if isinstance(card, dict) else None
        if not isinstance(card_id, str) or not re.fullmatch(r"[A-Z0-9-]{1,60}", card_id) or card_id in cards:
            raise ValueError("카드 ID 형식이 잘못됐거나 중복됐습니다.")
        cards[card_id] = card

    table = table_path.read_text(encoding="utf-8-sig")
    section = re.search(r"^## 3\. 카드 근거[^\n]*\n(.*?)(?=^## |\Z)", table, re.M | re.S)
    rows = [line for line in section[1].splitlines() if line.startswith("|")] if section else []
    if not rows or not rows[0].startswith("| 카드 ID | evidence_id"):
        raise ValueError("ID 대조표의 카드 근거 표를 찾을 수 없습니다.")
    used = set()
    results = []
    for line in rows[2:]:
        columns = [cell.strip().strip("`") for cell in re.split(r"(?<!\\)\|", line)[1:-1]]
        if len(columns) != 8:
            raise ValueError("카드 근거 표는 8개 열이어야 합니다.")
        card_id, evidence_id, kind, _, equipment, scenarios, tags, source_ref = columns
        if card_id not in cards or card_id in used:
            raise ValueError(f"카드와 대조표의 ID가 일치하지 않습니다. {card_id}")
        used.add(card_id)
        card = cards[card_id]
        source = re.fullmatch(r"([A-Z0-9-]{1,60}) p([1-9][0-9]{0,4})", source_ref)
        title = card.get("title")
        card_source = card.get("source")
        if (kind != KINDS.get(str(card.get("type"))) or evidence_id != f"kras:card-v1:{kind}:{card_id}"
                or not isinstance(title, str) or not title.strip() or len(title) > 255
                or not source or not isinstance(card_source, dict)
                or source[2] != str(card_source.get("page")) or int(source[2]) > 65535):
            raise ValueError(f"카드 종류, 근거 ID, 제목 또는 출처가 일치하지 않습니다. {card_id}")
        equipment_ids, scenario_refs = codes(equipment), codes(scenarios)
        scenario_ids = [value for value in scenario_refs if value in SCENARIO_IDS]
        unresolved = [value for value in scenario_refs if value not in SCENARIO_IDS]
        if not set(equipment_ids) <= EQUIPMENT_IDS or any(
            value != "REF" and not re.fullmatch(r"(NEW|HOLD):[A-Z][A-Z0-9_]{0,55}", value)
            for value in unresolved
        ):
            raise ValueError(f"등록되지 않은 표준 기기 또는 시나리오 ID입니다. {card_id}")
        results.append(dict(evidence_id=evidence_id, card_id=card_id, kind=kind, title=title,
                            source_code=source[1], source_page=int(source[2]), card_data=card, hazard_tags=codes(tags),
                            unresolved_scenario_refs=unresolved, equipment_ids=equipment_ids, scenario_ids=scenario_ids))
    if not results or used != set(cards):
        raise ValueError("모든 원본 카드에 대응하는 대조표 행이 필요합니다.")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=Path, required=True, help="카드 데이터 Markdown")
    parser.add_argument("--id-table", type=Path, required=True, help="카드 ID 대조표 Markdown")
    args = parser.parse_args()
    try:
        cards = load_inputs(args.cards, args.id_table)
        from database import engine

        with engine.begin() as db:
            for statement in MIGRATION.read_text(encoding="utf-8").split(";"):
                if statement.strip():
                    db.exec_driver_sql(statement)
        with engine.begin() as db:
            inserted = save_cards(db, cards)
    except (OSError, RuntimeError, ValueError) as problem:
        parser.exit(1, f"카드 적재 실패 · {problem}\n")
    except SQLAlchemyError as problem:
        parser.exit(1, f"DB 연결 또는 적재 실패 · {type(problem).__name__}\n")
    print(f"카드 {len(cards)}건 확인 · 신규 {inserted}건 · 기존 {len(cards) - inserted}건")


if __name__ == "__main__":
    main()
