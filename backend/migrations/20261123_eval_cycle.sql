-- UX-024 (2026-11-23): 평가 주기. 내 평가표 카드 제목을 '26년 [상반기|하반기] 사업장명'으로 보이기 위한 값.
-- Y 연간 · H1 상반기 · H2 하반기 · NULL 미지정(예전 평가표, 카드 제목은 '연도 + 사업장명').
-- 평가일 월로 자동 분류하지 않는다(3월에 작성한 연간 평가가 상반기가 되면 안 됨). 저장된 eval_nm·사업장명은 바꾸지 않는다.
ALTER TABLE eval_mst ADD COLUMN IF NOT EXISTS eval_cycle VARCHAR(2) NULL;
