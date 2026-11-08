from sqlalchemy import text
from load_facilities import engine

DDL = """
CREATE TABLE IF NOT EXISTS ai_cache (
    key TEXT PRIMARY KEY,
    response JSONB NOT NULL,
    model TEXT, tokens INT, latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_assessments (
    id SERIAL PRIMARY KEY,
    incident_id INT NOT NULL REFERENCES incidents(id),
    source TEXT NOT NULL,                       -- 'llm' or 'rules'
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL,
    injuries INT,
    trapped BOOLEAN,
    location_clues JSONB NOT NULL DEFAULT '[]',
    reasoning TEXT,
    floor_applied BOOLEAN NOT NULL DEFAULT FALSE,
    rule_category TEXT, rule_severity TEXT,     -- baseline output, kept for experiments
    provider TEXT, model TEXT, tokens INT, latency_ms INT,
    cached BOOLEAN NOT NULL DEFAULT FALSE,
    error TEXT,
    duplicates JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ai_assessments_incident ON ai_assessments (incident_id, id DESC);

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS category_confirmed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS duplicate_of INT REFERENCES incidents(id);
UPDATE incidents SET category_confirmed = TRUE WHERE category IS NOT NULL;
"""

with engine.begin() as conn:
    conn.execute(text(DDL))
print("AI tables ready")