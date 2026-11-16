-- Existing evaluation data stays intact. JSON stores facts, questions, provenance and policy version.
ALTER TABLE eval_mst ADD COLUMN IF NOT EXISTS risk_state LONGTEXT NULL;
