"""DB 기준 데이터 연결 계층. 등급 계산은 domain.risk_policy의 공통 함수를 사용한다.

정책(docs/implementation/risk-development-agreement.md): 신규 평가표는 ACTIVE_POLICY(FOOD-3LEVEL-1.2) 카탈로그로 만든다.
저장된 평가표는 행에 보관한 시나리오의 policy_version으로 계속 계산한다(기존 CATALOG-MVP-1.1 이력 보존).
"""
import json
import os
from pathlib import Path
from sqlalchemy import text
from domain.risk_policy import evaluate, POLICY, ACTIVE_POLICY, SUPPORTED
from services.auth import AuthError
from services import risk_law

SOURCE = 'catalog_v1'
AI_SOURCE = 'catalog_ai_v1'
RLS_SOURCE = risk_law.SOURCE  # 위험요인·법령 검색 모듈 연결(services/risk_law.py)
SOURCES = (SOURCE, AI_SOURCE, RLS_SOURCE)
CATALOG_DIR = Path(__file__).resolve().parents[2] / 'contracts/catalog_risk'
# 버전별 카탈로그. 1.1은 기존 평가표 조회·input_based v1 계약용으로 함께 적재한다.
SEEDS = {POLICY: CATALOG_DIR / 'catalog.json', ACTIVE_POLICY: CATALOG_DIR / 'catalog-food-3level-1.2.json'}
SEED = SEEDS[ACTIVE_POLICY]


def enabled():
    return os.getenv('SAFET_ASSESSMENT_MODE', 'unavailable') in SOURCES


def seed(db):
    """버전별 카탈로그를 적재한다. 이미 적재된 1.1은 그대로 두고 1.2를 추가한다. 반환: 신규 정책 시나리오 수."""
    counts = {}
    for version, path in SEEDS.items():
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['policy_version'] != version:
            raise ValueError(f'카탈로그 정책 버전 불일치: {path.name}')
        for scenario in data['scenarios']:
            if scenario['policy_version'] != version:
                raise ValueError('시나리오 정책 버전 불일치: ' + scenario['id'])
            payload = json.dumps(scenario, ensure_ascii=False, sort_keys=True)
            old = db.execute(text('SELECT payload FROM risk_catalog WHERE scenario_id=:id AND version=:v'),
                             {'id': scenario['id'], 'v': version}).scalar()
            if old is not None and json.loads(old) != scenario:
                raise ValueError('Catalog changed without version bump: '+scenario['id'])
            if old is None:
                db.execute(text('INSERT INTO risk_catalog(scenario_id,version,payload) VALUES(:id,:v,:p)'),
                           {'id': scenario['id'], 'v': version, 'p': payload})
        counts[version] = len(data['scenarios'])
    return counts[ACTIVE_POLICY]


def list_catalog(db, version=ACTIVE_POLICY):
    """기본은 신규 평가표 정책. 기존 평가표에 행을 더할 때는 그 평가표의 정책 버전을 넘긴다."""
    if version not in SUPPORTED:
        raise AuthError(409, 'POLICY_UNSUPPORTED', '지원하지 않는 위험도 정책 버전입니다.')
    return [json.loads(p) for p in db.execute(text('SELECT payload FROM risk_catalog WHERE version=:v ORDER BY scenario_id'), {'v': version}).scalars()]


def document_policy(items):
    """저장된 평가표의 정책 버전(행의 시나리오 기준). 행이 없으면 신규 정책."""
    versions = {it['catalog']['scenario']['policy_version'] for it in items if it.get('catalog')}
    if len(versions) > 1:
        raise AuthError(409, 'POLICY_MIXED', '한 평가표에 서로 다른 위험도 정책이 섞여 있습니다. 담당자 확인이 필요합니다.')
    return versions.pop() if versions else ACTIVE_POLICY


def generate(db, context, keyword=None, source=None):
    return generate_snapshot(list_catalog(db), context, keyword, source)


