-- ═══════════════════════════════════════════════════════════════════════
-- Enable Row Level Security on all tables
-- Date: 2026-03-11
-- Apply: Supabase Dashboard → SQL Editor → Run
--        OR: supabase db push
-- ═══════════════════════════════════════════════════════════════════════


-- ── Tables with direct user_id ───────────────────────────────────────

-- USERS
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users_own_row" ON public.users
  FOR ALL
  USING (id = auth.uid())
  WITH CHECK (id = auth.uid());

-- PETS
ALTER TABLE public.pets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pets_own_rows" ON public.pets
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- CHAT
ALTER TABLE public.chat ENABLE ROW LEVEL SECURITY;

CREATE POLICY "chat_own_rows" ON public.chat
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());

-- EVENTS
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "events_own_rows" ON public.events
  FOR ALL
  USING (user_id = auth.uid())
  WITH CHECK (user_id = auth.uid());


-- ── Tables via pet_id → pets.user_id ─────────────────────────────────

-- PET_MEDICAL_PROFILE
ALTER TABLE public.pet_medical_profile ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pet_medical_profile_own_rows" ON public.pet_medical_profile
  FOR ALL
  USING (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  )
  WITH CHECK (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  );

-- PET_DOCUMENTS
ALTER TABLE public.pet_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pet_documents_own_rows" ON public.pet_documents
  FOR ALL
  USING (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  )
  WITH CHECK (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  );

-- PET_VACCINES
ALTER TABLE public.pet_vaccines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "pet_vaccines_own_rows" ON public.pet_vaccines
  FOR ALL
  USING (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  )
  WITH CHECK (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  );

-- TIMELINE_DAYS
ALTER TABLE public.timeline_days ENABLE ROW LEVEL SECURITY;

CREATE POLICY "timeline_days_own_rows" ON public.timeline_days
  FOR ALL
  USING (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  )
  WITH CHECK (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  );

-- EPISODES
ALTER TABLE public.episodes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "episodes_own_rows" ON public.episodes
  FOR ALL
  USING (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  )
  WITH CHECK (
    pet_id IN (
      SELECT id FROM public.pets WHERE user_id = auth.uid()
    )
  );
