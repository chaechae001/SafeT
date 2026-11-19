CREATE TABLE IF NOT EXISTS risk_equipment_evidence (
    equipment_id VARCHAR(60) NOT NULL,
    candidate_id VARCHAR(60) NOT NULL,
    scenario_id VARCHAR(60) NULL,
    hazard_tag VARCHAR(30) NOT NULL,
    hazard VARCHAR(255) NOT NULL,
    evidence_id VARCHAR(100) NOT NULL,
    document_id VARCHAR(30) NOT NULL,
    pdf_page INT NOT NULL,
    locator VARCHAR(80) NOT NULL,
    evidence_summary VARCHAR(500) NOT NULL,
    PRIMARY KEY (equipment_id, candidate_id, evidence_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO risk_equipment_evidence
    (equipment_id, candidate_id, scenario_id, hazard_tag, hazard, evidence_id, document_id, pdf_page, locator, evidence_summary)
VALUES
    ('EQ_FRYER', 'FRY', 'FRY', 'burn', '고온 기름이 튀어 화상',
     'N02-p012-4.5-risk-b', 'N02', 12, '4.5 (1) (나)', '기름탱크의 물기가 고온 기름을 튀게 해 화상을 일으킬 수 있다.'),
    ('EQ_FRYER', 'FRY_CONTACT', NULL, 'burn', '가열된 튀김기 외부와 접촉해 화상',
     'N02-p012-4.5-risk-d', 'N02', 12, '4.5 (1) (라)', '조리 상태를 확인하다 가열된 튀김기 외부에 몸이 닿으면 화상을 입을 수 있다.'),
    ('EQ_FRYER', 'FIRE', 'FIRE', 'fire', '튀김기 과열로 식용유에 불이 붙어 화재',
     'N02-p012-4.5-risk-f', 'N02', 12, '4.5 (1) (바)', '튀김기를 고온에서 장시간 사용하면 과열로 화재가 발생할 수 있다.'),
    ('EQ_FRYER', 'FIRE', 'FIRE', 'fire', '튀김기 과열로 식용유에 불이 붙어 화재',
     'kras:card-v1:case:FOOD-04-C1', 'D5', 64, '인쇄 56쪽 사고사례', '조리 중 식용유가 착화해 화재가 발생한 사례다.')
ON DUPLICATE KEY UPDATE evidence_id = VALUES(evidence_id);
