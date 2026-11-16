"""모델 연결 지점. PR #9 위험도 알고리즘을 사용하지 않음.

기본은 unavailable: 판단 필요를 반환. SAFET_ASSESSMENT_MODE=demo일 때만
합성 고정값으로 저장/확정 흐름을 시험한다. 실제 AI 추론으로 표시하지 않는다.
"""
import os


def generate(context, keyword=None):
    demo = os.getenv('SAFET_ASSESSMENT_MODE', 'unavailable') == 'demo'
    if not demo:
        return 'unavailable', [dict(job=keyword[:100] if keyword else '현장 확인', title=keyword or '현장 위험 확인 필요',
            type='미분류', cause='현장 입력에 대한 모델 분석 대기', signal='N',
            reason='위험 판단 모델이 연결되지 않았습니다. 입력은 보존되며 확정은 차단됩니다.', curr=[], plans=[])]
    samples = [
        ('튀김 조리','고온 기름 튐에 의한 화상','화상','R',['긴 집게 사용','재료 물기 제거','보호구 착용'],['비산 방지판 설치','투입 절차 개선','적합한 보호구 지급']),
        ('바닥 이동','젖은 바닥 미끄러짐','넘어짐','Y',['바닥 물기 제거','미끄럼 방지 신발 착용'],['누수 원인 제거','배수 개선','청소 주기 지정']),
        ('칼 보관','칼 보관 중 접촉','베임','G',['칼집·칼꽂이 사용'],['보관 위치 구분','보관함 교체','작업 동선 정리']),
    ]
    if keyword: samples = [(keyword[:100], keyword[:180] + ' 관련 위험 (시험용)', '시험용', 'Y', ['현재 조치 확인'], ['작업 방법 개선','설비 점검','보호구 확인'])]
    return 'demo', [dict(job=j,title=t,type=ty,signal=s,cause='합성 시나리오: 실제 현장 분석 아님',
        reason='개발 흐름 검사용 고정 신호. 실제 위험도 판단에 사용하지 않습니다.',curr=c,plans=p) for j,t,ty,s,c,p in samples]


def project(item, source):
    # 예상도 모델 미연결은 N. demo도 개선 효과를 추정하지 않고 현재 신호 유지.
    if source == 'demo' and (item['keep']=='Y' or any(a['checked'] for a in item['plans'])):
        return item['signal'], True
    return 'N', False