def generate_snapshot(catalog, context, keyword=None, source=None):
    """DB 세션 없이 미리 읽은 기준으로 분석한다."""
    source = source or os.getenv('SAFET_ASSESSMENT_MODE', SOURCE)
    if source == AI_SOURCE:
        from services import catalog_ai
        data=dict(context)
        if keyword:data['text']=keyword
        analyses=catalog_ai.analyze(data,catalog)
        byid={s['id']:s for s in catalog}
        return AI_SOURCE, [make_item(byid[a['scenario_id']],a) for a in analyses]
    if source == RLS_SOURCE and not context.get('catalog_ids'):
        text_in = keyword if keyword else context.get('text', '')
        voice_in = '' if keyword else context.get('voice_text', '')
        machines = [] if keyword else context.get('machines', [])  # 사업장 등록 기기도 검색어로 쓴다
        if not (text_in.strip() or voice_in.strip() or machines):
            raise AuthError(422, 'RISK_LAW_TEXT_REQUIRED', '작업 설명·음성 전사문을 입력하거나 사업장 기기를 등록해 주세요.')
        result = risk_law.analyze(text_in, voice_in, machines)
        items, unmatched = risk_law.rows(result, catalog, context.get('registered_machines'))
        if not items:
            raise AuthError(422, 'CATALOG_SELECTION_REQUIRED', '연결할 수 있는 위험요인을 찾지 못했어요. 작업과 상황을 조금 더 적어 주세요.')
        warnings = [str(w)[:300] for w in (result.get('warnings') or [])][:5]  # 예: 법령 인덱스 재생성 안내
        for it in items:
            it['risk_law']['unmatched'] = unmatched[:20]
            it['risk_law']['warnings'] = warnings
        return RLS_SOURCE, items
    ids = context.get('catalog_ids', [])
    if len(ids) != len(set(ids)) or set(ids) - {s['id'] for s in catalog}:
        raise AuthError(422, 'INVALID_CATALOG', 'DB 위험요인 선택을 다시 확인해 주세요.')
    query = (keyword or ' '.join([context.get('text', ''), context.get('voice_text', ''),
             ' '.join(m['machine_nm'] for m in context.get('machines', []))])).lower()
    selected = [s for s in catalog if s['id'] in ids] if ids else [s for s in catalog if any(t.lower() in query for t in s['keywords'])]
    if not selected:
        raise AuthError(422, 'CATALOG_SELECTION_REQUIRED', '일치하는 위험요인이 없어요. 작업·기기 설명을 추가해 주세요. 사진 분석은 아직 연결되지 않았습니다.')
    return SOURCE, [make_item(s) for s in selected]


def make_item(s, analysis=None):
    return dict(job=s['task'][:100], title=s['title'][:200], type=s['event'][:50],
                cause=s['scenario'][:500], signal='N', reason='위험 후보 · 작업 해당 여부와 현재 조치를 확인해 주세요.',
                curr=[c['current_text'] for c in s['controls']], plans=[c['plan_text'] for c in s['controls']],
                catalog=s, ai_analysis=analysis)


def initialize(db, item_id, scenario, analysis=None, reference=None):
    actions = db.execute(text('SELECT action_no,action_type FROM eval_action WHERE eval_dtl_no=:n ORDER BY sort,action_no'), {'n': item_id}).mappings().all()
    links, controls = {}, {}
    if reference is not None:
        # 추천 대책은 시나리오 기준 조치와 순서가 다르다. 연결표에서 정한 ID만 쓴다.
        known = {c['id'] for c in scenario['controls']}
        by_pos = risk_law.links(reference)
        for kind, key in (('C', 'current'), ('P', 'plans')):
            group = [a for a in actions if a['action_type'] == kind]
            for pos, action in enumerate(group):
                cid = by_pos.get((kind, pos))
                if cid in known: links[str(action['action_no'])] = cid
                if pos < len(reference[key]):
                    view = dict(reference[key][pos].get('control') or {})
                    if cid not in known: view['control_id'] = None
                    controls[str(action['action_no'])] = view
    else:
        for kind in ('C', 'P'):
            group = [a for a in actions if a['action_type'] == kind]
            for action, control in zip(group, scenario['controls']): links[str(action['action_no'])] = control['id']
    state = {'scenario': scenario, 'links': links, 'current_result': evaluate(scenario, []), 'projected_result': None}
    if analysis:state['ai_analysis']=analysis
    if reference is not None:
        state['risk_law'] = reference
        state['action_controls'] = controls  # 화면 표시용: 추천 대책별 위험도 반영 여부와 이유
        current, projected = rls_results(scenario, set(), set(), reviewed=False)
        state.update(current_result=current, projected_result=projected)
        db.execute(text('UPDATE eval_dtl SET curr_risk_grade=:g,risk_reason=:r,after_risk_grade=:a,after_judge_yn=:j WHERE eval_dtl_no=:n'),
                   {'n': item_id, 'g': current['signal'], 'r': current['reason'], 'a': projected['signal'], 'j': 'Y'})
    store(db, item_id, state)


def rls_results(scenario, current, planned, reviewed):
    """일반 평가표(검색 모듈 연결 행)의 현재·예상 위험도. 생성 시(체크 0개)와 저장할 때마다 계산한다.

    현재 = 체크한 현재 안전조치의 기준 조치 ID. 예상 = 현재 ∪ 개선대책 ID(같은 조치는 한 번만).
    기준 조치 ID가 없는 추천·직접 입력은 저장하되 계산에서 제외한다. 체크하지 않은 조치는 계산에서만 미충족이다.
    목록 전체 확인 체크는 이 유형의 계산·확정 조건이 아니다(확정은 현재 조치 선택 또는 '현재 조치 없음'과 확인 대기 처리).
    """
    result = evaluate(scenario, current, answered=True)
    result['reason'] = '체크한 현재 안전조치(없으면 0개) 기준 계산입니다. ' + result['reason']
    projected = evaluate(scenario, current | planned, answered=True)
    projected.update(kind='projected', assumption='선택한 기준 대책이 모두 이행되어 유효하게 작동한다고 가정')
    projected['reason'] = '계획 이행·효과를 가정한 예상이며 실제 조치 결과가 아닙니다. 기준에 연결되지 않은 대책은 하향 계산에서 제외합니다. ' + projected['reason']
    return result, projected


