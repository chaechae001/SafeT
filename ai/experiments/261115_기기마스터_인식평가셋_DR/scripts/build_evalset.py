"""사진 기기 인식 평가셋 생성 스크립트.

실행(작업 폴더 루트에서): python 261115_기기마스터_인식평가셋_DR/scripts/build_evalset.py
입력: 실제사진/*.png|jpg (읽기만 함), 실제사진/261113_공개주방_이동파일목록_DR.json, 261115_기기마스터_v1_DR.json
출력: 261115_기기인식_평가셋_v1_DR.json, 261115_기기인식_평가셋_라벨_v1_DR.csv

라벨은 Claude가 사진을 보고 만든 AI 보조 라벨이다. 사람 검수 전이다.
영역은 EXIF 회전을 적용한 화면 기준 3x3 격자(행 1-3 위→아래, 열 A-C 왼쪽→오른쪽)로 표시한다.
bbox_norm은 격자 칸을 합친 대략 영역이며 정밀 박스가 아니다.
"""
import csv
import hashlib
import json
import os

from PIL import Image, ImageOps

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
OUT = os.path.join(ROOT, '261115_기기마스터_인식평가셋_DR')
PHOTO_DIR = os.path.join(ROOT, '실제사진')
LABEL_STATUS = 'AI 보조 라벨, 사람 검수 전'

# (equipment_id, visibility, grid, confidence, note)
L = {}
U = {}   # 판독 불확실 후보: (후보 equipment_id 또는 None, grid, 설명)
X = {}   # 마스터에 없는 기기: (이름, grid, 설명)
N = {}   # 이미지 메모

L['261113_P01_bApoYZBPCLE_0148.00s_DR'] = [
    ('EQ_REFRIGERATOR', 'clear', ['1A', '2A', '3A'], 'high', '세로형 업소용 냉장·냉동고, "냉동실" 표기'),
    ('EQ_KNIFE_BOARD', 'clear', ['3B'], 'high', '칼과 도마 사용 장면'),
    ('EQ_SHELF', 'clear', ['1B', '1C'], 'high', '벽면 적재 선반'),
    ('EQ_BEER_DISPENSER', 'partial', ['1C', '2C'], 'medium', '탭 손잡이가 있는 스테인리스 기기. 생맥주 디스펜서로 추정')]
U['261113_P01_bApoYZBPCLE_0148.00s_DR'] = [('EQ_ICE_CRUSHER', ['2B'], '파란색 기기. 빙수기·쇄빙기 또는 포장기로 추정, 판독 불가')]
N['261113_P01_bApoYZBPCLE_0148.00s_DR'] = '방송 화면(워크맨 127화 치킨집 자막). 근로자 얼굴 일부 노출(마스크 착용).'

L['261113_P04_bApoYZBPCLE_0513.00s_DR'] = [('EQ_FRYER', 'clear', ['1B', '2A', '2B', '2C', '3A', '3B', '3C'], 'high', '튀김 유조·바스켓·제어판')]
L['261113_P06_gkMLRGZIHsc_0311.00s_DR'] = [
    ('EQ_SHELF', 'clear', ['1A', '2A', '2B'], 'high', '스테인리스 벽 선반'),
    ('EQ_FRYER', 'partial', ['3A'], 'medium', '좌하단 튀김 바스켓·유조 일부')]
U['261113_P06_gkMLRGZIHsc_0311.00s_DR'] = [('EQ_MICROWAVE', ['1B'], '상단 검은 기기 일부. 전자레인지 추정')]
N['261113_P06_gkMLRGZIHsc_0311.00s_DR'] = '방송 화면(워크맨). 근로자 얼굴 노출.'
L['261113_P07_gkMLRGZIHsc_0314.00s_DR'] = [('EQ_FRYER', 'clear', ['1B', '1C', '2A', '2B', '2C', '3B', '3C'], 'high', '튀김 유조·바스켓')]
L['261113_P09_gkMLRGZIHsc_0414.00s_DR'] = [
    ('EQ_GAS_RANGE', 'clear', ['3B', '3C'], 'high', '다구 가스레인지, 불꽃 보임'),
    ('EQ_EXHAUST_HOOD', 'clear', ['1B', '1C'], 'high', '상부 배기후드'),
    ('EQ_SHELF', 'partial', ['2C', '3C'], 'medium', '우측 스테인리스 선반')]
