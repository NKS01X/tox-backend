-- Run this in Supabase Dashboard → SQL Editor
-- Creates the predictions table for the tox-detector service.

CREATE TABLE IF NOT EXISTS predictions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  status          TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
  smiles_input    TEXT NOT NULL,
  tox_score       NUMERIC,
  tox_class       TEXT,
  llm_explanation TEXT,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
