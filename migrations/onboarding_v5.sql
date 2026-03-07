-- ═══════════════════════════════════════════════════════════════════════
-- Onboarding v5 migration
-- Run in Supabase Dashboard → SQL Editor
-- ═══════════════════════════════════════════════════════════════════════

-- ── pets table: new columns ──────────────────────────────────────────
ALTER TABLE pets ADD COLUMN IF NOT EXISTS gender TEXT;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS neutered BOOLEAN;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS age_years FLOAT;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS onboarding_step TEXT;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS optional_gate_passed BOOLEAN DEFAULT FALSE;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS avatar_url TEXT;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS birth_date_skipped BOOLEAN DEFAULT FALSE;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS neutered_skipped BOOLEAN DEFAULT FALSE;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS photo_avatar_skipped BOOLEAN DEFAULT FALSE;

-- ── pets table: fix _skipped column name mismatch ────────────────────
-- Code writes chip_id_skipped / stamp_id_skipped,
-- but old migration created chip_skipped / stamp_skipped.
-- Rename if old names exist:
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'pets' AND column_name = 'chip_skipped'
  ) THEN
    ALTER TABLE pets RENAME COLUMN chip_skipped TO chip_id_skipped;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'pets' AND column_name = 'stamp_skipped'
  ) THEN
    ALTER TABLE pets RENAME COLUMN stamp_skipped TO stamp_id_skipped;
  END IF;
END $$;

-- If they never existed under old names, create with correct names:
ALTER TABLE pets ADD COLUMN IF NOT EXISTS chip_id_skipped BOOLEAN DEFAULT FALSE;
ALTER TABLE pets ADD COLUMN IF NOT EXISTS stamp_id_skipped BOOLEAN DEFAULT FALSE;

-- ── users table: new columns ─────────────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS pet_count INT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_onboarded BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_stage INT DEFAULT 1;

-- ── pet_documents table ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pet_documents (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  pet_id UUID NOT NULL REFERENCES pets(id) ON DELETE CASCADE,
  doc_type TEXT NOT NULL,
  extracted_data JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(pet_id, doc_type)
);

-- ── Verify ───────────────────────────────────────────────────────────
-- Run this after to confirm:
-- SELECT column_name, data_type FROM information_schema.columns
-- WHERE table_name IN ('pets', 'users', 'pet_documents')
-- ORDER BY table_name, ordinal_position;