U['261113_P09_gkMLRGZIHsc_0414.00s_DR'] = [(None, ['3A'], '좌하단 사각 용기. 보온 중탕기 또는 튀김기 일부, 판독 불가')]
N['261113_P09_gkMLRGZIHsc_0414.00s_DR'] = '방송 화면(워크맨). 근로자 옆모습 노출.'
L['261113_P11_TCdTyi29FJA_0095.90s_DR'] = [('EQ_FRYER', 'clear', ['2A', '3A', '3B'], 'high', '튀김 유조와 하단 제어판')]
L['261113_P12_TCdTyi29FJA_0103.00s_DR'] = [('EQ_FRYER', 'clear', ['1A', '2A', '2B', '3A'], 'high', '튀김 유조')]
L['C02_kkubeurakko_process_2'] = [('EQ_OVEN', 'clear', ['1A', '1B', '1C', '2A', '2B', '2C', '3A', '3B', '3C'], 'medium', '내부 가열부와 석쇠. 회전식 오븐·로스터로 추정')]
N['C02_kkubeurakko_process_2'] = '브랜드 홍보 이미지로 보임("굽고!" 자막). 출처 URL 미기록.'
L['C03_kkubeurakko_process_3'] = [('EQ_GAS_RANGE', 'clear', ['3A', '3B', '3C'], 'high', '고화력 가스버너, 불꽃 보임')]
X['C03_kkubeurakko_process_3'] = [('자동 볶음기(회전 드럼)', ['1A', '1B', '1C', '2A', '2B', '2C'], '구형 회전 조리통. 마스터에 없음')]
N['C03_kkubeurakko_process_3'] = '브랜드 홍보 이미지로 보임("볶고!" 자막). 출처 URL 미기록.'
L['G02_goobne_fryer'] = [
    ('EQ_FRYER', 'clear', ['1B', '1C', '2B', '2C'], 'high', '제품 사진(Rinnai 표기)'),
    ('EQ_WASTE_OIL_CONTAINER', 'clear', ['3B', '3C'], 'medium', '튀김기 하부 배유 통')]
N['G02_goobne_fryer'] = '흰 배경 제품 이미지. 실제 매장 사진 아님.'
L['K01_kyochon_robot'] = [
    ('EQ_COOKING_ROBOT', 'clear', ['1A', '1B', '2A', '2B', '3A'], 'high', '로봇팔(제조사 표기 보임)'),
    ('EQ_FRYER', 'clear', ['2A', '2C', '3B', '3C'], 'high', '여러 대의 튀김 유조')]
L['PotPlayer64_QgHfifs4YE'] = [('EQ_FRYER', 'clear', ['1B', '2A', '2B', '2C', '3A', '3B', '3C'], 'high', '튀김 유조·바스켓')]
N['PotPlayer64_QgHfifs4YE'] = '동영상 플레이어 캡처. "jinny\'s plan" 워터마크. 원 영상 ID 미확인. P11·P12와 같은 장면일 가능성(미확인).'
L['PotPlayer64_VW1iKQ5C4k'] = [('EQ_FRYER', 'clear', ['2A', '2B', '2C', '3A', '3B', '3C'], 'high', '튀김기 3대, 위에서 본 장면')]
N['PotPlayer64_VW1iKQ5C4k'] = '동영상 플레이어 캡처. 워크맨 워터마크. 원 영상 ID 미확인.'
L['_fAwR9CFoyI_0121'] = [
    ('EQ_FRYER', 'partial', ['3B', '3C'], 'medium', '튀김 유조 일부, 저해상도'),
    ('EQ_MICROWAVE', 'partial', ['1B', '1C'], 'medium', '선반 위 전자레인지로 보임'),
    ('EQ_SHELF', 'partial', ['1B', '2B'], 'medium', '스테인리스 선반')]
