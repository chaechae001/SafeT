"""Exercise hybrid authoring with fixed retrieval and gateway responses."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import assessment, authoring_rag
from services.auth import AuthError

from ai.assessment_authoring.contracts import load_catalog
from ai.assessment_authoring.fryer_work import decide
from ai.assessment_authoring.hybrid_frontdoor import HybridFrontDoor
from ai.assessment_authoring.mechanism_evidence import supports, unmapped_conveyor

CONVEYOR = "정지한 식기세척기 컨베이어의 롤러 사이에 끼인 접시를 손으로 빼냅니다."


def model_row(scenario_id, ref):
    return dict(scenario_id=scenario_id, work_ref=ref, controls=[])


@pytest.fixture
def generate(monkeypatch):
    catalog = load_catalog()
    ranker = HybridFrontDoor.__new__(HybridFrontDoor)
    ranker.by_id = {row["id"]: row for row in catalog["scenarios"]}
    monkeypatch.setenv("SAFET_AUTHORING_E5_MODEL_DIR", "synthetic-e5")
    monkeypatch.setattr(authoring_rag, "hybrid_ranker", lambda _: ranker)
    monkeypatch.setattr(authoring_rag, "qualified_candidates", lambda *a, **kw: {"candidates": []})
    monkeypatch.setattr(authoring_rag.catalog_ai, "gateway_url", lambda: "test")
    monkeypatch.setattr(authoring_rag.catalog_ai, "configuration", lambda: (None, "test", None))
    monkeypatch.setattr(authoring_rag.catalog_ai, "model_headers", lambda: {})

    def run(text, ranked, model_rows, expected_calls=1, truncated=False):
        ranker.rank_units = lambda *_: [{"scenario_ids": ranked}]
        content = json.dumps({"candidates": model_rows})
        response = dict(choices=[dict(finish_reason="stop", message={"content": content})])
        cut = dict(choices=[dict(finish_reason="length", message={"content": content[:-8]})])
        request = Mock(side_effect=[{"count": 800}, *([cut] if truncated else []), response])
        monkeypatch.setattr(authoring_rag, "request_json", request)
        _, rows, snapshot = authoring_rag.generate(catalog["scenarios"], {"text": text})
        calls = [call.args[2] for call in request.call_args_list]
        retry = ["/v1/chat/completions"] if truncated else []
        assert calls == (["/tokenize", "/v1/chat/completions"] + retry) * expected_calls
        if truncated:
            assert "frequency_penalty" in request.call_args_list[-1].args[3]
        return {row["authoring"]["analysis"]["scenario_id"] for row in rows}, snapshot

    return run


@pytest.mark.parametrize(("text", "state"), [
    ("튀김기는 쓰지 않지만 작업대와 바닥을 청소합니다.", "unused"),
    ("튀김기를 보유한 작업대에서 바닥을 청소합니다.", "unconfirmed"),
    ("튀김기가 있는 작업대에서 철판으로 조리합니다.", "unconfirmed"),
    ("튀김기 사용 여부를 확인하지 않았습니다.", "unconfirmed"),
    ("튀김기 기름을 교체합니다.", "used"),
    ("튀김기를 가끔 사용합니다.", "used"),
    ("치킨을 튀깁니다.", "used"),
    ("소스가 튀기 시작합니다.", "unmentioned"),
    ("튀김기는 오늘 켜지 않습니다.", "unused"),
    ("튀김기를 이번 주에는 사용하지 않습니다.", "unused"),
    # 다른 동사의 부정은 튀김기 미사용이 아니다.
    ("기름이 식지 않은 상태에서 튀김기를 청소합니다.", "used"),
    ("튀김기 전원을 끄지 않은 채 기름통을 닦습니다.", "unconfirmed"),
    ("튀김기를 끄지 않고 바구니를 꺼냅니다.", "unconfirmed"),
])
def test_fryer_requires_its_own_work(text, state):
    assert decide({"media": [{"id": "TEXT", "kind": "text", "text": text}]})[0] == state


def test_unused_fryer_stays_out_of_assessed_rows(generate):
    rows, snapshot = generate("튀김기는 쓰지 않지만 작업대와 바닥을 청소합니다.", ["FRY"], [], expected_calls=0)
    assert rows == set()
    assert snapshot["review_candidates"] == [{"scenario_id": "FRY", "reason": "input_denies_work"}]


def test_frying_without_equipment_name_is_assessed(generate):
    rows, snapshot = generate("치킨을 튀깁니다.", ["FRY"], [model_row("FRY", "S1")])
    assert rows == {"FRY"}
    assert snapshot["review_candidates"] == []


def test_truncated_hybrid_response_is_retried_once(generate):
    rows, _ = generate("치킨을 튀깁니다.", ["FRY"], [model_row("FRY", "S1")], truncated=True)
    assert rows == {"FRY"}


def test_fryer_inventory_does_not_remove_knife_work(generate):
    rows, snapshot = generate("튀김기를 보유한 작업대에서 칼로 양파를 썹니다.",
                              ["FRY", "KNIFE"], [model_row("KNIFE", "S1")])
    assert rows == {"KNIFE"}
    assert snapshot["review_candidates"] == [{"scenario_id": "FRY", "reason": "work_unconfirmed"}]


def test_missing_and_rejected_candidates_remain_for_review(generate):
    rows, snapshot = generate(
        "물기가 있는 바닥을 통행합니다. 박스를 밟고 올라가 선반 물건을 꺼냅니다.",
        ["ENV", "LADDER", "KNIFE"],
        [model_row("ENV", "S1"), model_row("KNIFE", "S2")],
    )
    assert rows == {"ENV"}
    assert snapshot["review_candidates"] == [
        {"scenario_id": "KNIFE", "reason": "work_unconfirmed"},
        {"scenario_id": "LADDER", "reason": "work_unconfirmed"},
    ]


def test_conveyor_exposure_remains_unmapped_without_a_catalog_row(generate):
    assert unmapped_conveyor(CONVEYOR)
    assert not supports("CUT", CONVEYOR)
    assert supports("CUT", "육절기 날 가까이 손을 댑니다.")
    rows, snapshot = generate(CONVEYOR, [], [])
    assert rows == set()
    assert snapshot["review_candidates"] == [{"scenario_id": "WASH", "reason": "work_unconfirmed"}]
    assert snapshot["unmatched_risks"] == ["컨베이어·롤러 끼임: 기준 연결 확인 필요 — " + CONVEYOR]


def test_e5_setup_checks_local_path_and_packages(monkeypatch, tmp_path: Path):
    ranker = Mock(side_effect=ImportError("torch"))
    monkeypatch.setattr(authoring_rag, "hybrid_ranker", ranker)
    monkeypatch.setenv("SAFET_ASSESSMENT_MODE", "authoring_rag_v1")
    monkeypatch.delenv("SAFET_AUTHORING_E5_MODEL_DIR", raising=False)
    authoring_rag.prepare_hybrid()
    ranker.assert_not_called()

    monkeypatch.setenv("SAFET_AUTHORING_E5_MODEL_DIR", str(tmp_path / "missing"))
    with pytest.raises(RuntimeError, match="SAFET_AUTHORING_E5_MODEL_DIR"):
        authoring_rag.prepare_hybrid()
    ranker.assert_not_called()

    monkeypatch.setenv("SAFET_AUTHORING_E5_MODEL_DIR", str(tmp_path))
    with pytest.raises(RuntimeError, match="SAFET_AUTHORING_E5_MODEL_DIR"):
        authoring_rag.prepare_hybrid()
    ranker.assert_called_once_with(str(tmp_path))

    ranker.reset_mock()
    ranker.side_effect = None
    authoring_rag.prepare_hybrid()
    ranker.assert_called_once_with(str(tmp_path))


def test_unmatched_only_draft_cannot_be_confirmed(monkeypatch):
    db = Mock()
    monkeypatch.setattr(assessment, "owned", lambda *args: {"generation_source": authoring_rag.SOURCE})
    monkeypatch.setattr(assessment, "writable", Mock())
    monkeypatch.setattr(assessment, "detail", lambda *args: {
        "items": [], "review_candidates": [], "unmatched_risks": [CONVEYOR],
    })
    body = SimpleNamespace(revision=1, items=[], excluded_review_candidates=None)
    with pytest.raises(AuthError) as error:
        assessment.save(db, "review@example.invalid", 1, body, confirm=True)
    assert error.value.code == "NO_ASSESSED_ROWS"
    db.commit.assert_not_called()