def store(db, item_id, state):
    db.execute(text('UPDATE eval_dtl SET catalog_state=:s WHERE eval_dtl_no=:n'), {'n': item_id, 's': json.dumps(state, ensure_ascii=False)})


def control_view(scenario, cid):
    c = next((c for c in scenario['controls'] if c['id'] == cid), None)
    if c is None:
        return dict(control_id=None, status='unmapped', message='기준 조치에 연결되지 않은 대책 · 위험도 계산 제외')
    return dict(control_id=cid, status='catalog', critical=c['critical'],
                message=('핵심' if c['critical'] else '보완') + ' 기준 조치 · 위험도 계산 반영')


def enrich(item, raw):
    if not raw: return
    state = json.loads(raw)
    item['catalog'] = state
    item['controls_reviewed'] = state.get('controls_reviewed', False)
    if 'scenario' not in state:  # input_based 행 등 다른 저장 형식은 authoring_rag.enrich가 처리한다
        return
    item['policy_version'] = state['scenario'].get('policy_version')
    shown = state.get('action_controls', {})
    for a in item.get('curr', []) + item.get('plans', []):
        cid = state.get('links', {}).get(str(a['id']))
        if cid:
            a['control'] = dict(shown.get(str(a['id'])) or {}, **control_view(state['scenario'], cid))
        else:
            a['control'] = (dict(shown[str(a['id'])], control_id=None) if str(a['id']) in shown
                            else dict(control_id=None, status='manual',
                                      message='직접 입력 · 기준 조치 ID 없음 · 위험도 계산 제외'))


def recalculate(db, item, edit, email, revision, no):
    state = item.get('catalog')
    if not state: return
    # 저장된 정책으로 계속 계산한다(1.1 평가표는 1.1, 신규는 1.2). 1.2 전환은 새 평가표로 한다.
    if state['scenario']['policy_version'] not in SUPPORTED:
        raise AuthError(409, 'POLICY_CHANGED', '지원하지 않는 이전 기준 평가표입니다. 새 평가표를 작성해 주세요.')
    known = {c['id'] for c in state['scenario']['controls']}

    def selected(actions):
        # 이 행에 저장한 action_id → control_id 연결만 쓴다(다른 행·시나리오 ID는 반영하지 않음).
        return {state['links'][str(a.id)] for a in actions
                if a.checked and a.id is not None and state['links'].get(str(a.id)) in known}
    current = selected(edit.curr)
    if state.get('risk_law') is not None:
        reviewed = edit.controls_reviewed and (edit.none or any(a.checked for a in edit.curr))
        result, projected = rls_results(state['scenario'], current, selected(edit.plans), reviewed)
        state.update(controls_reviewed=edit.controls_reviewed, current_result=result, projected_result=projected)
        store(db, item['id'], state)
        db.execute(text('UPDATE eval_dtl SET curr_risk_grade=:g,risk_reason=:r,after_risk_grade=:a,after_judge_yn=:j WHERE eval_dtl_no=:n'),
                   {'n': item['id'], 'g': result['signal'], 'r': result['reason'], 'a': projected['signal'], 'j': 'Y'})
        event(db, no, item['id'], revision, 'calculation', email, {'current': result, 'projected': projected})
        return
    answered = edit.controls_reviewed and (edit.none or any(a.checked for a in edit.curr)) and not state.get('ai_analysis',{}).get('questions')
    result = evaluate(state['scenario'], current, answered=answered)
    if state.get('ai_analysis',{}).get('questions'):
        result['reason']='AI 추가 질문에 답한 뒤 현재 조치 목록을 확인해 주세요.'
    planned = selected(edit.plans)
    projected = None
    if answered and (any(a.checked for a in edit.plans) or edit.keep == 'Y'):
        projected = evaluate(state['scenario'], current | planned, answered=True)
        projected.update(kind='projected', assumption='선택한 기준 대책이 모두 이행되어 유효하게 작동한다고 가정')
        projected['reason'] = '계획 이행·효과를 가정한 예상이며 실제 조치 결과가 아닙니다. 기준에 연결되지 않은 직접 추가 대책은 하향 계산에서 제외합니다. ' + projected['reason']
    state.update(controls_reviewed=edit.controls_reviewed, current_result=result, projected_result=projected)
    store(db, item['id'], state)
    db.execute(text('UPDATE eval_dtl SET curr_risk_grade=:g,risk_reason=:r,after_risk_grade=:a,after_judge_yn=:j WHERE eval_dtl_no=:n'),
               {'n': item['id'], 'g': result['signal'], 'r': result['reason'],
                'a': projected['signal'] if projected else 'N', 'j': 'Y' if projected else 'N'})
    event(db, no, item['id'], revision, 'calculation', email, {'current': result, 'projected': projected})


def event(db, no, item_id, revision, kind, email, payload):
    db.execute(text('INSERT INTO risk_event(eval_no,item_id,revision,kind,actor,payload) VALUES(:n,:i,:r,:k,:e,:p)'),
               {'n': no, 'i': item_id, 'r': revision, 'k': kind, 'e': email, 'p': json.dumps(payload, ensure_ascii=False)})
