import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from import_risk_cards import load_inputs


@pytest.fixture
def inputs(tmp_path):
    cards = tmp_path / "cards.md"
    table = tmp_path / "ids.md"
    original = {"id": "TEST-H1", "type": "check", "title": "합성 점검", "source": {"page": 7},
                "measures_extra": [{"text": "합성 조치", "from": "TEST-H1"}], "laws": ["합성 법령명"]}
    cards.write_text("```jsonl\n" + json.dumps(original, ensure_ascii=False) + "\n```\n", encoding="utf-8")
    table.write_text(
        "## 3. 카드 근거 (evidence_id 기준)\n\n"
        "| 카드 ID | evidence_id (제안) | 종류 | 제목 | 기기 | 위험요인 | 위험 태그 | 출처 |\n"
        "|---|---|---|---|---|---|---|---|\n"
        "| TEST-H1 | `kras:card-v1:checklist:TEST-H1` | checklist | 합성 점검 | `EQ_FRYER`, `EQ_OVEN`"
        " | FRY, NEW:TMP_CONTACT | `burn` | CARD-TEST p7 |\n\n## 4. 확인 필요\n",
        encoding="utf-8",
    )
    return cards, table, original


def test_preserves_raw_card_and_resolves_only_catalog_ids(inputs):
    cards, table, original = inputs
    row, = load_inputs(cards, table)
    assert row["card_data"] == original
    assert row["kind"] == "checklist"
    assert row["equipment_ids"] == ["EQ_FRYER", "EQ_OVEN"]
    assert row["scenario_ids"] == ["FRY"]
    assert row["unresolved_scenario_refs"] == ["NEW:TMP_CONTACT"]
    assert row["hazard_tags"] == ["burn"]


@pytest.mark.parametrize(("before", "after"), [
    ("EQ_FRYER", "EQ_UNKNOWN"),
    ("NEW:TMP_CONTACT", "TMP_CONTACT"),
    ("CARD-TEST p7", "CARD-TEST p8"),
    ("checklist:TEST-H1", "checklist:OTHER"),
])
def test_rejects_invalid_mapping(inputs, before, after):
    cards, table, _ = inputs
    table.write_text(table.read_text(encoding="utf-8").replace(before, after), encoding="utf-8")
    with pytest.raises(ValueError):
        load_inputs(cards, table)
