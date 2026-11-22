"""위험도 정답셋 회귀 검사: 팀 확정 문서에서 만든 기대 신호와 서비스 계산 경로(evaluate·일반 평가표·DB 기준·input_based)를 대조한다.

정답셋·평가 스크립트: ai/experiments/261122_위험도정확도평가_DR/. DB·모델 없이 실행한다.
문서 기준과 계산이 어긋나면 이 검사가 실패한다. 기준 변경은 문서와 정답셋을 함께 고친다.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'ai/experiments/261122_위험도정확도평가_DR/eval_risk_levels.py'
_spec = importlib.util.spec_from_file_location('eval_risk_levels', SCRIPT)
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def _gold():
    return [json.loads(line) for line in ev.GOLD.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_saved_gold_matches_document_tables():
    """저장된 정답셋이 문서 표에서 다시 만든 정답셋과 같다(손으로 고친 정답 방지)."""
    assert _gold() == ev.build_gold()


def test_service_paths_match_gold():
    rows = ev.run_gold(_gold())
    bad = [(r['id'], r['path'], r['scenario_id'], r['expected'], r['actual'], r['error']) for r in rows if not r['ok']]
    assert not bad
    assert {r['path'] for r in rows} == {'evaluate', 'rls_create', 'rls_save', 'catalog_save', 'input_based'}


def test_1122_signals_follow_input_based_contract():
    """11/22 실모델 결과의 모든 R은 계약 v1(1.1 표, unknown=계산상 미충족) 기대와 같다."""
    rows = ev.replay_1122()
    assert rows and all(r['ok'] for r in rows)


def test_public_cases_are_not_scored_without_conversion_rule():
    """공개 사례는 척도 변환 기준이 없어 등급 정확도에서 제외하고 사유를 남긴다."""
    rows = ev.public_cases()
    assert len(rows) == 8 and not any(r['grade_comparable'] for r in rows)
    assert all(r['exclusion_reasons'] for r in rows)
