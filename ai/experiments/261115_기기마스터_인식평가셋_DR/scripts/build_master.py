"""업종별 기기 마스터 초안 생성 스크립트.

실행(작업 폴더 루트에서): python 261115_기기마스터_인식평가셋_DR/scripts/build_master.py
입력: 없음(근거 쪽수는 아래 표에 직접 기록. 근거 확인은 261115_RAG_지식베이스_DR 청크·구조화표로 수행)
출력: 261115_기기마스터_v1_DR.json, 261115_기기마스터_v1_DR.csv, 261115_기기마스터_업종별목록_v1_DR.csv
"""
import csv
import json
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
VERSION = 'v1-draft'
CREATED = '2026-11-16'

SOURCES = {
    'CHK': {'title': '음식점업 자율안전점검표', 'path': 'RAG용/음식점업 자율안전점검표.pdf',
            'page_basis': 'PDF 쪽', 'note': '음식점업 공통 점검표. 업종 구분 없음.',
            'rag_row_prefix': '261115_RAG_구조화표_v1_DR.jsonl row_id CHK-*'},
    'D8': {'title': '프랜차이즈 가맹본부의 산재예방 조치 이행 실태조사 및 개선방안 마련 최종보고서',
           'path': 'RAG용/최종보고서_프랜차이즈 가맹본부의 산재예방 조치 이행 실태조사 및 개선방안 마련.pdf',
           'page_basis': 'PDF 쪽(인쇄 쪽 = PDF 쪽 - 24)',
           'note': 'VI장 업종별 안전보건 현장 가이드(한식 p247-253, 중식 p253-257, 피자 p258-261, 치킨 p262-266, 커피 p267-270, 제과제빵 p271-275). p96-97은 국외 레스토랑 가이드 정리.',
           'rag_chunk_prefix': 'D8-pNNN'},
    'D5': {'title': '서비스업 재해사례 중심 위험성평가 방법 안내서(2023)',
           'path': 'RAG용/[2023-중소기업지원실-404]_[2023-중소기업지원실-404]서비스업+재해사례+중심+위험성평가+방법+안내서.pdf',
           'page_basis': 'PDF 쪽', 'note': '음식업 p58-73. 원문 글꼴 문제로 OCR 텍스트 사용. 오인식 가능, 원문 대조 필요.',
           'rag_chunk_prefix': 'D5-pNNN'},
    'CASE_A': {'title': '노인인력개발원 안전보건관리 에센스(실제 사업장 위험성평가 사례)',
               'path': '261113_restaurant_completed_assessments_DR/261113_노인인력개발원_안전보건관리에센스_원본_DR.pdf',
               'page_basis': 'PDF 쪽', 'note': '음식점·카페 사례. 261115_RAG_구조화표 row CASE-FOOD_A_*, CASE-CAFE_B_*'},
    'CASE_N': {'title': '난정평화교육원 2025 위험성평가 결과(급식실)',
               'path': '261113_restaurant_completed_assessments_DR/261113_난정평화교육원_2025_위험성평가결과_원본_DR.pdf',
               'page_basis': 'PDF 쪽', 'note': '급식실 사례. row CASE-KITCHEN_N_*'},
    'DESIGN': {'title': 'Safe-T 화면설계서 v3.19', 'path': '261115_SafeT_화면설계서_v3.19_통합본_SH_v3.pdf',
               'page_basis': 'PDF 쪽', 'note': '화면 예시. 안전 근거가 아니다. 제안 항목의 출처 표시용.'},
    'PHOTO': {'title': '실제사진 폴더 관찰', 'path': '실제사진/',
              'note': '사진에서 기기 존재를 관찰한 것. 위험요인 근거가 아니다.'},
}

HAZARDS = {
    'slip': '미끄러짐·넘어짐', 'cut': '베임·절단·끼임', 'burn': '고온 접촉·화상', 'fire': '화재',
    'gas': '가스 누출·폭발', 'electric': '감전·전기 위험', 'chemical': '세척제·화학물질',
    'ergonomic': '중량물·근골격계 부담', 'falling': '낙하·충돌·추락', 'respiratory': '조리흄·환기·유해가스 노출',
    'traffic': '교통사고', 'noise_vibration': '소음·진동', 'heat_cold': '고열·한랭 노출', 'entrapment': '냉장·냉동실 갇힘',
}
HAZARD_SOURCE = '261113_위험요인설정_검토_DR/261113_분야별_위험요인_설정_v1_DR.json (model_risk_types 10개 + additional_topics 4개)'

INDUSTRIES = [('chicken', '치킨'), ('bunsik', '분식'), ('cafe', '카페'), ('korean', '한식'), ('other', '기타')]
BASIS_TYPES = {
    '업종근거': 'D8 해당 업종 절에 기기가 명시됨(치킨→치킨, 카페→커피, 한식→한식).',
    '공통근거': '음식점업 공통 자료(CHK·D5·사례)에 있음. 이 업종 목록에 넣는 판단은 프로젝트 제안이며 검수 필요.',
    '제안': '이 업종에 대한 근거 자료 없음. 다른 업종 근거·사진 관찰·화면 예시를 참고한 제안.',
}


def r(src, page, loc=''):
    return {'src': src, 'page': page, 'locator': loc}


# 각 항목: id, 표준명, 구역, 동의어, 위험요인[(code, 요약, [refs])], 근거[refs], 업종{code: (basis_type, note)}
E = []


def add(eid, name, area, syn, hazards, refs, ind, note=''):
    E.append(dict(eid=eid, name=name, area=area, syn=syn, hazards=hazards, refs=refs, ind=ind, note=note))