N['_fAwR9CFoyI_0121'] = '저해상도(455x251). BBQ 로고 워터마크. 근로자 노출(마스크 착용).'
L['bbq_inspection_2023'] = [
    ('EQ_OVEN', 'clear', ['2A', '2B'], 'high', 'BAKERTOP 표기 콤비오븐'),
    ('EQ_FRYER', 'clear', ['3A'], 'high', '튀김 바스켓과 유조'),
    ('EQ_EXHAUST_HOOD', 'clear', ['1A', '1B'], 'high', '상부 후드·필터'),
    ('EQ_SHELF', 'partial', ['1C', '2C'], 'medium', '우측 벽 선반')]
N['bbq_inspection_2023'] = '언론 사진. 점검자·근로자 얼굴이 식별 가능.'
L['brave_ZcRVMActFC'] = [
    ('EQ_SINK', 'clear', ['1C', '2C'], 'high', '세척대와 수전'),
    ('EQ_GAS_CYLINDER', 'clear', ['3C'], 'high', '부탄캔'),
    ('EQ_CART', 'partial', ['2C', '3C'], 'medium', '우측 바퀴 달린 랙')]
U['brave_ZcRVMActFC'] = [('EQ_FRYER', ['2A', '3A'], '좌측 루버형 가스 조리기기. 튀김기 또는 그릴로 추정, 판독 불가'),
                         ('EQ_GRILL', ['2A'], '위에 쌓인 석쇠. 기기 본체인지 도구인지 불명')]
N['brave_ZcRVMActFC'] = '브라우저 캡처. 출처 미기록. 인물 얼굴 흐림 처리됨. 위생 불량 장면 보도 이미지로 추정.'
L['brave_uFFOgcRwoD'] = [
    ('EQ_SHELF', 'partial', ['1B'], 'medium', '안쪽 벽 선반'),
    ('EQ_GAS_CYLINDER', 'partial', ['2B'], 'medium', '부탄캔'),
    ('EQ_SINK', 'partial', ['1B'], 'medium', '안쪽 세척대')]
U['brave_uFFOgcRwoD'] = [('EQ_OVEN', ['1A', '2A'], '좌측 대형 스테인리스 조리기기. 오븐·그리들 추정'),
                         ('EQ_GAS_RANGE', ['2A', '2B'], '제어 손잡이가 있는 조리기기. 레인지·그리들 추정'),
                         (None, ['1C', '2C'], '우측 흰색 기기. 용도 판독 불가')]
N['brave_uFFOgcRwoD'] = 'brave_ZcRVMActFC와 같은 주방의 다른 각도. 인물 흐림 처리됨.'
L['dongdaemun_bhc_1'] = [
    ('EQ_FRYER', 'clear', ['3A', '3B', '3C'], 'high', 'Rinnai 튀김기 여러 대'),
    ('EQ_EXHAUST_HOOD', 'clear', ['1A', '1B', '1C'], 'high', '상부 후드')]
L['dongdaemun_bhc_3'] = [
    ('EQ_REFRIGERATOR', 'clear', ['1A', '2A'], 'high', '좌측 업소용 냉장고'),
    ('EQ_DISPLAY_COOLER', 'clear', ['2A'], 'high', '음료 쇼케이스(유리문)'),
    ('EQ_MICROWAVE', 'clear', ['3B'], 'high', '카운터 아래 전자레인지'),
    ('EQ_EXHAUST_HOOD', 'clear', ['1C'], 'high', '우측 상부 후드'),
    ('EQ_SHELF', 'clear', ['1B', '1C', '2C'], 'high', '포장재 적재 선반'),
    ('EQ_FRYER', 'partial', ['3C'], 'medium', '우하단 제어판 있는 기기. 튀김기로 추정')]
U['dongdaemun_bhc_3'] = [(None, ['2C', '3C'], '우측 선반의 검은 팬 달린 기기. 실링기 추정, 판독 불가')]
X['dongdaemun_bhc_3'] = [('선풍기', ['2A'], '마스터 제외 대상'), ('POS·모니터', ['2B', '2C'], '마스터 제외 대상')]
L['nahYjWAkqY8_0015'] = [('EQ_FRYER', 'clear', ['1A', '1B', '2A', '2B', '2C', '3A', '3B'], 'high', '튀김 유조·바스켓')]
N['nahYjWAkqY8_0015'] = '저해상도(455x251). BBQ 로고 워터마크.'
L['seongdong_bbq_haengdang_1'] = [
    ('EQ_SINK', 'clear', ['2B', '3A', '3B', '3C'], 'high', '세척대'),
    ('EQ_SHELF', 'clear', ['1A', '1B'], 'high', '벽 선반(식기 건조대)'),
    ('EQ_DISPLAY_COOLER', 'partial', ['1C', '2C', '3C'], 'medium', '우측 끝 음료 쇼케이스 일부')]
