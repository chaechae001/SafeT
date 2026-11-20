"""위험요인·법령 검색 모듈(ai/risk_law_search)을 평가표 생성에 연결한다.

SAFET_ASSESSMENT_MODE=catalog_rls_v1 이고 SAFET_RISK_LAW_URL(예: http://127.0.0.1:8020)이 있을 때 쓴다.
- 입력 글·음성 전사문 → 모듈 /api/analyze → 위험 카드 → 카드에 연결된 카탈로그 시나리오 → 평가표 행.
- 행의 현재·개선 대책은 모듈이 고른 추천 3개씩(AI 추천). 대책 → 기준 조치 연결은 모듈 연결표(검토 완료만 기본 반영)를 따른다.
- 위험도는 기존 공통 정책(domain.risk_policy, DB 카탈로그 버전)으로 계산한다. 모듈의 시험용 정책은 쓰지 않는다.
- 카드·입력 문장·법령 후보는 참고 정보(reference)다. 법령은 자동 검색 후보이며 정식 법령 칸·PDF에 넣지 않는다.
- 사업장 등록 기기(workplace_machine)도 검색어로 보낸다. 사업장이 쓰는 기기를 미리 입력한 것이다(사진 탐지 부담을 줄이는 용도).
  기기에서만 나온 행은 '등록 기기 기준'으로 구분하고 실제 작업 여부를 작성자가 확인한다. 입력 글에서 나온 행을 먼저 둔다.
"""
import json
import os
import urllib.error
import urllib.request

from services.auth import AuthError

SOURCE = 'catalog_rls_v1'
USABLE = ('auto', 'confirmed')  # 카드→시나리오 연결 상태 중 행을 만들 수 있는 것


def base_url():
    return os.getenv('SAFET_RISK_LAW_URL', '').strip().rstrip('/')


def analyze(text, voice_text, machines=()):
    base = base_url()
    if not base:
        raise AuthError(503, 'RISK_LAW_UNCONFIGURED', '위험요인 검색 서버 주소(SAFET_RISK_LAW_URL)를 설정해 주세요.')
    machines = [dict(machine_code=m.get('machine_code'), machine_nm=m.get('machine_nm'))
                for m in machines or () if isinstance(m, dict) and (m.get('machine_nm') or '').strip()][:100]
    body = json.dumps({'text': text or '', 'voice_text': voice_text or '', 'machines': machines},
                      ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(base + '/api/analyze', data=body, method='POST',
                                 headers={'Content-Type': 'application/json; charset=utf-8'})
    timeout = float(os.getenv('SAFET_RISK_LAW_TIMEOUT', '60'))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return json.loads(res.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 400:
            raise AuthError(422, 'RISK_LAW_INPUT', '작업 설명이나 음성 전사문을 확인해 주세요.') from None
        raise AuthError(503, 'RISK_LAW_FAILED', '위험요인 검색 서버가 응답하지 않습니다. 입력은 유지됩니다.') from None
    except (OSError, ValueError):
        raise AuthError(503, 'RISK_LAW_FAILED', '위험요인 검색 서버가 응답하지 않습니다. 입력은 유지됩니다.') from None


def _law(risk):
    law = risk.get('law')
    view = None
    if law:
        view = {k: law.get(k) for k in ('id', 'law_name', 'locator', 'article_title', 'effective_from', 'quote')}
        view['quote'] = (view['quote'] or '')[:500]
    return dict(candidate=view, basis=(risk.get('law_basis') or '')[:300],
                status='자동 검색 후보 · 적용 여부는 작성자가 확인')


def _options(options):
    return [dict(text=o['text'][:500], original=o.get('original', '')[:1000], origin=o.get('origin'),
                 origin_card=o.get('origin_card'), control=o.get('control') or
                 dict(control_id=None, status='unmapped', message='연결 정보 없음 · 위험도 계산 제외'))
            for o in options]


def rows(result, catalog):
    """모듈 응답 → (행 목록, 행을 만들지 못한 위험). 같은 시나리오는 한 행으로 합친다(공통 계약 MVP)."""
    byid = {s['id']: s for s in catalog}
    items, unmatched, seen = [], [], {}
    for unit in result.get('units', []):
        for risk in unit.get('risks', []):
            link = risk.get('scenario') or {}
            sid = link.get('scenario_id')
            from_machine = unit.get('source') == 'MACHINE'
            card = dict(card_id=risk['card_id'], title=risk['title'][:200], risk_type=risk.get('risk_type'),
                        input_text=(unit.get('text') or '')[:500], source=unit.get('source_label'),
                        from_machine=from_machine, low_confidence=bool(risk.get('low_confidence')))
            if link.get('status') not in USABLE or sid not in byid or risk.get('low_confidence'):
                unmatched.append(dict(card, reason=link.get('message') or '시나리오 연결 없음',
                                      scenario_status=link.get('status')))
                continue
            if sid in seen:
                seen[sid]['risk_law']['other_cards'].append(card)
                continue
            s = byid[sid]
            reference = dict(card=card, scenario_link=dict(status=link['status'], message=link.get('message')),
                             law=_law(risk), current=_options(risk.get('current_options', [])),
                             plans=_options(risk.get('improvement_options', [])), other_cards=[],
                             notice=('등록 기기 기준 AI 검색 결과 · 실제로 하는 작업인지 작성자 확인' if from_machine
                                     else 'AI 검색 결과 · 작성자 확인 후 사용'))
            item = dict(job=s['task'][:100], title=risk['title'][:200], type=(risk.get('risk_type') or s['event'])[:50],
                        cause=(risk.get('text') or s['scenario'])[:500], signal='N',
                        reason=('등록 기기(' + card['input_text'][:50] + ') 기준 AI 추천 위험요인 · 실제로 하는 작업인지와 현재 조치를 확인해 주세요.'
                                if from_machine else 'AI 추천 위험요인 · 작업 해당 여부와 현재 조치를 확인해 주세요.'),
                        curr=[o['text'] for o in reference['current']], plans=[o['text'] for o in reference['plans']],
                        catalog=s, risk_law=reference)
            seen[sid] = item
            items.append(item)
    return items, unmatched


def links(reference):
    """eval_action 정렬 순서(C·P별 0부터) → 기준 조치 ID. 연결 없는 추천은 넣지 않는다."""
    out = {}
    for kind, key in (('C', 'current'), ('P', 'plans')):
        for pos, o in enumerate(reference[key]):
            cid = (o.get('control') or {}).get('control_id')
            if cid:
                out[(kind, pos)] = cid
    return out
