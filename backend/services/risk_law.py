"""위험요인·법령 검색 모듈(ai/risk_law_search)을 평가표 생성에 연결한다.

SAFET_ASSESSMENT_MODE=catalog_rls_v1 이고 SAFET_RISK_LAW_URL(예: http://127.0.0.1:8020)이 있을 때 쓴다.
- 입력 글·음성 전사문 → 모듈 /api/analyze → 위험 카드 → 카드에 연결된 카탈로그 시나리오 → 평가표 행.
- 행의 현재 안전조치·개선대책은 시나리오 카탈로그(신규: FOOD-3LEVEL-1.2)의 기준 조치로 직접 구성한다(control_id 보유).
  모듈 추천 문구는 검토 완료(confirmed) 연결이면 해당 기준 조치를 앞에 두고, 미확정·미연결이면 저장만 하고 계산에서 제외한다.
- 위험도는 공통 판정 함수(domain.risk_policy.evaluate)와 DB 카탈로그 시나리오로 계산한다.
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
    """관련 법령 후보: 검색 모듈이 주제를 맞춘 1순위(law)만 쓴다. 없으면 후보 없음('찾지 못함').
    UX-024(2026-11-23 사용자 결정): UX-023의 참고 법령 대체(카드 연결 법령·검색 1순위로 채움)는 되돌린다.
    직접 맞는 법령이 없을 때 유사 법령을 가져오는 기능은 추후 백엔드 법령 검색 작업에서 다룬다(임의 조문으로 채우지 않음)."""
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


def control_options(scenario, kind, recs):
    """기준 조치(핵심 → 보완 순, 검토 완료 추천은 맨 앞) + 계산 제외 추천. kind: current | plans."""
    key = 'current_text' if kind == 'current' else 'plan_text'
    known = {c['id'] for c in scenario['controls']}
    recommended, extras = [], []
    for o in _options(recs):
        cid = o['control'].get('control_id')
        if cid in known:
            if cid not in recommended:
                recommended.append(cid)
        else:  # 미확정·미연결·다른 시나리오 ID: 저장하고 계산에서 제외
            control = dict(o['control'], control_id=None)
            if control.get('status') in ('confirmed', 'auto'):
                control.update(status='unmapped', message='이 시나리오의 기준 조치에 연결되지 않음 · 위험도 계산 제외')
            extras.append(dict(o, control=control))
    ordered = ([c for cid in recommended for c in scenario['controls'] if c['id'] == cid]
               + [c for c in scenario['controls'] if c['critical'] and c['id'] not in recommended]
               + [c for c in scenario['controls'] if not c['critical'] and c['id'] not in recommended])
    out = [dict(text=c[key][:500], original=c[key][:1000], origin='기준 조치' + (' · AI 추천' if c['id'] in recommended else ''),
                origin_card=None, control=dict(control_id=c['id'], status='catalog', critical=c['critical'],
                                               recommended=c['id'] in recommended,
                                               message=('핵심' if c['critical'] else '보완') + ' 기준 조치 · 위험도 계산 반영'))
           for c in ordered]
    texts = {o['text'] for o in out}
    return out + [o for o in extras if o['text'] not in texts]


def machine_identity(unit):
    # 검색 서버의 MACHINE:<코드> 또는 코드 없는 기기의 MACHINE:<순번>.
    prefix, _, value = (unit.get('unit_id') or '').partition(':')
    return unit.get('machine_code') or (value if prefix == 'MACHINE' and not value.isdecimal() else None)


def registered_matcher(registered):
    codes, names = set(), set()
    for machine in registered or ():
        if isinstance(machine, dict):
            if machine.get('machine_code'):
                codes.add(machine['machine_code'])
            machine = machine.get('machine_nm')
        names.add(_key(machine))
    def matches(code, name):
        return code in codes if code and codes else _key(name) in names
    return matches


def rows(result, catalog, registered=None):
    """모듈 응답 → (행 목록, 행을 만들지 못한 위험). 같은 시나리오는 한 행으로 합친다(공통 계약 MVP)."""
    byid = {s['id']: s for s in catalog}
    items, unmatched, seen = [], [], {}
    matches = registered_matcher(registered)
    def priority(unit):
        if unit.get('source') != 'MACHINE':
            return 0
        return 1 if matches(machine_identity(unit), unit.get('text')) else 2
    # 대표 카드와 그 카드의 법령·조치를 함께 선택한다.
    for unit in sorted(result.get('units', []), key=priority):
        for risk in unit.get('risks', []):
            link = risk.get('scenario') or {}
            sid = link.get('scenario_id')
            from_machine = unit.get('source') == 'MACHINE'
            card = dict(card_id=risk['card_id'], title=risk['title'][:200], risk_type=risk.get('risk_type'),
                        input_text=(unit.get('text') or '')[:500], source=unit.get('source_label'),
                        machine_code=machine_identity(unit) if from_machine else None,
                        from_machine=from_machine, low_confidence=bool(risk.get('low_confidence')))
            if link.get('status') not in USABLE or sid not in byid or risk.get('low_confidence'):
                unmatched.append(dict(card, reason=link.get('message') or '시나리오 연결 없음',
                                      scenario_status=link.get('status')))
                continue
            if sid in seen:
                seen[sid]['risk_law']['other_cards'].append(card)
                continue
            s = byid[sid]
            reference = dict(policy_version=s['policy_version'],card=card, scenario_link=dict(status=link['status'], message=link.get('message')),
                             law=_law(risk), current=control_options(s, 'current', risk.get('current_options', [])),
                             plans=control_options(s, 'plans', risk.get('improvement_options', [])), other_cards=[],
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


REGISTERED_NOTICE = '사업장 등록 기기 기준 AI 검색 결과 · 현재 조치를 확인해 주세요.'
UNREGISTERED_NOTICE = '이번 평가에만 추가한 기기(사진 탐지·직접 추가) 기준 AI 검색 결과 · 실제로 하는 작업인지 확인한 뒤 평가표에 추가해 주세요.'


def _key(name):
    return ' '.join(str(name or '').split()).lower()


def split_pending(items, registered=None):
    """(평가표 행, 확인 대기).
    UX-024(2026-11-23 사용자 결정): 평가표 범위는 사업장에서 정기적으로 하는 전체 작업과 쓰는 기기다.
      사업장에 등록된 기기에서 나온 위험은 첫 초안부터 일반 평가 행이다(출처 표시 '등록 기기'는 유지, 당일 사용 확인 단계 없음).
      이번 평가에만 추가한 미등록 기기(사진 탐지·직접 추가)에서만 나온 위험은 지금처럼 '확인 대기'에 두고,
      담당자가 실제 작업으로 확인해 추가하면 그때 행이 된다.
    registered: 사업장 등록 기기 이름 목록. None 이면 예전처럼 기기 기준 위험을 모두 확인 대기로 둔다(호환).
    같은 위험이 작업 설명과 기기 양쪽에서 나오면 rows() 가 한 행으로 합치고 앞선(작업 설명) 출처를 대표로 둔다."""
    matches = registered_matcher(registered)
    rows_, pending = [], []
    for it in items:
        card = it['risk_law']['card']
        if not card.get('from_machine'):
            rows_.append(it)
        elif registered is not None and matches(card.get('machine_code'), card.get('input_text')):
            card['machine_kind'] = 'registered'
            it['risk_law']['notice'] = REGISTERED_NOTICE
            it['reason'] = ('사업장 등록 기기(' + (card.get('input_text') or '')[:50]
                            + ') 기준 AI 추천 위험요인 · 현재 조치를 확인해 주세요.')
            rows_.append(it)
        else:
            if registered is not None:
                card['machine_kind'] = 'unregistered'
            pending.append(it)
    return rows_, pending


def pending_view(it):
    """화면 표시용 요약. 저장된 확인 대기 항목 전체(기준 조치·추천)는 서버에만 둔다."""
    card = it['risk_law']['card']
    # UX-024: 새 평가표의 확인 대기는 미등록 기기(unregistered)뿐. 예전 평가표에 저장된 대기 항목은 machine_kind 가 없어 registered 로 표시
    kind = card.get('machine_kind') or 'registered'
    return dict(scenario_id=it['catalog']['id'], job=it['job'], title=it['title'], type=it['type'],
                machine=card.get('input_text', ''), card_title=card.get('title', ''), machine_kind=kind,
                notice=(UNREGISTERED_NOTICE if kind == 'unregistered' else
                        '등록 기기 기준 AI 검색 결과 · 실제로 하는 작업인지 확인한 뒤 평가표에 추가해 주세요.'))
