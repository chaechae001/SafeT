"""E5(review_unverified)를 켜도 등록 기기 위험은 행, 미등록 기기 위험은 확인 대기(UX-024)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services import risk_law


def found(kind):
    return dict(catalog=dict(id='MIX'), risk_law=dict(
        card=dict(machine_kind=kind, from_machine=True, input_text='반죽기 회전부 청소'),
        other_cards=[], law=dict(candidate=None)))


@pytest.mark.parametrize(('kind', 'where'), [('registered', 'items'), ('unregistered', 'pending')])
@pytest.mark.parametrize('review_unverified', [False, True])
def test_registered_machine_risk_is_a_row_even_with_e5(monkeypatch, kind, where, review_unverified):
    row = found(kind)
    monkeypatch.setattr(risk_law, 'authoring_search_input', lambda ctx: ([{'machine_nm': '반죽기'}], set()))
    monkeypatch.setattr(risk_law, 'analyze', lambda *a, **kw: {})
    monkeypatch.setattr(risk_law, 'rows', lambda *a, **kw: ([row], None))
    monkeypatch.setattr(risk_law, 'split_pending', lambda found_, registered: (found_, []))
    items, snapshot = [], dict(review_candidates=[])
    risk_law.supplement_authoring(items, snapshot, [], dict(text='닭을 칼로 손질합니다.', voice_text=''),
                                  ['반죽기'], review_unverified=review_unverified)
    assert (items, snapshot['rls_pending']) == (([row], []) if where == 'items' else ([], [row]))
