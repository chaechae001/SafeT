"""Transparent experimental rules. No model, DB writes, or automatic final approval."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

POLICY_PATH = Path(__file__).with_name('criteria.json')
VERSION = 'CHK-3L-EXP-0.1'
LABELS = {'R': '상', 'Y': '중', 'G': '하', 'N': '판단 필요'}
STATE_KEYS = {'facts', 'complete', 'severe_residual', 'treatment_residual',
              'unresolved_near_miss', 'legal_status', 'controls'}
LEGAL = {'compliant', 'noncompliant', 'unknown', 'not_applicable'}
CONTROLS = {'effective', 'partial', 'ineffective', 'unknown', 'not_needed'}
FLAGS = {'SEVERE', 'LEGAL', 'TREATMENT', 'NEAR_MISS', 'CONTROLS'}


def texts(value, field, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise ValueError(f'{field}: 문자열 배열이 필요합니다.')
    if any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f'{field}: 빈 문자열은 허용하지 않습니다.')


def state_checked(state):
    if not isinstance(state, dict) or set(state) != STATE_KEYS:
        raise ValueError('state 필드가 누락되었거나 정의되지 않은 필드가 있습니다.')
    texts(state['facts'], 'facts', allow_empty=True)
    if type(state['complete']) is not bool:
        raise ValueError('complete는 JSON boolean이어야 합니다.')
    for key in ('severe_residual', 'treatment_residual', 'unresolved_near_miss'):
        if state[key] is not None and type(state[key]) is not bool:
            raise ValueError(f'{key}는 true/false/null이어야 합니다.')
    if not isinstance(state['legal_status'], str) or state['legal_status'] not in LEGAL:
        raise ValueError('legal_status 값이 잘못되었습니다.')
    if not isinstance(state['controls'], str) or state['controls'] not in CONTROLS:
        raise ValueError('controls 값이 잘못되었습니다.')
    return deepcopy(state)


def flags(state):
    result = []
    for key, flag in (('severe_residual', 'SEVERE'), ('treatment_residual', 'TREATMENT'),
                      ('unresolved_near_miss', 'NEAR_MISS')):
        if state[key] is True:
            result.append(flag)
    if state['legal_status'] == 'noncompliant': result.append('LEGAL')
    if state['controls'] in ('partial', 'ineffective'): result.append('CONTROLS')
    return result


def classify(raw):
    state = state_checked(raw)
    active = flags(state)
    missing = []
    if not state['facts']: missing.append('판단을 뒷받침하는 사실/근거')
    if not state['complete']: missing.append('핵심 정보 확인 완료')
    for key in ('severe_residual', 'treatment_residual', 'unresolved_near_miss'):
        if state[key] is None: missing.append(key)
    if state['legal_status'] == 'unknown': missing.append('적용 법정조치 확인')
    if state['controls'] == 'unknown': missing.append('현재/가정된 조치 효과 확인')
    # R is a conservative warning; missing information cannot erase known severe flags.
    if 'LEGAL' in active:
        code, rule = 'R', 'R_LEGAL'
    elif 'SEVERE' in active:
        code, rule = 'R', 'R_SEVERE'
    elif missing:
        code, rule = 'N', 'N_INFORMATION'
    elif active:
        code, rule = 'Y', 'Y_RESIDUAL'
    else:
        code, rule = 'G', 'G_CONTROLLED'
    return {'grade': code, 'label': LABELS[code], 'rule_id': rule,
            'risk_flags': active, 'missing_information': missing,
            'requires_human_review': True}


def pending(reason):
    return {'grade': 'N', 'label': LABELS['N'], 'rule_id': 'N_PROJECTION',
            'risk_flags': [], 'missing_information': [reason], 'requires_human_review': True}


def evaluate_case(case):
    if not isinstance(case, dict) or not {'case_id', 'task', 'current'} <= set(case):
        raise ValueError('case_id, task, current가 필요합니다.')
    if set(case) - {'case_id', 'task', 'current', 'projection', 'expected', 'note'}:
        raise ValueError('정의되지 않은 사례 필드입니다.')
    if any(not isinstance(case[k], str) or not case[k].strip() for k in ('case_id', 'task')):
        raise ValueError('case_id/task는 비어 있지 않은 문자열이어야 합니다.')
    current = classify(case['current'])
    projected = pending('개선계획과 효과 가정이 아직 없습니다.')
    projection = case.get('projection')
    if projection is not None:
        keys = {'state', 'measures', 'assumptions', 'effect_reason', 'verification_steps',
                'addressed_flags', 'effect_reviewed'}
        if not isinstance(projection, dict) or set(projection) != keys:
            raise ValueError('projection 필드가 누락되었거나 정의되지 않은 필드가 있습니다.')
        for key in ('measures', 'assumptions', 'verification_steps'):
            texts(projection[key], key, allow_empty=True)
        texts(projection['addressed_flags'], 'addressed_flags', allow_empty=True)
        if set(projection['addressed_flags']) - FLAGS:
            raise ValueError('addressed_flags 값이 잘못되었습니다.')
        if type(projection['effect_reviewed']) is not bool or not isinstance(projection['effect_reason'], str):
            raise ValueError('effect_reviewed/effect_reason 형식을 확인하세요.')
        candidate = classify(projection['state'])
        if not all(projection[k] for k in ('measures', 'assumptions', 'verification_steps')) or not projection['effect_reason'].strip():
            projected = pending('대책·작동 가정·효과 이유·실행 후 확인 항목을 작성하세요.')
        elif not projection['effect_reviewed']:
            projected = pending('효과 가정을 검토하지 않았습니다.')
        elif current['grade'] == 'N' and candidate['grade'] != 'R':
            projected = pending('현재의 핵심 정보를 먼저 확인하세요. 예상값으로 현재 미판정을 덮지 않습니다.')
        else:
            removed = set(current['risk_flags']) - set(candidate['risk_flags'])
            unexplained = removed - set(projection['addressed_flags'])
            if unexplained:
                projected = pending('해소를 가정한 위험의 대책 연결이 없습니다: ' + ', '.join(sorted(unexplained)))
            else:
                projected = candidate
    current['basis'] = 'reported_current_conditions'
    projected['basis'] = 'conditional_unimplemented_plan'
    projected['is_actual_result'] = False
    projected['assumptions'] = deepcopy(projection['assumptions']) if projection else []
    projected['effect_reason'] = projection['effect_reason'] if projection else ''
    projected['verification_steps'] = deepcopy(projection['verification_steps']) if projection else []
    policy = json.loads(POLICY_PATH.read_text(encoding='utf-8'))
    if policy.get('version') != VERSION:
        raise ValueError('기준 JSON 버전과 규칙 코드 버전이 다릅니다. 함께 변경하세요.')
    serialized = json.dumps(case, ensure_ascii=False, sort_keys=True).encode()
    return {'case_id': case['case_id'], 'task': case['task'], 'criteria_version': VERSION,
            'input_sha256': hashlib.sha256(serialized).hexdigest(),
            'criteria_sha256': hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest(),
            'engine_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'current': current, 'projected': projected,
            'status': 'experimental_candidate_not_final', 'acceptable_after_execution': None}