# ---------------- 조리 기기 ----------------
add('EQ_FRYER', '튀김기', 'kitchen', ['프라이어', '딥프라이어', '튀김솥', '전기튀김기', '가스튀김기'],
    [('burn', '튀김기 열기·기름에 화상', [r('D8', 265, 'D8-p265-s1-c01'), r('D8', 250, 'D8-p250-s1-c01')]),
     ('fire', '유류화재(식용유 착화)', [r('D8', 265), r('D5', 64, 'D5-p064-s1-c01')]),
     ('slip', '튀김기 주변 바닥 기름으로 넘어짐', [r('D8', 265)]),
     ('gas', '가스식 조리설비 배관·호스 누출', [r('CHK', 6, 'CHK-4-2-3-01')])],
    [r('CHK', 6, 'CHK-4-2-3 조리설비·기구(회전식 국솥, 튀김기 등)'), r('D8', 264, '치킨 ④ 조리 및 담기: 튀김기, 오븐기'),
     r('D8', 250, '한식 ④ 조리: 튀김기'), r('D8', 96, '국외: 딥프라이어')],
    {'chicken': ('업종근거', 'D8 p264'), 'bunsik': ('제안', '분식 근거 없음. 튀김 메뉴 가정'),
     'korean': ('업종근거', 'D8 p250'), 'other': ('공통근거', 'CHK p6')})
add('EQ_GAS_RANGE', '가스레인지', 'kitchen', ['가스테이블', '화구', '버너', '레인지', '중화레인지', '쿡탑'],
    [('gas', '가스 누출 시 화재·폭발', [r('CHK', 6, 'CHK-4-2-2-02'), r('D8', 251)]),
     ('respiratory', '불완전 연소로 CO 발생·중독', [r('D8', 251, 'D8-p251-s1-c01')]),
     ('burn', '가스테이블 본체·증기에 화상', [r('D8', 251)]),
     ('fire', '조리 중 화재', [r('D5', 64)])],
    [r('CHK', 6, 'CHK-4-2-2 가스테이블(가스레인지)'), r('D8', 250, '한식 ④ 조리: 가스테이블'), r('D8', 255, '중식: 가스테이블')],
    {'chicken': ('공통근거', 'CHK p6. 화면설계서 p9 치킨 예시에도 있음'), 'bunsik': ('공통근거', 'CHK p6'),
     'korean': ('업종근거', 'D8 p250'), 'other': ('공통근거', 'CHK p6')})
add('EQ_OVEN', '오븐', 'kitchen', ['오븐기', '컨벡션오븐', '콤비오븐', '화덕', '로스터'],
    [('burn', '고온 스팀·본체·핫플레이트에 화상', [r('D8', 250), r('D8', 273)]),
     ('falling', '개방된 오븐 문에 부딪힘', [r('D8', 250)]),
     ('fire', '밀폐용기 가열 시 폭발·가연물 화재', [r('D8', 250)]),
     ('slip', '오븐 주변 밀가루 등으로 넘어짐', [r('D8', 250)])],
    [r('D8', 264, '치킨: 오븐기'), r('D8', 250, '한식: 오븐기'), r('D8', 273, '제과제빵: 오븐기'), r('D8', 96, '국외: 오븐')],
    {'chicken': ('업종근거', 'D8 p264'), 'cafe': ('제안', 'D8 제과제빵 p273-274 참고. 커피 절에는 없음'),
     'korean': ('업종근거', 'D8 p250'), 'other': ('제안', '공통 점검표에 없음')})
add('EQ_GRILL', '그릴', 'kitchen', ['샐러맨더', '상부 가열식 그릴', '숯불구이기', '석쇠'],
    [('burn', '고온 본체에 화상', [r('D8', 96)]), ('fire', '기름·가연물 화재', [r('D8', 96)])],
    [r('D8', 96, '국외 레스토랑: 가스레인지·오븐·그릴 사용'), r('PHOTO', None, 'seongdong_bbq_haengdang_3')],
    {'chicken': ('제안', '사진 관찰(BBQ 행당점)'), 'korean': ('제안', '구이 메뉴 가정'), 'other': ('제안', '')},
    note='국내 음식점 자료 근거 없음. 국외 가이드(D8 p96)만 있음.')
add('EQ_MICROWAVE', '전자레인지', 'kitchen', ['전자렌지'],
    [('burn', '꺼낸 용기·증기에 화상', [r('D8', 96)]), ('electric', '금속 용기 사용 시 스파크', [r('D8', 96)])],
    [r('D8', 96, '국외: 전자레인지 사용'), r('D8', 274, '제과제빵 ⑤ 진열·판매: 전자렌지')],
    {'chicken': ('제안', '사진 관찰(bhc 휘경점, BBQ 영상)'), 'bunsik': ('제안', ''), 'cafe': ('제안', 'D8 제과제빵 p274 참고'),
     'other': ('제안', '')})
add('EQ_RICE_COOKER', '취반기·밥솥', 'kitchen', ['취반기', '전기밥솥', '업소용 밥솥', '가스밥솥'],
    [('burn', '고온 본체·그릇·증기에 화상', [r('D8', 250)]), ('slip', '주변 바닥 미끄러움', [r('D8', 250)]),
     ('ergonomic', '쌀·밥솥 운반 중량물', [r('D8', 250)])],
    [r('D8', 250, '한식 ④ 조리: 취반기'), r('D5', 71, '후드 유속 기준표: 밥솥')],
    {'chicken': ('제안', '사진 관찰(교촌 용답점)'), 'bunsik': ('제안', '김밥·덮밥 메뉴 가정'),
     'korean': ('업종근거', 'D8 p250'), 'other': ('제안', '')})