L['seongdong_bbq_haengdang_3'] = [
    ('EQ_FRYER', 'clear', ['3A', '3B', '3C'], 'high', '튀김기와 바스켓'),
    ('EQ_EXHAUST_HOOD', 'clear', ['1B', '1C'], 'high', '상부 후드'),
    ('EQ_GRILL', 'clear', ['2C'], 'medium', '"화상주의" 표지가 있는 상부 가열식 기기. 샐러맨더로 추정, 오븐일 가능성'),
    ('EQ_ELECTRIC_PANEL', 'partial', ['2C'], 'medium', '벽 콘센트')]
L['seongdong_bbq_haengdang_4'] = []
N['seongdong_bbq_haengdang_4'] = '작업대·포장재만 보임. 마스터 기기 없음(음성 예시). 작업대 하부 선반은 EQ_SHELF에서 제외.'
L['seongdong_kyochon_1'] = [
    ('EQ_FRYER', 'clear', ['2A', '2B', '2C', '3A', '3B', '3C'], 'high', 'Rinnai 튀김기 3대 이상'),
    ('EQ_WASTE_OIL_CONTAINER', 'partial', ['3B', '3C'], 'medium', '튀김기 하부 통')]
U['seongdong_kyochon_1'] = [(None, ['3A'], '좌하단 소형 기기. 오일 필터기 추정, 판독 불가')]
L['seongdong_kyochon_3'] = [
    ('EQ_FRYER', 'clear', ['1A', '1B', '1C'], 'high', '뒤쪽 튀김기 줄'),
    ('EQ_RICE_COOKER', 'clear', ['1C'], 'high', '전기밥솥'),
    ('EQ_ELECTRIC_PANEL', 'clear', ['1C'], 'medium', '벽에 걸린 멀티탭')]
U['seongdong_kyochon_3'] = [('EQ_REFRIGERATOR', ['1A', '2A'], '좌측 유리문. 냉장고 추정')]
L['seongdong_kyochon_4'] = [
    ('EQ_FRYER', 'clear', ['2A', '2B', '2C', '3A', '3B', '3C'], 'high', 'Rinnai 튀김기'),
    ('EQ_SHELF', 'partial', ['2B', '2C'], 'medium', '튀김기 위 소형 선반')]
L['seongdong_nene_geumho_1'] = [
    ('EQ_REFRIGERATOR', 'clear', ['3A', '3B', '3C'], 'medium', '뚜껑형 냉장고(김치냉장고·다목적 냉동고)'),
    ('EQ_SHELF', 'clear', ['1A', '1B', '1C'], 'high', '벽 선반'),
    ('EQ_KNIFE_BOARD', 'partial', ['2C', '3C'], 'medium', '나무 도마'),
    ('EQ_EXHAUST_HOOD', 'partial', ['1C'], 'medium', '벽 환풍기'),
    ('EQ_ELECTRIC_PANEL', 'clear', ['1A'], 'medium', '벽 콘센트와 전선'),
    ('EQ_SINK', 'partial', ['3A', '3B'], 'low', '하단 가장자리 세척대 일부')]
L['seongdong_nene_geumho_2'] = [('EQ_FRYER', 'clear', ['2A', '2B', '2C', '3A', '3B', '3C'], 'high', 'Rinnai 튀김기 2대')]
L['seongdong_nene_geumho_3'] = [
    ('EQ_SINK', 'clear', ['2A', '2B', '3A', '3B', '3C'], 'high', '세척대'),
    ('EQ_SCISSORS', 'clear', ['1B'], 'high', '벽에 걸린 가위'),
    ('EQ_REFRIGERATOR', 'clear', ['2C', '3C'], 'medium', '뚜껑형 냉장고')]
