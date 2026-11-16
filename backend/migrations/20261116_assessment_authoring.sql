-- ERD V1.1 유지: 중복 생성 방지, 동시 저장 충돌 감지, 합성/실제 출처 구분만 추가.
-- 적용 전 백업. 기존 데이터 변경/삭제 없음. MariaDB 10.5+.
ALTER TABLE eval_mst ADD COLUMN IF NOT EXISTS request_key varchar(36) NULL;
ALTER TABLE eval_mst ADD COLUMN IF NOT EXISTS revision int NOT NULL DEFAULT 1;
ALTER TABLE eval_mst ADD COLUMN IF NOT EXISTS generation_source varchar(30) NOT NULL DEFAULT 'unavailable';
CREATE UNIQUE INDEX IF NOT EXISTS uq_eval_request ON eval_mst (email, request_key);