add('EQ_SOUP_KETTLE', '국솥', 'kitchen', ['회전식 국솥', '대형국솥', '스팀솥', '육수솥'],
    [('burn', '국솥 운반·증기 화상, 전면 차열판 필요', [r('CHK', 6, 'CHK-4-2-3-07'), r('D8', 251)]),
     ('cut', '접이식 덮개 모서리·고정 불량', [r('CHK', 6, 'CHK-4-2-3-05')]),
     ('ergonomic', '중량물 취급 요통', [r('D8', 251)]), ('gas', '가스 누출 점화로 화재·폭발', [r('D8', 251)])],
    [r('CHK', 6, 'CHK-4-2-3 조리설비·기구(회전식 국솥, 튀김기 등)'), r('D8', 250, '한식: 대형국솥')],
    {'bunsik': ('제안', '국물 메뉴 가정'), 'korean': ('업종근거', 'D8 p250'), 'other': ('공통근거', 'CHK p6')})
add('EQ_GRIDDLE', '철판(그리들)', 'kitchen', ['그리들', '전기 그리들', '떡볶이 철판', '부침 철판'],
    [('burn', '고온 철판 접촉', []), ('fire', '기름 화재', []), ('gas', '가스식인 경우 누출', [])],
    [], {'bunsik': ('제안', ''), 'korean': ('제안', ''), 'other': ('제안', '')},
    note='근거 자료 없음. 위험요인도 제안.')
add('EQ_STEAMER', '찜기', 'kitchen', ['만두 찜기', '찜솥', '스티머'],
    [('burn', '증기 화상', [])], [], {'bunsik': ('제안', ''), 'korean': ('제안', ''), 'other': ('제안', '')},
    note='근거 자료 없음. 위험요인도 제안.')
add('EQ_ODEN_WARMER', '어묵 보온기', 'kitchen', ['어묵 온장고', '보온통', '중탕기'],
    [('burn', '뜨거운 국물·본체 접촉', []), ('electric', '물기 있는 전기기기', [])], [],
    {'bunsik': ('제안', '')}, note='근거 자료 없음. 위험요인도 제안.')
add('EQ_PORTABLE_BURNER', '휴대용 가스버너', 'hall', ['부루스타', '테이블 버너', '휴대용 가스레인지'],
    [('gas', '부탄캔 과열·누출 폭발', []), ('fire', '화재', []), ('burn', '화상', [])], [],
    {'bunsik': ('제안', '즉석 메뉴 가정'), 'korean': ('제안', '홀 조리 메뉴 가정'), 'other': ('제안', '')},
    note='근거 자료 없음. 위험요인도 제안.')
add('EQ_COOKING_ROBOT', '조리 로봇', 'kitchen', ['튀김 로봇', '로봇팔', '협동로봇'],
    [('cut', '로봇팔 동작 범위에서 끼임·충돌', []), ('burn', '튀김 공정 화상', [])],
    [r('PHOTO', None, 'K01_kyochon_robot')], {'chicken': ('제안', '사진 관찰')},
    note='근거 자료 없음. 산업용 로봇 관련 기준 확인 필요(미확인).')

# ---------------- 전처리·가공 기기 ----------------
add('EQ_KNIFE_BOARD', '칼·도마', 'kitchen', ['칼', '식칼', '도마', '조리용 칼'],
    [('cut', '칼에 절단·베임·찔림', [r('D8', 249), r('D8', 264), r('D5', 69, 'D5-p069-s1-c01')]),
     ('falling', '칼·도마가 작업대에서 떨어져 발등 상해', [r('D8', 249), r('D8', 264)]),
     ('ergonomic', '반복 칼질 근골격계 부담', [r('D8', 249)])],
    [r('D8', 263, '치킨 ③ 전처리: 칼, 가위'), r('D8', 249, '한식 ③ 전처리: 칼, 가위'), r('D8', 267, '커피 ② 검수·보관: 칼(사무용)'),
     r('D5', 69, '절단용 수공구(칼) 작업'), r('DESIGN', 14, 'S03 예시 태그 "칼·도마"')],
    {'chicken': ('업종근거', 'D8 p263'), 'bunsik': ('제안', ''), 'cafe': ('업종근거', 'D8 p267 칼(사무용). 조리용 칼은 아님'),
     'korean': ('업종근거', 'D8 p249'), 'other': ('공통근거', 'D5 p69')},
    note='화면설계서 S03 예시처럼 칼과 도마를 한 항목으로 묶음.')
add('EQ_SCISSORS', '주방가위', 'kitchen', ['가위', '조리용 가위'],
    [('cut', '베임·찔림', [r('D8', 263)])],
    [r('D8', 263, '치킨: 칼, 가위'), r('D8', 249, '한식: 칼, 가위')],
    {'chicken': ('업종근거', 'D8 p263'), 'bunsik': ('제안', ''), 'korean': ('업종근거', 'D8 p249'), 'other': ('제안', '')})
add('EQ_VEG_CUTTER', '채소절단기', 'kitchen', ['야채절단기', '야채 슬라이서', '채칼', '다지기'],
    [('cut', '칼날에 손 절단·베임, 방호덮개·인터록 필요', [r('D8', 264), r('CHK', 5, 'CHK-4-2-1-02')]),
     ('electric', '젖은 손 조작·가공기계 누전', [r('D8', 264), r('CHK', 5, 'CHK-4-2-1-08')])],
    [r('D8', 263, '치킨 ③ 전처리: 채소절단기'), r('D8', 249, '한식 ③ 전처리'), r('CHK', 5, 'CHK-4-2-1 식품가공기계(파쇄·절단·반죽·혼합·제면기)'),
     r('D5', 58, '칼, 수동 절단기 사용 작업')],
    {'chicken': ('업종근거', 'D8 p263'), 'bunsik': ('제안', ''), 'korean': ('업종근거', 'D8 p249'), 'other': ('공통근거', 'CHK p5')},
    note='수동 채칼도 동의어로 둠. 동력 기기와 위험 수준이 다르므로 검수 시 분리 여부 판단 필요.')
