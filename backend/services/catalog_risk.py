"""DB 기준 데이터 연결 계층. 등급 계산은 domain.risk_policy의 공통 함수를 사용한다."""
import json
import os
from pathlib import Path
from sqlalchemy import text
from domain.risk_policy import evaluate, POLICY
from services.auth import AuthError
from schemas.risk_analysis import CONTRACT_VERSION

SOURCE = 'catalog_v1'
SEED = Path(__file__).resolve().parents[2] / 'contracts/catalog_risk/catalog.json'


def enabled():
    return os.getenv('SAFET_ASSESSMENT_MODE', 'unavailable') == SOURCE


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


def generate(db, context, keyword=None):
    catalog = list_catalog(db)
    ids = context.get('catalog_ids', [])
    if len(ids) != len(set(ids)) or set(ids) - {s['id'] for s in catalog}:
        raise AuthError(422, 'INVALID_CATALOG', 'DB 위험요인 선택을 다시 확인해 주세요.')
    query = (keyword or ' '.join([context.get('text', ''), context.get('voice_text', ''),
             ' '.join(m['machine_nm'] for m in context.get('machines', []))])).lower()
    selected = [s for s in catalog if s['id'] in ids] if ids else [s for s in catalog if any(t.lower() in query for t in s['keywords'])]
    if not selected:
        raise AuthError(422, 'CATALOG_SELECTION_REQUIRED', '일치하는 위험요인이 없어요. 작업·기기 설명을 추가해 주세요. 사진 분석은 아직 연결되지 않았습니다.')
    return SOURCE, [dict(job=s['task'][:100], title=s['title'][:200], type=s['event'][:50],
                        cause=s['scenario'][:500], signal='N', reason='DB 후보 · 적용 상황과 현재 조치를 확인해 주세요.',
                        curr=[c['current_text'] for c in s['controls']], plans=[c['plan_text'] for c in s['controls']],
                        catalog=s) for s in selected]


def initialize(db, item_id, scenario):
    actions = db.execute(text('SELECT action_no,action_type FROM eval_action WHERE eval_dtl_no=:n ORDER BY sort,action_no'), {'n': item_id}).mappings().all()
    links = {}
    for kind in ('C', 'P'):
        group = [a for a in actions if a['action_type'] == kind]
        for action, control in zip(group, scenario['controls']): links[str(action['action_no'])] = control['id']
    state = {'scenario': scenario, 'links': links, 'current_result': evaluate(scenario, []), 'projected_result': None}
    store(db, item_id, state)


def store(db, item_id, state):
    db.execute(text('UPDATE eval_dtl SET catalog_state=:s WHERE eval_dtl_no=:n'), {'n': item_id, 's': json.dumps(state, ensure_ascii=False)})


def enrich(item, raw):
    if not raw: return
    state = json.loads(raw)
    item['catalog'] = state


def recalculate(db, item, edit, email, revision, no):
    state = item.get('catalog')
    if not state: return
    if state['scenario']['policy_version'] != POLICY:
        raise AuthError(409, 'POLICY_CHANGED', '이전 기준 평가표입니다. 새 평가표를 작성해 주세요.')
    def selected(actions):
        return {state['links'][str(a.id)] for a in actions if a.checked and str(a.id) in state['links']}
    current = selected(edit.curr)
    answered = edit.none or any(a.checked for a in edit.curr)
    ai = state.get('ai')
    if ai:
        # 과거 선택·변경 없는 저장은 새 미확인·상충 정보를 해소하는 답변이 아니다.
        previous = {state['links'][str(a['id'])] for a in item['curr'] if a['checked'] and str(a['id']) in state['links']}
        changed = current ^ previous
        explicit_none = edit.none and not item['none']
        for field in ('unknown_ids','conflict_ids'):
            ai[field] = [] if explicit_none else [cid for cid in ai.get(field, []) if cid not in changed]
        answered = answered and ai.get('contract_version')==CONTRACT_VERSION and ai['match']['applicability']=='confirmed' and not ai['unknown_ids'] and not ai['conflict_ids'] and not ai['match']['uncertainties']
    result = evaluate(state['scenario'], current, answered=answered)
    if ai and not answered:
        result['reason']='현재 조치와 입력 근거의 미확인·상충 정보를 확인해 주세요. 필요한 질문은 추가 확인에 표시됩니다.'
    planned = selected(edit.plans)
    projected = None
    if answered and (planned or edit.keep == 'Y'):
        projected = evaluate(state['scenario'], current | planned, answered=True)
        projected['reason'] = '선택한 개선대책을 이행한다고 가정한 예상 결과입니다. ' + projected['reason']
    state.update(current_result=result, projected_result=projected)
    store(db, item['id'], state)
    db.execute(text('UPDATE eval_dtl SET curr_risk_grade=:g,risk_reason=:r,after_risk_grade=:a,after_judge_yn=:j WHERE eval_dtl_no=:n'),
               {'n': item['id'], 'g': result['signal'], 'r': result['reason'],
                'a': projected['signal'] if projected else 'N', 'j': 'Y' if projected else 'N'})
    event(db, no, item['id'], revision, 'calculation', email, {'current': result, 'projected': projected})


def event(db, no, item_id, revision, kind, email, payload):
    db.execute(text('INSERT INTO risk_event(eval_no,item_id,revision,kind,actor,payload) VALUES(:n,:i,:r,:k,:e,:p)'),
               {'n': no, 'i': item_id, 'r': revision, 'k': kind, 'e': email, 'p': json.dumps(payload, ensure_ascii=False)})
