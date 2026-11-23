"""문서 다운로드(결과서 PDF) 단위 테스트 · DB 없이 가짜 조회값으로 확인

실행 (저장소 루트): backend\\.venv\\Scripts\\python -m pytest backend/unit_tests/test_report.py -q
값은 합성 예시이며 실제 현장 자료가 아닙니다.
"""
import sys
from datetime import date, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from services import report_service as rs  # noqa: E402
from services.auth import AuthError  # noqa: E402

MST = dict(eval_no=1, workplace='시험 매장', biz_nm='치킨', eval_nm='11월 <주방> 평가', eval_writer='작성자',
           eval_dt=datetime(2026, 11, 14), confirm_dt=None, sign_end_dt=None, eval_status='W',
           generation_source='demo')
DTL = [
    # 상 · 대책 2개(1개는 직접 추가) · 개선 후 중
    dict(eval_dtl_no=11, job='튀김', risk_factor='기름 튐', risk_type='화상', reason='물기', curr_risk_grade='R',
         keep_yn=None, curr_none_yn='N', after_risk_grade='Y', manager_nm='가', due_dt=date(2026, 11, 20),
         law=None, law_summary=None),
    # 하 · 현재 상태 유지 → 대책·담당자·예정일 숨김
    dict(eval_dtl_no=12, job='칼', risk_factor='베임', risk_type='베임', reason=None, curr_risk_grade='G',
         keep_yn='Y', curr_none_yn='N', after_risk_grade='N', manager_nm='나', due_dt=date(2026, 12, 1),
         law=None, law_summary=None),
    # 판단 필요 · 개선 후도 판단 필요 → '내려감'으로 세지 않음
    dict(eval_dtl_no=13, job='현장', risk_factor='확인 필요', risk_type='미분류', reason=None, curr_risk_grade='N',
         keep_yn=None, curr_none_yn='Y', after_risk_grade='N', manager_nm=None, due_dt=None,
         law=None, law_summary=None),
]
ACT = [
    dict(eval_dtl_no=11, action_type='C', action_text='집게', ai_yn='Y'),
    dict(eval_dtl_no=11, action_type='P', action_text='방지판', ai_yn='Y'),
    dict(eval_dtl_no=11, action_type='P', action_text='교육', ai_yn='N'),
    dict(eval_dtl_no=12, action_type='P', action_text='유지인데 남은 대책', ai_yn='Y'),
]


def fetch(sql, params):
    if 'FROM eval_mst' in sql:
        return [MST]
    if 'FROM eval_member' in sql:
        return [dict(member_no=1, member_nm='근로자1')]
    if 'FROM eval_machine' in sql:
        return [dict(machine_nm='튀김기')]
    if 'FROM eval_dtl' in sql:
        return DTL
    if 'FROM eval_action' in sql:
        return ACT
    if 'FROM eval_sign' in sql:
        return [dict(member_no=1, sign_img='https://example.invalid/x.png', confirm_yn='Y', sign_dt=datetime(2026, 11, 15, 9, 0))]
    raise AssertionError(sql)


def test_요약_판단필요는_따로_세고_내려감에서_제외():
    ctx = rs.build_context(1, fetch)
    assert ctx['sum'] == dict(total=3, R=1, Y=0, G=1, N=1, plans=2, after_down=1, last_due='2026.11.20')
    keep = ctx['rows'][1]
    assert keep['keep'] and keep['plans'] == [] and keep['manager'] is None and keep['due_dt'] is None
    assert ctx['rows'][0]['plans'][1] == {'text': '교육', 'ai': False}


def test_미확정_시험용_표시와_외부_서명이미지_차단():
    ctx = rs.build_context(1, fetch)
    assert ctx['draft'] and ctx['demo'] and '합성' in ctx['method']
    assert ctx['signs'][0]['img'] is None and ctx['signs'][0]['confirm']
    html = rs.render_html(ctx)
    assert '미확정본' in html and '시험용 합성 자료' in html
    assert '&lt;주방&gt;' in html                      # 평가명 HTML 이스케이프
    assert '가능성' not in html                         # 판단 기준표·가능성 열 제외 (팀 결정 전)


def test_파일이름():
    ctx = rs.build_context(1, fetch)
    assert rs.file_name(ctx) == '11월 _주방_ 평가_위험성평가결과서_미확정.pdf'


def test_폰트_없으면_503(monkeypatch):
    monkeypatch.setattr(rs, '_font_ready', False)
    monkeypatch.setattr(rs, 'FONT_CANDIDATES', [])
    monkeypatch.setenv('REPORT_FONT_REGULAR', '')
    with pytest.raises(AuthError) as e:
        rs._register_font()
    assert e.value.status == 503


def test_PDF_생성():
    if not any(Path(r).is_file() for r, _ in rs.FONT_CANDIDATES):
        pytest.skip('한글 폰트 없음 (REPORT_FONT_REGULAR 지정 필요)')
    pdf = rs.render_pdf(rs.build_context(1, fetch))
    assert pdf.startswith(b'%PDF') and len(pdf) > 10000


def test_법령_검색후보는_상태문구와_함께_표시():
    """UX-020: 일반 평가표는 law 칸이 비어 있고 catalog_state.risk_law.law.candidate 에 후보가 있다."""
    import json
    state = json.dumps({'risk_law': {'law': {'candidate': {'law_name': '산업안전보건기준에 관한 규칙', 'locator': '제239조',
                                                          'article_title': '위험물 등이 있는 장소에서 화기 등의 사용 금지'},
                                            'status': '자동 검색 후보 · 적용 여부는 작성자가 확인'}}}, ensure_ascii=False)
    got = rs._law(dict(law=None, law_summary=None, catalog_state=state))
    assert got['law'] == '산업안전보건기준에 관한 규칙 제239조' and '위험물' in got['law_summary'] and '작성자가 확인' in got['law_note']
    assert rs._law(dict(law='저장된 법령', law_summary='요약'))['law_note'] is None          # 저장된 법령이 우선
    assert rs._law(dict(law=None, catalog_state='깨진 값'))['law'] is None                    # 읽지 못하면 비움


def test_결과서_로고와_모바일_용지():
    html = rs.render_html(rs.build_context(1, fetch))
    assert 'data:image/png;base64,' in html and 'a5 portrait' in html


def test_항목_카드는_쪽마다_하나씩이_아니라_이어서_배치():
    """UX-021: 카드마다 새 쪽으로 넘기던 구조(강제 쪽 넘김·여백 있는 묶음)를 쓰지 않는다.
    카드는 여백 없는 page-break-inside: avoid 묶음으로만 감싸 잘리지 않고 이어서 놓인다."""
    import re
    html = rs.render_html(rs.build_context(1, fetch))
    assert '<pdf:nextpage' not in html
    keeps = re.findall(r'<div style="([^"]*page-break-inside: avoid[^"]*)"', html)
    assert len(keeps) == 3 + 1 and all('padding' not in k and 'margin' not in k for k in keeps)   # 카드 3 + 서명 1
    assert '현재 안전조치' in html and '개선대책' in html and '개선 후 (예상)' in html