add('EQ_MEAT_SLICER', '육절기', 'kitchen', ['고기 슬라이서', '고기 절단기', '골절기'],
    [('cut', '육절기 작업 중 베임', [r('D5', 69)]), ('electric', '가공기계 누전', [r('CHK', 5, 'CHK-4-2-1-08')])],
    [r('D5', 69, '육절기 작업 중 베임 사망사례'), r('CHK', 5, '식품가공기계(절단기)'), r('D8', 97, '국외: 슬라이서')],
    {'korean': ('공통근거', 'D5 p69'), 'other': ('공통근거', 'D5 p69, CHK p5')})
add('EQ_MIXER', '혼합기·믹서기', 'kitchen', ['믹서', '믹서기', '블렌더', '분쇄기', '푸드프로세서', '소스 혼합기'],
    [('cut', '회전부에 옷·손 말림, 투입구·청소 중 끼임', [r('D8', 264), r('D5', 68, 'D5-p068-s1-c01')]),
     ('electric', '젖은 손 조작·누전', [r('D8', 264), r('CHK', 5)])],
    [r('D8', 263, '치킨 ③ 전처리: 분쇄기·믹서기'), r('D8', 264, '치킨: 소스 혼합기 회전부'), r('D8', 268, '커피 ③: 믹서기'),
     r('CHK', 5, '식품가공기계(혼합기)'), r('D5', 68, '혼합기(식품가공용) 작업')],
    {'chicken': ('업종근거', 'D8 p263-264'), 'bunsik': ('제안', ''), 'cafe': ('업종근거', 'D8 p268'),
     'korean': ('공통근거', 'CHK p5'), 'other': ('공통근거', 'CHK p5')})
add('EQ_DOUGH_MIXER', '반죽기', 'kitchen', ['반죽 믹서', '니더'],
    [('cut', '작동 중 용기 이물질 제거 시 손 말림', [r('D8', 255)]), ('electric', '본체 절연 파괴 누전', [r('D8', 255)])],
    [r('D8', 255, '중식: 반죽기'), r('D8', 272, '제과제빵 ③: 반죽기'), r('CHK', 5, '식품가공기계(반죽)')],
    {'bunsik': ('제안', 'D8 중식 p255 참고(면·만두 반죽 가정)'), 'cafe': ('제안', 'D8 제과제빵 p272 참고'),
     'other': ('공통근거', 'CHK p5')},
    note='화면설계서 B02(9쪽)에서 치킨 업종 "직접 추가" 예시로 쓰임. 치킨 기본 목록에는 넣지 않음.')
add('EQ_NOODLE_MACHINE', '제면기', 'kitchen', ['국수 기계', '면 뽑는 기계'],
    [('cut', '롤러에 손 감김·협착', [r('D8', 253)]), ('electric', '누전 감전', [r('D8', 253)])],
    [r('D8', 253, '중식 개요: 제면기'), r('CHK', 5, '식품가공기계(제면기)'), r('D5', 68, '제면작업')],
    {'bunsik': ('제안', 'D8 중식 p253-255 참고(면 메뉴 가정)'), 'korean': ('제안', ''), 'other': ('공통근거', 'CHK p5')})
add('EQ_RICE_WASHER', '세미기', 'kitchen', ['쌀 세척기'],
    [('cut', '회전부에 옷 감김·끼임', [r('D8', 249)]), ('electric', '젖은 손 작동 감전', [r('D8', 249)])],
    [r('D8', 249, '한식 ③ 전처리: 세미기')], {'korean': ('업종근거', 'D8 p249'), 'other': ('제안', '')})
add('EQ_MARINATOR', '염지기', 'kitchen', ['염지 텀블러', '진공 텀블러', '염지통'],
    [('cut', '회전 드럼 끼임(제안)', []), ('electric', '물기 있는 전기기기(제안)', [])],
    [r('DESIGN', 9, 'B02 치킨 목록 예시 "염지기"')], {'chicken': ('제안', '화면설계서 예시')},
    note='안전 자료 근거 없음. 화면 예시에서만 확인. 실제 매장 보유 여부 확인 필요.')

# ---------------- 음료 기기 ----------------
add('EQ_COFFEE_MACHINE', '커피머신', 'kitchen', ['에스프레소 머신', '샷 추출기', '스팀기', '스팀 노즐'],
    [('burn', '고온 스팀·본체·뜨거운 우유에 화상', [r('D8', 269, 'D8-p269-s1-c01')]),
     ('slip', '주변 바닥 물기로 넘어짐', [r('D8', 269)]), ('electric', '젖은 손 기기 작동 감전', [r('D8', 269)]),
     ('ergonomic', '반복 추출·장시간 입식', [r('D8', 269)])],
    [r('D8', 268, '커피 ③ 기계점검: 그라인더, 믹서기, 스팀기'), r('D8', 269, '커피 ④ 샷 추출: 샷 추출기, ⑤ 스팀기')],
    {'cafe': ('업종근거', 'D8 p268-269')})
