CREATE TABLE IF NOT EXISTS risk_card (
    evidence_id VARCHAR(120) NOT NULL PRIMARY KEY,
    card_id VARCHAR(60) NOT NULL,
    kind ENUM('case', 'checklist', 'reference') NOT NULL,
    title VARCHAR(255) NOT NULL,
    source_code VARCHAR(60) NOT NULL,
    source_page SMALLINT UNSIGNED NOT NULL,
    review_status ENUM('pending', 'verified') NOT NULL DEFAULT 'pending',
    card_data JSON NOT NULL,
    hazard_tags JSON NOT NULL,
    unresolved_scenario_refs JSON NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS risk_card_equipment (
    equipment_id VARCHAR(60) NOT NULL,
    evidence_id VARCHAR(120) NOT NULL,
    PRIMARY KEY (equipment_id, evidence_id),
    FOREIGN KEY (evidence_id) REFERENCES risk_card (evidence_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS risk_card_scenario (
    scenario_id VARCHAR(60) NOT NULL,
    evidence_id VARCHAR(120) NOT NULL,
    PRIMARY KEY (scenario_id, evidence_id),
    FOREIGN KEY (evidence_id) REFERENCES risk_card (evidence_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
