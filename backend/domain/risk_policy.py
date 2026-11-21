"""피해 수준과 조치 선택으로 현재·예상 위험도를 계산한다.

정책 기준: docs/implementation/risk-development-agreement.md
- 신규 평가표: FOOD-3LEVEL-1.2 (ACTIVE_POLICY). 카탈로그 contracts/catalog_risk/catalog-food-3level-1.2.json
- 기존 평가표: 저장 당시 시나리오의 policy_version으로 계속 계산한다(CATALOG-MVP-1.1 이력 보존).
- input_based v1 계약(contracts/assessment_authoring/v1)은 MATRIX(1.1)를 직접 참조한다. MATRIX는 바꾸지 않는다.
"""
POLICY = 'CATALOG-MVP-1.1'  # 기존 공통 정책. 과거 평가표·input_based v1 계약용
MATRIX = {1: {1: '하', 2: '중', 3: '중'},
          2: {1: '중', 2: '중', 3: '상'},
          3: {1: '상', 2: '상', 3: '상'}}
RESTAURANT_POLICY = 'FOOD-3LEVEL-1.2'
# 열(조치 구간): 1 기준 조치 전체 충족, 2 핵심 전부 충족·보완 일부 미충족, 3 핵심 일부 또는 전부 미충족
RESTAURANT_MATRIX = {1: {1: '하', 2: '하', 3: '중'},
                     2: {1: '하', 2: '중', 3: '중'},
                     3: {1: '중', 2: '중', 3: '상'}}
ACTIVE_POLICY = RESTAURANT_POLICY  # 신규 평가표에 적용하는 정책
MATRICES = {POLICY: MATRIX, RESTAURANT_POLICY: RESTAURANT_MATRIX}
SUPPORTED = tuple(MATRICES)
SIGNAL = {'상': 'R', '중': 'Y', '하': 'G', None: 'N'}
SEVERITY_TEXT = {1: '경미·응급처치', 2: '휴업 부상·질병 가능', 3: '사망·중상 가능'}
BAND_TEXT = {1: '기준 조치 전체 충족', 2: '핵심 전부 충족·보완 일부 미충족', 3: '핵심 일부 또는 전부 미충족'}


def _explain(version, matrix, severity, band, grade, applied, missing_critical, missing_support):
    if version == POLICY:  # 기존 1.1 문구 유지(저장 이력과 같은 형식)
        return f'피해 S{severity} · 조치 C{band} → {grade}. 선택한 현재 조치를 기준으로 계산했습니다.'
    parts = [f'{version} · 피해 S{severity}({SEVERITY_TEXT[severity]}) · {BAND_TEXT[band]} → {grade}.',
             '반영한 기준 조치: ' + (', '.join(applied) if applied else '없음') + '.']
    if missing_critical:
        parts.append('남은 핵심 조치: ' + ', '.join(missing_critical) + '.')
    if missing_support:
        parts.append('남은 보완 조치: ' + ', '.join(missing_support) + '.')
    best = matrix[severity][1]
    if band == 1:
        if grade != '하':
            parts.append(f'기준 조치를 모두 충족해도 판정표상 피해 S{severity}의 최저 등급은 {grade}입니다.')
    else:
        nxt = matrix[severity][band - 1]
        if nxt == grade:
            parts.append(f'남은 {"핵심" if band == 3 else "보완"} 조치를 충족해도 판정표상 {grade}가 유지됩니다'
                         + (f'(전체 충족 시 {best}).' if best != grade else '.'))
        else:
            parts.append(f'남은 {"핵심" if band == 3 else "보완"} 조치를 충족하면 {nxt}입니다.')
    return ' '.join(parts)


def evaluate(scenario, selected_ids, *, answered=False):
    """미응답은 판단 필요. 선택 개수가 아닌 핵심 조치 충족 여부를 사용한다. 같은 조치는 한 번만 센다."""
    version = scenario['policy_version']
    matrix = MATRICES.get(version)
    if matrix is None:
        raise ValueError('지원하지 않는 정책 버전입니다.')
    severity = scenario['severity']
    if type(severity) is not int or severity not in matrix:
        raise ValueError('피해 수준이 올바르지 않습니다.')
    controls = scenario['controls']
    known = {c['id'] for c in controls}
    critical = {c['id'] for c in controls if c['critical']}
    selected = set(selected_ids)
    if len(known) != len(controls) or not critical or selected - known:
        raise ValueError('조치 기준이 올바르지 않습니다.')
    band = 3 if not critical <= selected else (1 if known <= selected else 2)
    grade = matrix[severity][band] if answered else None
    order = [c['id'] for c in controls]
    applied = [i for i in order if i in selected]
    missing_critical = [i for i in order if i in critical - selected]
    missing_support = [i for i in order if i in known - critical - selected]
    reason = (_explain(version, matrix, severity, band, grade, applied, missing_critical, missing_support)
              if answered else '현재 작업에 해당하는지와 현재 조치 목록 전체를 확인해 주세요.')
    return {'policy_version': version, 'grade': grade, 'signal': SIGNAL[grade],
            'status': 'calculated' if answered else 'needs_information',
            'severity': severity, 'control_band': band if answered else None, 'reason': reason,
            'applied_control_ids': applied, 'missing_critical_ids': missing_critical,
            'missing_supplementary_ids': missing_support}