L['seongdong_nene_geumho_4'] = [('EQ_GAS_RANGE', 'clear', ['2A', '2B', '2C', '3A', '3B', '3C'], 'high', '2구 가스레인지(Rinnai)')]
L['seongdong_nene_seongsu_1'] = [('EQ_REFRIGERATOR', 'clear', ['1A', '1B', '1C', '2A', '2B', '2C', '3A', '3B', '3C'], 'high', '4도어 업소용 냉장고, 냉장실·냉동실 표기')]
N['seongdong_nene_seongsu_1'] = '원본 EXIF 방향 6(90도 회전). 격자는 회전 적용 후 기준.'
L['seongdong_nene_seongsu_3'] = [
    ('EQ_GAS_RANGE', 'clear', ['3B', '3C'], 'high', '2구 가스테이블(Rinnai)'),
    ('EQ_SHELF', 'clear', ['1A', '1B', '1C'], 'high', '벽 선반'),
    ('EQ_SCISSORS', 'clear', ['2A', '2B', '2C'], 'high', '벽에 걸린 가위 여러 개'),
    ('EQ_VEG_CUTTER', 'clear', ['2B'], 'medium', '수동 채칼'),
    ('EQ_KNIFE_BOARD', 'clear', ['2B'], 'medium', '보라색 도마'),
    ('EQ_SINK', 'clear', ['3A'], 'high', '세척대')]
L['seongdong_nene_seongsu_4'] = [('EQ_FRYER', 'clear', ['2A', '3A', '2C', '3C'], 'high', '좌우 Rinnai 튀김기')]
U['seongdong_nene_seongsu_4'] = [('EQ_EXHAUST_HOOD', ['1C'], '우상단 녹슨 함체. 후드·덕트 추정')]
L['zT1kAueZC7k_0019'] = [('EQ_GAS_RANGE', 'clear', ['3A', '3B', '3C'], 'high', '가스 화구와 웍, 불꽃 보임')]
N['zT1kAueZC7k_0019'] = '홍보 영상 프레임(PURADAK CHICKEN 워터마크). 같은 이름 zip은 실제사진 폴더 전체 백업으로 보임(35개 항목).'


def grid_bbox(cells):
    xs, ys = [], []
    for c in cells:
        r, col = int(c[0]) - 1, 'ABC'.index(c[1])
        xs += [col / 3, (col + 1) / 3]
        ys += [r / 3, (r + 1) / 3]
    return [round(min(xs), 4), round(min(ys), 4), round(max(xs), 4), round(max(ys), 4)]


def source_info(stem, meta):
    s = {'origin_type': '미확인', 'video_id': None, 'video_time_s': None, 'channel_or_brand_observed': None,
         'page_url': None, 'image_url': None, 'store': None, 'retrieved_date_kst': None, 'url_status': '미기록'}
    if stem in meta:
        m = meta[stem]
        s.update(origin_type='지자체·언론 게시물 이미지', page_url=m.get('page_url'), image_url=m.get('image_url'),
                 store=m.get('store'), retrieved_date_kst=m.get('retrieved_date_kst'),
                 url_status='261113_공개주방_이동파일목록_DR.json에 기록됨')
        return s
    parts = stem.split('_')
    if stem.startswith('261113_P'):
        s.update(origin_type='유튜브 영상 프레임(파일명 기준)', video_id=parts[2], video_time_s=float(parts[3].rstrip('s')),
                 url_status='파일명에서 재구성. 실제 접속 확인 안 함')
        s['page_url'] = f"https://www.youtube.com/watch?v={parts[2]}&t={int(float(parts[3].rstrip('s')))}s"
    elif stem.startswith(('_fAwR9CFoyI', 'nahYjWAkqY8', 'zT1kAueZC7k')):
        vid = stem[:11]
        s.update(origin_type='유튜브 영상 프레임(파일명 기준)', video_id=vid,
                 url_status='파일명에서 재구성. 뒤 숫자(' + stem[12:] + ')가 초인지 프레임 번호인지 미확인')
        s['page_url'] = f'https://www.youtube.com/watch?v={vid}'
    elif stem.startswith('PotPlayer64_'):
        s.update(origin_type='동영상 플레이어 캡처(원 영상 미확인)')
    elif stem.startswith('brave_'):
        s.update(origin_type='브라우저 캡처(원 페이지 미확인)')
    elif stem[:3] in ('C02', 'C03', 'G02', 'K01'):
        s.update(origin_type='브랜드 홍보·제품 이미지로 추정(원 페이지 미확인)')
    return s