add('EQ_COFFEE_GRINDER', '커피 그라인더', 'kitchen', ['그라인더', '원두 분쇄기'],
    [('cut', '분쇄부 접촉(방호덮개·인터록)', [r('D8', 268)]), ('electric', '외함접지·누전차단기', [r('D8', 269)])],
    [r('D8', 268, '커피 ③ 기계점검: 그라인더')], {'cafe': ('업종근거', 'D8 p268')})
add('EQ_ICE_MAKER', '제빙기', 'kitchen', ['아이스 메이커'],
    [('electric', '물기 있는 전기기기', []), ('slip', '주변 물기', []), ('chemical', '세척·소독제 취급', [])], [],
    {'chicken': ('제안', ''), 'cafe': ('제안', ''), 'other': ('제안', '')}, note='근거 자료 없음. 위험요인도 제안.')
add('EQ_ICE_CRUSHER', '쇄빙기·빙수기', 'kitchen', ['빙삭기', '빙수기계', '얼음 분쇄기'],
    [('cut', '회전날 접촉(제안)', []), ('electric', '물기 있는 전기기기(제안)', [])],
    [r('D8', 274, '제과제빵 ⑤ 진열·판매: 쇄빙기')], {'cafe': ('제안', 'D8 제과제빵 p274 참고'), 'other': ('제안', '')},
    note='D8은 기기명만 제시. 위험요인은 제안.')
add('EQ_WATER_HEATER', '온수기', 'kitchen', ['소형 온수기', '전기온수기', '온수 디스펜서'],
    [('burn', '뜨거운 물 화상(제안)', []), ('electric', '전기기기(제안)', [])],
    [r('DESIGN', 14, 'S03 AI 인식 예시 "소형 온수기"')],
    {'chicken': ('제안', '화면설계서 예시'), 'bunsik': ('제안', ''), 'cafe': ('제안', ''), 'other': ('제안', '')},
    note='안전 자료 근거 없음.')
add('EQ_BEER_DISPENSER', '생맥주 디스펜서', 'hall', ['생맥주 기계', '맥주 서버', '탄산가스 용기'],
    [('gas', '탄산가스(CO2) 용기 취급(제안)', []), ('falling', '케그·가스용기 넘어짐(제안)', []),
     ('ergonomic', '케그 운반(제안)', [])],
    [r('PHOTO', None, '261113_P01_bApoYZBPCLE_0148.00s_DR(추정)')], {'chicken': ('제안', '사진 관찰 추정'), 'other': ('제안', '')},
    note='근거 자료 없음. 사진 판독도 추정.')

# ---------------- 세척·위생 ----------------
add('EQ_DISHWASHER', '식기세척기', 'kitchen', ['세척기', '컨베이어 식기세척기', '도어형 세척기'],
    [('cut', '컨베이어에 손 말림', [r('CHK', 8, 'CHK-4-2-5-01')]),
     ('electric', '접지·누전차단기 미흡', [r('CHK', 8, 'CHK-4-2-5-03')]),
     ('burn', '증기가 근로자 방향 배출', [r('CHK', 8, 'CHK-4-2-5-06')]),
     ('slip', '주변 물기', [r('CHK', 8, 'CHK-4-2-5-08')]), ('noise_vibration', '85dB 이상 소음 장소', [r('CHK', 13, 'CHK-4-4-2-09')])],
    [r('CHK', 8, 'CHK-4-2-5 식기세척기'), r('D8', 266, '치킨 ⑥ 후처리: 세척기'), r('D8', 270, '커피 ⑥: 세척기'), r('D8', 252, '한식 ⑥: 세척기')],
    {'chicken': ('업종근거', 'D8 p266'), 'bunsik': ('공통근거', 'CHK p8'), 'cafe': ('업종근거', 'D8 p270'),
     'korean': ('업종근거', 'D8 p252'), 'other': ('공통근거', 'CHK p8')})
add('EQ_STERILIZER', '식기소독기', 'kitchen', ['소독기', '살균기', '자외선 살균기', '컵 소독기'],
    [('burn', '고온 소독 화상(제안)', []), ('chemical', '살균기 자외선 노출 피부질환(도어 인터록)', [r('D8', 252)])],
    [r('D8', 266, '치킨 ⑥: 소독기'), r('D8', 270, '커피 ⑥: 소독기'), r('D8', 252, '한식 ⑥: 소독기, 살균기 자외선')],
    {'chicken': ('업종근거', 'D8 p266'), 'bunsik': ('제안', ''), 'cafe': ('업종근거', 'D8 p270'),
     'korean': ('업종근거', 'D8 p252'), 'other': ('제안', '')},
    note='자외선 노출을 chemical로 분류한 것은 임시. 위험유형 체계에 맞는 코드 없음.')
add('EQ_SINK', '세척대(싱크대)', 'kitchen', ['싱크대', '개수대', '세정대'],
    [('slip', '바닥 물기·호스에 넘어짐', [r('D8', 252)]), ('electric', '젖은 손으로 콘센트 접촉', [r('D8', 252)]),
     ('chemical', '세척제 피부질환', [r('D8', 252)]), ('cut', '깨진 그릇 베임', [r('D8', 252)])],
    [r('D8', 252, '한식 ⑥ 후처리(설거지) 작업 위험. 기기 목록에는 없음')],
    {'chicken': ('제안', '설거지 작업 근거 D8 p266'), 'bunsik': ('제안', ''), 'cafe': ('제안', ''),
     'korean': ('제안', '설거지 작업 근거 D8 p252'), 'other': ('제안', '')},
    note='D8은 설거지 작업 위험을 다루지만 기기 목록에 싱크대를 넣지 않음. 기기 항목화는 제안.')
