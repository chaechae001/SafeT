"""DB 기준 데이터 연결 계층. 등급 계산은 domain.risk_policy의 공통 함수를 사용한다."""
import json
import os
from pathlib import Path
from sqlalchemy import text
from domain.risk_policy import evaluate, POLICY
from services.auth import AuthError
from services import risk_law

SOURCE = 'catalog_v1'
AI_SOURCE = 'catalog_ai_v1'
RLS_SOURCE = risk_law.SOURCE  # 위험요인·법령 검색 모듈 연결(services/risk_law.py)
SOURCES = (SOURCE, AI_SOURCE, RLS_SOURCE)
SEED = Path(__file__).resolve().parents[2] / 'contracts/catalog_risk/catalog.json'


def enabled():
    return os.getenv('SAFET_ASSESSMENT_MODE', 'unavailable') in SOURCES


def seed(db):
    data = json.loads(SEED.read_text(encoding='utf-8'))
    for scenario in data['scenarios']:
        payload = json.dumps(scenario, ensure_ascii=False, sort_keys=True)
        old = db.execute(text('SELECT payload FROM risk_catalog WHERE scenario_id=:id AND version=:v'),
                         {'id': scenario['id'], 'v': POLICY}).scalar()
        if old is not None and json.loads(old) != scenario:
            raise ValueError('Catalog changed without version bump: '+scenario['id'])
        if old is None:
            db.execute(text('INSERT INTO risk_catalog(scenario_id,version,payload) VALUES(:id,:v,:p)'),
                       {'id': scenario['id'], 'v': POLICY, 'p': payload})
    return len(data['scenarios'])


def list_catalog(db):
    return [json.loads(p) for p in db.execute(text('SELECT payload FROM risk_catalog WHERE version=:v ORDER BY scenario_id'), {'v': POLICY}).scalars()]


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
        items, unmatched = risk_law.rows(risk_law.analyze(text_in, voice_in, machines), catalog)
        if not items:
            raise AuthError(422, 'CATALOG_SELECTION_REQUIRED', '연결할 수 있는 위험요인을 찾지 못했어요. 작업과 상황을 조금 더 적어 주세요.')
        for it in items:
            it['risk_law']['unmatched'] = unmatched[:20]
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
        current, projected = rls_results(scenario, set(), set())
        state.update(current_result=current, projected_result=projected)
        db.execute(text('UPDATE eval_dtl SET curr_risk_grade=:g,risk_reason=:r,after_risk_grade=:a,after_judge_yn=:j WHERE eval_dtl_no=:n'),
                   {'n': item_id, 'g': current['signal'], 'r': current['reason'], 'a': projected['signal'], 'j': 'Y'})
    store(db, item_id, state)


def rls_results(scenario, current, planned):
    """검색 모듈 연결 행: 처음(선택 0개)부터 현재·예상 위험도를 계산하고 저장할 때마다 다시 계산한다.

    체크하지 않은 추천은 '확인된 조치 아님'으로 계산에서만 미충족 처리한다(미실시로 기록하지 않는다).
    기준 조치에 연결되지 않은 추천·직접 추가 대책은 저장하되 하향 계산에 쓰지 않는다.
    """
    result = evaluate(scenario, current, answered=True)
    result['reason'] = '체크한 현재 조치 중 기준 조치에 연결된 것만 반영했습니다. ' + result['reason']
    projected = evaluate(scenario, current | planned, answered=True)
    projected.update(kind='projected', assumption='선택한 기준 대책이 모두 이행되어 유효하게 작동한다고 가정')
    projected['reason'] = '계획 이행·효과를 가정한 예상이며 실제 조치 결과가 아닙니다. 기준에 연결되지 않은 대책은 하향 계산에서 제외합니다. ' + projected['reason']
    return result, projected


def store(db, item_id, state):
    db.execute(text('UPDATE eval_dtl SET catalog_state=:s WHERE eval_dtl_no=:n'), {'n': item_id, 's': json.dumps(state, ensure_ascii=False)})


def enrich(item, raw):
    if not raw: return
    state = json.loads(raw)
    item['catalog'] = state
    item['controls_reviewed'] = state.get('controls_reviewed', False)
    if 'risk_law' in state:
        shown = state.get('action_controls', {})
        for a in item.get('curr', []) + item.get('plans', []):
            a['control'] = shown.get(str(a['id'])) or dict(control_id=None, message='기준 조치에 연결되지 않은 대책')


def recalculate(db, item, edit, email, revision, no):
    state = item.get('catalog')
    if not state: return
    if state['scenario']['policy_version'] != POLICY:
        raise AuthError(409, 'POLICY_CHANGED', '이전 기준 평가표입니다. 새 평가표를 작성해 주세요.')
    def selected(actions):
        return {state['links'][str(a.id)] for a in actions if a.checked and str(a.id) in state['links']}
    current = selected(edit.curr)
    if state.get('risk_law') is not None:
        result, projected = rls_results(state['scenario'], current, selected(edit.plans))
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