WATERMARK = {'261113_P01': '워크맨', '261113_P04': '워크맨', '261113_P06': '워크맨', '261113_P07': '워크맨', '261113_P09': '워크맨',
             'PotPlayer64_VW1i': '워크맨', 'PotPlayer64_QgHf': "jinny's plan", '_fAwR9CFoyI': 'BBQ 로고', 'nahYjWAkqY8': 'BBQ 로고',
             'zT1kAueZC7k': 'PURADAK CHICKEN', 'C02_kkubeurakko': '꾸브라꼬(파일명)', 'C03_kkubeurakko': '꾸브라꼬(파일명)',
             'G02_goobne': '굽네(파일명), Rinnai 제품', 'K01_kyochon': '교촌(파일명)'}
PERSON = {'261113_P01_bApoYZBPCLE_0148.00s_DR': '얼굴 일부 노출', '261113_P06_gkMLRGZIHsc_0311.00s_DR': '얼굴 노출',
          '261113_P09_gkMLRGZIHsc_0414.00s_DR': '얼굴 옆모습 노출', '_fAwR9CFoyI_0121': '얼굴 일부 노출(저해상도)',
          'bbq_inspection_2023': '얼굴 식별 가능', 'brave_ZcRVMActFC': '인물 흐림 처리됨', 'brave_uFFOgcRwoD': '인물 흐림 처리됨',
          '261113_P11_TCdTyi29FJA_0095.90s_DR': '손·몸통만', '261113_P12_TCdTyi29FJA_0103.00s_DR': '손만', 'PotPlayer64_QgHfifs4YE': '손만',
          'PotPlayer64_VW1iKQ5C4k': '손만', 'nahYjWAkqY8_0015': '없음', 'zT1kAueZC7k_0019': '손만', 'C02_kkubeurakko_process_2': '팔만',
          'K01_kyochon_robot': '없음', '261113_P04_bApoYZBPCLE_0513.00s_DR': '없음', '261113_P07_gkMLRGZIHsc_0314.00s_DR': '장갑 낀 손만'}
GROUP = [('261113_P01', 'yt_bApoYZBPCLE'), ('261113_P04', 'yt_bApoYZBPCLE'), ('261113_P0', 'yt_gkMLRGZIHsc'),
         ('261113_P1', 'yt_TCdTyi29FJA'), ('PotPlayer64_QgHf', 'video_unknown_jinnysplan'), ('PotPlayer64_VW1i', 'video_unknown_workman'),
         ('_fAwR9CFoyI', 'yt__fAwR9CFoyI'), ('nahYjWAkqY8', 'yt_nahYjWAkqY8'), ('zT1kAueZC7k', 'yt_zT1kAueZC7k'),
         ('C0', 'brand_kkubeurakko'), ('G02', 'brand_goobne_product'), ('K01', 'brand_kyochon_robot'), ('brave_', 'web_capture_same_kitchen'),
         ('dongdaemun_bhc', 'store_bhc_hwigyeong'), ('seongdong_bbq_haengdang', 'store_bbq_haengdang'), ('seongdong_kyochon', 'store_kyochon_yongdap'),
         ('seongdong_nene_geumho', 'store_nene_geumho'), ('seongdong_nene_seongsu', 'store_nene_seongsu'), ('bbq_inspection', 'news_bbq_inspection')]