add('EQ_EXHAUST_HOOD', '배기후드', 'kitchen', ['후드', '배기팬', '환풍기', '덕트', '환기설비'],
    [('falling', '후드 청소 시 의자·조리대에서 떨어짐', [r('CHK', 8, 'CHK-4-2-6-02'), r('D8', 252)]),
     ('cut', '배기팬 회전체 접촉', [r('CHK', 8, 'CHK-4-2-6-05')]), ('electric', '배기팬 접지·누전', [r('CHK', 8, 'CHK-4-2-6-04')]),
     ('respiratory', '조리흄·환기 불량', [r('CHK', 8, 'CHK-4-2-6-03'), r('D5', 71)]),
     ('fire', '후드·덕트 기름때', [r('CHK', 8, 'CHK-4-2-6-01')]), ('noise_vibration', '소음 장소', [r('CHK', 13, 'CHK-4-4-2-09')])],
    [r('CHK', 8, 'CHK-4-2-6 배기후드'), r('D5', 70, '배기후드 점검·청소'), r('D8', 252, '한식 후드청소')],
    {'chicken': ('공통근거', 'CHK p8'), 'bunsik': ('공통근거', 'CHK p8'), 'korean': ('업종근거', 'D8 p252-253 후드청소'),
     'other': ('공통근거', 'CHK p8')})
add('EQ_WASTE_OIL_CONTAINER', '폐유통', 'kitchen', ['폐식용유 통', '기름받이 통'],
    [('burn', '뜨거운 폐유 운반 중 화상', [r('D8', 252)]), ('ergonomic', '폐유 운반 중량물(제안)', []),
     ('slip', '기름 흘림(제안)', [])],
    [r('D8', 266, '치킨 ⑥ 후처리: 폐유 담은 통'), r('D8', 252, '폐유 운반 중 화상')],
    {'chicken': ('업종근거', 'D8 p266'), 'korean': ('제안', 'D8 p252 폐유 운반 작업 참고'), 'other': ('제안', '')})

# ---------------- 보관·운반 ----------------
add('EQ_REFRIGERATOR', '업소용 냉장·냉동고', 'storage', ['냉장고', '냉동고', '업소용 냉장고', '테이블 냉장고', '김치냉장고', '다목적 냉동고'],
    [('slip', '냉장·냉동고 출입 시 넘어짐', [r('D8', 248)]), ('heat_cold', '장시간 저온 작업', [r('CHK', 10, 'CHK-4-3-1-10')]),
     ('falling', '적재물 낙하(제안)', []), ('electric', '전기기기 누전(제안)', [])],
    [r('CHK', 10, 'CHK-4-3-1 식자재 운반·보관(냉장·냉동고)'), r('D8', 263, '치킨 ② 냉장고 보관'), r('D8', 267, '커피 ② 냉장고'),
     r('D8', 248, '한식 ② 냉장고'), r('DESIGN', 14, 'S03 예시 "업소용 냉장고"')],
    {'chicken': ('업종근거', 'D8 p263'), 'bunsik': ('공통근거', 'CHK p10'), 'cafe': ('업종근거', 'D8 p267'),
     'korean': ('업종근거', 'D8 p248'), 'other': ('공통근거', 'CHK p10')})
add('EQ_WALKIN_COOLER', '냉장·냉동창고', 'storage', ['워크인 냉장고', '워크인 냉동고', '냉동창고', '저온창고'],
    [('entrapment', '출입문이 안에서 열리지 않아 갇힘', [r('CHK', 10, 'CHK-4-3-1-09'), r('CHK', 14, 'CHK-4-4-3-07')]),
     ('heat_cold', '한랭 노출·저체온', [r('CHK', 14, 'CHK-4-4-3-10')]), ('slip', '출입 시 넘어짐', [r('D5', 72)])],
    [r('CHK', 10, '냉장·냉동고 출입문'), r('CHK', 14, '냉동·냉장창고')],
    {'korean': ('공통근거', 'CHK p10, p14'), 'other': ('공통근거', 'CHK p10, p14')},
    note='사람이 들어가는 창고형만 해당. 일반 냉장고와 구분.')
add('EQ_DISPLAY_COOLER', '쇼케이스 냉장고', 'hall', ['음료 쇼케이스', '음료 냉장고', '진열 냉장고', '매대'],
    [('electric', '매대 전선 노출 감전', [r('D8', 274)]), ('falling', '이동대차와 부딪힘', [r('D8', 274)])],
    [r('D8', 274, '제과제빵 ⑤ 진열·판매 매대')],
    {'chicken': ('제안', '사진 관찰(bhc 휘경점)'), 'bunsik': ('제안', ''), 'cafe': ('제안', 'D8 제과제빵 p274 참고'),
     'korean': ('제안', ''), 'other': ('제안', '')})
add('EQ_CART', '운반대차', 'storage', ['이동대차', '카트', '서빙카트', '대차', '서빙용 이동식 대차'],
    [('ergonomic', '중량물 운반', [r('CHK', 10, 'CHK-4-3-1-03'), r('D8', 248)]),
     ('falling', '과적·편하중으로 물체 낙하', [r('D8', 248)]), ('cut', '이동식 대차에 끼임', [r('D8', 248)]),
     ('slip', '바닥 돌출부·트랜치에 걸려 넘어짐', [r('D8', 248)])],
    [r('CHK', 10, '운반대차'), r('D5', 72, '운반대차'), r('D8', 262, '치킨 ① 이동대차'), r('D8', 267, '커피 ① 이동대차'),
     r('D8', 248, '한식 ① 이동대차')],
    {'chicken': ('업종근거', 'D8 p262'), 'bunsik': ('공통근거', 'CHK p10'), 'cafe': ('업종근거', 'D8 p267'),
     'korean': ('업종근거', 'D8 p248'), 'other': ('공통근거', 'CHK p10')})
