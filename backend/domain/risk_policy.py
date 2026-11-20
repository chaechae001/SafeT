"""피해 수준과 조치 선택으로 현재·예상 위험도를 계산한다."""
POLICY = 'CATALOG-MVP-1.1'
MATRIX = {1: {1: '하', 2: '중', 3: '중'},
          2: {1: '중', 2: '중', 3: '상'},
          3: {1: '상', 2: '상', 3: '상'}}
RESTAURANT_POLICY = 'FOOD-3LEVEL-1.2'
# 열 순서: 전체 충족, 핵심만 모두 충족, 핵심 일부 미확인
RESTAURANT_MATRIX = {1: {1: '하', 2: '하', 3: '중'},
                     2: {1: '하', 2: '중', 3: '중'},
                     3: {1: '중', 2: '중', 3: '상'}}
SIGNAL = {'상': 'R', '중': 'Y', '하': 'G', None: 'N'}


def evaluate(scenario, selected_ids, *, answered=False):
    """미응답은 판단 필요. 선택 개수가 아닌 핵심 조치 충족 여부를 사용한다."""
    version = scenario['policy_version']
    matrix = {POLICY: MATRIX, RESTAURANT_POLICY: RESTAURANT_MATRIX}.get(version)
    if matrix is None:
        raise ValueError('지원하지 않는 정책 버전입니다.')
    severity = scenario['severity']
    if type(severity) is not int or severity not in MATRIX:
        raise ValueError('피해 수준이 올바르지 않습니다.')
    controls = scenario['controls']
    known = {c['id'] for c in controls}
    critical = {c['id'] for c in controls if c['critical']}
    selected = set(selected_ids)
    if len(known) != len(controls) or not critical or selected - known:
        raise ValueError('조치 기준이 올바르지 않습니다.')
    band = 3 if not critical <= selected else (1 if known <= selected else 2)
    grade = matrix[severity][band] if answered else None
    reason = (f'피해 S{severity} · 조치 C{band} → {grade}. 선택한 현재 조치를 기준으로 계산했습니다.'
              if answered else '현재 작업에 해당하는지와 현재 조치 목록 전체를 확인해 주세요.')
    return {'policy_version': version, 'grade': grade, 'signal': SIGNAL[grade],
            'status': 'calculated' if answered else 'needs_information',
            'severity': severity, 'control_band': band if answered else None, 'reason': reason}