def main():
    master = json.load(open(os.path.join(OUT, '261115_기기마스터_v1_DR.json'), encoding='utf-8'))
    ids = {e['equipment_id'] for e in master['equipment']}
    meta_list = json.load(open(os.path.join(PHOTO_DIR, '261113_공개주방_이동파일목록_DR.json'), encoding='utf-8'))
    meta = {os.path.splitext(os.path.basename(m['file'].replace('\\', '/')))[0]: m for m in meta_list}
    files = sorted(f for f in os.listdir(PHOTO_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg')))
    images, rows = [], []
    for fn in files:
        stem = os.path.splitext(fn)[0]
        p = os.path.join(PHOTO_DIR, fn)
        b = open(p, 'rb').read()
        im = Image.open(p)
        exif_o = im.getexif().get(274)
        w0, h0 = im.size
        dw, dh = ImageOps.exif_transpose(im).size
        labels = []
        for i, (eid, vis, grid, conf, note) in enumerate(L[stem], 1):
            assert eid in ids, (stem, eid)
            labels.append({'label_id': f'{stem}#L{i:02d}', 'equipment_id': eid, 'visibility': vis, 'region_grid': grid,
                           'bbox_norm_from_grid': grid_bbox(grid), 'label_confidence': conf, 'note': note})
            rows.append([stem, fn, f'{stem}#L{i:02d}', eid, vis, ' '.join(grid), conf, note])
        group = next(g for pre, g in GROUP if stem.startswith(pre))
        wm = next((v for k, v in WATERMARK.items() if stem.startswith(k)), None)
        src = source_info(stem, meta)
        src['channel_or_brand_observed'] = wm
        images.append({
            'image_id': stem, 'file': f'실제사진/{fn}', 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b),
            'width': w0, 'height': h0, 'exif_orientation': exif_o, 'display_width': dw, 'display_height': dh,
            'scene_group': group, 'source': src,
            'rights': {'sharing_status': '공유 권한 미확인', 'training_use': '학습·평가 사용 권한 미확인',
                       'person_visibility': PERSON.get(stem, '없음'),
                       'store_or_brand_identifiable': bool(src.get('store') or wm),
                       'check_needed': '원 게시자 이용조건 확인, 인물·상호 노출 시 비식별 또는 사용 제외 판단'},
            'label_status': LABEL_STATUS, 'labeler': 'Claude(AI 보조)', 'labeled_date_kst': '2026-11-16',
            'is_negative': len(labels) == 0,
            'labels': labels,
            'uncertain_candidates': [{'candidate_equipment_id': c, 'region_grid': g, 'reason': t} for c, g, t in U.get(stem, [])],
            'not_in_master': [{'name': n, 'region_grid': g, 'note': t} for n, g, t in X.get(stem, [])],
            'note': N.get(stem, ''),
        })
    assert set(L) == {os.path.splitext(f)[0] for f in files}, set(L) ^ {os.path.splitext(f)[0] for f in files}
    ev = {
        'name': 'Safe-T 사진 기기 인식 평가셋', 'version': 'v1-draft', 'created_date_kst': '2026-11-16',
        'label_status': LABEL_STATUS, 'master': '261115_기기마스터_v1_DR.json', 'master_version': master['version'],
        'photo_dir': '실제사진/ (원본 수정 없음)',
        'label_unit': '이미지 단위 기기 존재(멀티라벨). 영역은 3x3 격자 근사.',
        'grid_rule': 'EXIF 회전 적용 화면 기준. 행 1-3 위→아래, 열 A-C 왼쪽→오른쪽. bbox_norm_from_grid = [x0, y0, x1, y1] (0-1).',
        'visibility_values': {'clear': '기기 종류를 판단할 만큼 보임', 'partial': '일부만 보이거나 작음'},
        'label_confidence_values': {'high': '라벨러 확신', 'medium': '추정 포함', 'low': '판독 어려움'},
        'scoring_guidance': '평가 기본은 clear 라벨. partial·uncertain은 별도 집계. 같은 scene_group 사진은 서로 독립 표본이 아니다.',
        'not_for_training': '권한 미확인. 모델 학습에 쓰지 않는다.',
        'images': images,
    }
    with open(os.path.join(OUT, '261115_기기인식_평가셋_v1_DR.json'), 'w', encoding='utf-8') as f:
        json.dump(ev, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT, '261115_기기인식_평가셋_라벨_v1_DR.csv'), 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.writer(f)
        w.writerow(['image_id', 'file', 'label_id', 'equipment_id', 'visibility', 'region_grid', 'label_confidence', 'note'])
        w.writerows(rows)
    print('images', len(images), 'labels', len(rows), 'negative', sum(i['is_negative'] for i in images))


if __name__ == '__main__':
    main()