add('EQ_SHELF', '적재 선반', 'storage', ['선반', '벽선반', '랙', '수납선반'],
    [('falling', '선반에서 중량물 낙하·불안정한 발판에서 떨어짐', [r('D8', 248), r('CHK', 10, 'CHK-4-3-1-07')]),
     ('cut', '선반 날카로운 부분에 부딪힘·베임', [r('CHK', 10, 'CHK-4-3-1-06')]), ('ergonomic', '인력 적재 요통', [r('D8', 248)])],
    [r('CHK', 10, '선반'), r('D5', 72, '선반'), r('D8', 263, '치킨 ② 적재·보관'), r('D8', 268, '커피 적재·보관'), r('D8', 248, '한식 적재·보관')],
    {'chicken': ('업종근거', 'D8 p263'), 'bunsik': ('공통근거', 'CHK p10'), 'cafe': ('업종근거', 'D8 p268'),
     'korean': ('업종근거', 'D8 p248'), 'other': ('공통근거', 'CHK p10')},
    note='D8은 기기 목록이 아니라 위험요인 표에서 선반을 다룸. 작업대 하부 선반은 제외.')
add('EQ_LADDER', '사다리·작업발판', 'storage', ['이동식 사다리', 'A형 사다리', '발붙임 사다리', '작업발판'],
    [('falling', '사다리·발판에서 추락', [r('CHK', 3, 'CHK-4-1-2'), r('D5', 66)]),
     ('electric', '주변 전선 감전', [r('CHK', 3, 'CHK-4-1-2-12')])],
    [r('CHK', 3, 'CHK-4-1-2 사다리'), r('D5', 58, '사다리 작업 중 추락')],
    {k: ('공통근거', 'CHK p3-4') for k, _ in INDUSTRIES})
add('EQ_DUMBWAITER', '덤웨이터(간이리프트)', 'storage', ['음식 운반용 승강기', '간이리프트', '리프트'],
    [('cut', '운반구·출입문 사이 끼임', [r('D5', 67), r('CHK', 7, 'CHK-4-2-4-08')]),
     ('falling', '탑승·추락', [r('CHK', 7, 'CHK-4-2-4-01'), r('CHK', 10, 'CHK-4-3-1-12')])],
    [r('CHK', 7, 'CHK-4-2-4 리프트(간이리프트 등)'), r('D5', 67, '음식 운반용 승강기(덤웨이터)')],
    {'korean': ('공통근거', 'CHK p7'), 'other': ('공통근거', 'CHK p7')}, note='다층 매장에만 해당.')

# ---------------- 배달·설비 ----------------
add('EQ_MOTORCYCLE', '배달 이륜차', 'delivery', ['오토바이', '스쿠터', '배달 오토바이'],
    [('traffic', '배달 중 교통사고', [r('CHK', 9, 'CHK-4-2-7'), r('D5', 59), r('D8', 265)]),
     ('slip', '빗길·빙판길 미끄러짐', [r('D8', 251)])],
    [r('CHK', 9, 'CHK-4-2-7 이륜차'), r('D8', 265, '치킨 ⑤ 배달: 이륜차'), r('D8', 251, '한식 ⑤ 배달: 이륜차'), r('D5', 59, '이륜차 배달업무')],
    {'chicken': ('업종근거', 'D8 p265'), 'bunsik': ('공통근거', 'CHK p9'), 'cafe': ('공통근거', 'CHK p9'),
     'korean': ('업종근거', 'D8 p251'), 'other': ('공통근거', 'CHK p9')},
    note='사진 인식 대상 아님(주방·홀 사진에 잘 나오지 않음). B02 목록용.')
add('EQ_GAS_CYLINDER', '가스용기(LPG·부탄)', 'facility', ['LPG 용기', '가스통', '부탄캔', '부탄가스'],
    [('gas', '용기 전도·파손으로 누출, 화재·폭발', [r('CASE_A', 16, 'CASE-FOOD_A_02'), r('CASE_A', 17, 'CASE-FOOD_A_03')]),
     ('fire', '인화성 가스 화재', [r('CHK', 12, 'CHK-4-4-1-06')])],
    [r('CASE_A', 16, 'LPG 가스용기 전도방지'), r('CHK', 12, 'LPG가스 검지·경보장치'), r('D5', 64, 'LPG·LNG 감지기 위치')],
    {'chicken': ('공통근거', 'CHK p12'), 'bunsik': ('공통근거', 'CHK p12'), 'korean': ('공통근거', 'CHK p12, 사례 p16-17'),
     'other': ('공통근거', 'CHK p12')},
    note='부탄캔은 사진 관찰로 동의어에 추가. LPG 용기와 위험 수준이 다르므로 분리 여부 검수 필요.')
add('EQ_ELECTRIC_PANEL', '전기설비(분전반·콘센트·멀티탭)', 'facility', ['분전반', '콘센트', '멀티탭', '연장선', '전선'],
    [('electric', '분전반 잠금·표지 미흡, 바닥 콘센트 파손 감전', [r('CASE_N', 42, 'CASE-KITCHEN_N_01'), r('CASE_A', 15, 'CASE-FOOD_A_01')]),
     ('fire', '콘센트 파손·전선 과열 화재', [r('CASE_A', 15, 'CASE-FOOD_A_01')]),
     ('gas', '가스 배관에 전선 고정 시 화재·폭발', [r('CASE_A', 18, 'CASE-FOOD_A_04')])],
    [r('CASE_A', 15, '바닥 콘센트'), r('CASE_A', 18, '가스배관 전선 고정'), r('CASE_N', 42, '분전반'), r('D8', 97, '통로 전기 코드'),
     r('CHK', 5, '누전차단기')],
    {k: ('공통근거', '사례 CASE_A p15·p18, CASE_N p42') for k, _ in INDUSTRIES},
    note='기기보다 설비에 가까움. B02 목록 포함 여부는 팀 결정 필요.')

INCLUDED_NOT = {
    '소화기·가스누설경보기·자동차단기': '안전장치·대책이므로 기기 목록에서 제외. 위험요인 대책 쪽에서 다룸.',
    '세제·청소기·빵틀·피자샵': 'D8 기계·기구 목록에 있으나 기기 인식·업종 목록 가치가 낮아 제외(제외 판단은 제안).',
    '중화웍·피자반달칼': '중식·피자 전용. Safe-T 업종(치킨·분식·카페·한식·기타)에 해당 절 없음.',
    '작업대·조리대': '거의 모든 사진에 있어 구분력이 낮음. 제외(제안).',
}


def main():
    ind_names = dict(INDUSTRIES)
    items = []
    for e in E:
        any_src = [x for x in e['refs'] if x['src'] not in ('DESIGN', 'PHOTO')]
        hz_has_src = any(h[2] for h in e['hazards'])
        items.append({
            'equipment_id': e['eid'], 'standard_name': e['name'], 'area': e['area'], 'synonyms': e['syn'],
            'evidence_status': '근거있음' if any_src else '제안',
            'hazard_evidence_status': '근거있음' if hz_has_src else '제안',
            'related_hazards': [{'code': c, 'name': HAZARDS[c], 'summary': s, 'refs': refs,
                                 'evidence': '근거있음' if refs else '제안'} for c, s, refs in e['hazards']],
            'sources': e['refs'],
            'industries': [{'industry': k, 'industry_name': ind_names[k], 'basis_type': v[0], 'basis_note': v[1]}
                           for k, v in e['ind'].items()],
            'note': e['note'],
            'review_status': '전문가·팀 검수 전',
        })
    industry_lists = {}
    for k, nm in INDUSTRIES:
        lst = []
        for it in items:
            for ind in it['industries']:
                if ind['industry'] == k:
                    lst.append({'equipment_id': it['equipment_id'], 'standard_name': it['standard_name'],
                                'basis_type': ind['basis_type'], 'basis_note': ind['basis_note']})
        order = {'업종근거': 0, '공통근거': 1, '제안': 2}
        lst.sort(key=lambda x: order[x['basis_type']])
        industry_lists[k] = {'industry_name': nm, 'items': lst}

    master = {
        'name': 'Safe-T 업종별 기기 마스터 초안', 'version': VERSION, 'created_date_kst': CREATED,
        'status': '초안. 전문가·팀 검수 전. 확정 요구사항 아님.',
        'screen_refs': ['화면설계서 v3.19 p9(B02)', 'p14(S03)', 'p34(business_equipment, ai_found)'],
        'usage': {'B02': 'industry_lists[업종].items를 미체크 상태로 불러온다(source=db).',
                  'S03': '비전 인식 결과의 equipment_id는 equipment[] 안의 값만 쓴다.'},
        'id_rule': 'EQ_ + 영문 대문자 스네이크. 한 번 배포한 ID는 바꾸지 않는다(폐기 시 deprecated 표시 제안).',
        'basis_types': BASIS_TYPES, 'hazard_codes': HAZARDS, 'hazard_code_source': HAZARD_SOURCE,
        'sources': SOURCES, 'excluded_candidates': INCLUDED_NOT,
        'equipment': items, 'industry_lists': industry_lists,
    }
    with open(os.path.join(OUT, '261115_기기마스터_v1_DR.json'), 'w', encoding='utf-8') as f:
        json.dump(master, f, ensure_ascii=False, indent=2)

    def fmt_refs(refs):
        return '; '.join(f"{x['src']}" + (f" p{x['page']}" if x['page'] else '') + (f" ({x['locator']})" if x['locator'] else '') for x in refs)

    with open(os.path.join(OUT, '261115_기기마스터_v1_DR.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['equipment_id', 'standard_name', 'area', 'synonyms', 'evidence_status', 'hazard_codes',
                    'hazard_summary', 'hazard_evidence_status', 'sources'] + [nm for _, nm in INDUSTRIES] + ['note'])
        for it in items:
            ind = {x['industry']: x['basis_type'] for x in it['industries']}
            w.writerow([it['equipment_id'], it['standard_name'], it['area'], '|'.join(it['synonyms']), it['evidence_status'],
                        '|'.join(h['code'] for h in it['related_hazards']),
                        ' / '.join(f"{h['name']}: {h['summary']}" for h in it['related_hazards']),
                        it['hazard_evidence_status'], fmt_refs(it['sources'])]
                       + [ind.get(k, '') for k, _ in INDUSTRIES] + [it['note']])
    with open(os.path.join(OUT, '261115_기기마스터_업종별목록_v1_DR.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['industry', 'industry_name', 'order', 'equipment_id', 'standard_name', 'basis_type', 'basis_note'])
        for k, v in industry_lists.items():
            for i, x in enumerate(v['items'], 1):
                w.writerow([k, v['industry_name'], i, x['equipment_id'], x['standard_name'], x['basis_type'], x['basis_note']])
    print('equipment', len(items))
    for k, v in industry_lists.items():
        print(k, len(v['items']), {b: sum(1 for x in v['items'] if x['basis_type'] == b) for b in BASIS_TYPES})


if __name__ == '__main__':
    main()
