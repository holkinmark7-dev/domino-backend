# Domino Pets Backend — Project Status

## 1. File Inventory

### routers/

| File | Description |
|------|-------------|
| `chat.py` | Main clinical chat API — triage orchestrator: symptom extraction, clinical decision, escalation, episode management, AI response |
| `pets.py` | Pet CRUD — creation endpoint |
| `timeline.py` | Timeline API — monthly/daily views, recalculation, filtering by event type |
| `vet_report.py` | Vet report — JSON aggregation + PDF export over episodes |
| `chat_history.py` | Chat history — chronological messages enriched with triage data |

### routers/services/

| File | Description |
|------|-------------|
| `ai.py` | OpenAI GPT-4o-mini integration — system prompt building, deterministic templates, event extraction |
| `clinical_engine.py` | Clinical decision builder — symptom stats, escalation evaluation (frozen baseline) |
| `risk_engine.py` | Risk engine v1 — score-to-escalation mapping (frozen) |
| `episode_manager.py` | Episode lifecycle — creation, updates, resolution, escalation tracking |
| `memory.py` | DB abstraction — event saving, medical events, pet profile retrieval |
| `response_templates.py` | Deterministic template selector by response_type + phase prefixes |
| `symptom_registry.py` | Symptom registry — 37 symptoms across 8 classes, normalization |
| `symptom_class_registry.py` | Symptom-to-class mapper (GI, RESPIRATORY, INGESTION, TOXIC, URINARY, NEURO, OCULAR, TRAUMA) |
| `recurrence.py` | Recurrence detection — 3+ resolved episodes for same key within 30 days |
| `episode_phase.py` | Episode phase display — initial/ongoing/prolonged by duration (no escalation effect) |
| `__init__.py` | Empty package init |

### tests/

| File | Tests | Description |
|------|-------|-------------|
| `test_anti_redundancy.py` | 5 | Anti-redundancy guard in ai.py |
| `test_stress_scenarios.py` | 20 | S01-S20 stress scenarios, all symptom classes |
| `test_routing_modes.py` | 18 | 3-mode AI routing (CASUAL/PROFILE/CLINICAL) |
| `test_timeline.py` | 8 | Timeline month/day/recalculate |
| `test_timeline_day20.py` | 5 | Timeline filter endpoint |
| `test_clinical_stress_matrix.py` | 12 | 12-scenario multi-layer triage pipeline |
| `test_clinical_engine_snapshot_v1.py` | 6 | v1.0.0 snapshot freeze (5 scenarios + version tag) |
| `test_risk_engine_v1.py` | 2 | Score-to-escalation mapping + monotonicity |

### Root-level test files

| File | Tests | Description |
|------|-------|-------------|
| `test_llm_contract.py` | 65 | LLM contract validation |
| `test_response_templates.py` | 37 | Template selection by response_type |
| `test_symptom_registry_sync.py` | 22 | Symptom registry consistency |
| `test_episode_engine.py` | 21 | Episode manager lifecycle |
| `test_timeline.py` | 20 | Timeline API (old interface) |
| `test_episode_phase.py` | 16 | Episode phase display thresholds |
| `test_recurrence.py` | 13 | Recurrence detection logic |
| `test_action_block_fix.py` | 13 | Action block fix validation |
| `test_phase_aware_tone.py` | 12 | Phase-aware tone in AI responses |
| `test_vet_report.py` | 12 | Vet report JSON endpoint |
| `test_ai_prompt_fix.py` | 11 | AI prompt construction fixes |
| `test_chat_history.py` | 11 | Chat history endpoint |
| `test_critical_fixes.py` | 11 | Critical bug fixes regression |
| `test_vet_report_pdf.py` | 10 | Vet report PDF export |
| `test_monotonic_lock.py` | 9 | Monotonic escalation lock |
| `test_api_fixes.py` | 9 | API-level fixes |
| `test_chat_fixes.py` | 9 | Chat pipeline fixes |
| `test_dialogue_tone.py` | 8 | Dialogue tone calibration |
| `test_episode_phase_v1.py` | 8 | Episode phase v1 logic |
| `test_phase_followup_engine.py` | 6 | Follow-up engine phase logic |
| `test_risk_calibration.py` | 10 | Risk calibration S1-S10 |
| `test_triage_v44.py` | 24 | Triage v4.4 (14 required + 10 sanity) |
| `test_medical_core.py` | 3 | Medical core integration |
| `test_cross_symptom.py` | 3 | Cross-symptom override |

**Total: ~405 test methods across 32 files**

---

## 2. All Endpoints

| Method | Path | Function | File |
|--------|------|----------|------|
| GET | `/health` | `health` | `main.py` |
| POST | `/pets` | `create_pet` | `routers/pets.py` |
| POST | `/chat` | `create_chat_message` | `routers/chat.py` |
| GET | `/events/{pet_id}` | `get_events` | `routers/chat.py` |
| GET | `/medical-events/{pet_id}` | `get_medical_events_endpoint` | `routers/chat.py` |
| POST | `/migrate-user` | `migrate_user` | `routers/chat.py` |
| GET | `/api/timeline/{pet_id}` | `get_timeline_month` | `routers/timeline.py` |
| GET | `/api/timeline/{pet_id}/day` | `get_timeline_day` | `routers/timeline.py` |
| POST | `/api/timeline/{pet_id}/recalculate` | `recalculate_day_endpoint` | `routers/timeline.py` |
| GET | `/api/timeline/{pet_id}/filter` | `get_timeline_filtered` | `routers/timeline.py` |
| GET | `/vet-report/{pet_id}` | `get_vet_report` | `routers/vet_report.py` |
| GET | `/vet-report/{pet_id}/pdf` | `get_vet_report_pdf` | `routers/vet_report.py` |
| GET | `/chat/history/{pet_id}` | `get_chat_history` | `routers/chat_history.py` |

Note: Timeline router mounted with `prefix="/api"`.

---

## 3. Supabase Tables

| Table | Used In |
|-------|---------|
| `chat` | `chat.py`, `chat_history.py` |
| `events` | `chat.py`, `chat_history.py`, `timeline.py`, `services/memory.py` |
| `episodes` | `chat.py`, `timeline.py`, `vet_report.py`, `services/episode_manager.py`, `services/recurrence.py` |
| `pets` | `chat.py`, `pets.py`, `vet_report.py`, `services/memory.py` |
| `timeline_days` | `timeline.py` |

**5 tables total.**

---

## 4. Module Import Graph

```
main.py
  <- routers/pets.py
  <- routers/chat.py
  <- routers/timeline.py
  <- routers/vet_report.py
  <- routers/chat_history.py

routers/chat.py
  <- services/memory        (save_event, save_medical_event, get_recent_events, get_pet_profile, get_medical_events)
  <- services/ai            (generate_ai_response, extract_event_data)
  <- services/symptom_registry      (normalize_symptom)
  <- services/symptom_class_registry (get_symptom_class)
  <- services/clinical_engine       (get_symptom_stats, build_clinical_decision, apply_cross_symptom_override)
  <- services/risk_engine           (calculate_risk_score, ESCALATION_ORDER)
  <- services/episode_manager       (process_event, update_episode_escalation)
  <- services/recurrence            (check_recurrence)
  <- services/episode_phase         (compute_episode_phase)
  <- routers/timeline               (recalculate_day) [lazy import in try/except]

routers/vet_report.py
  <- services/risk_engine   (ESCALATION_ORDER)

routers/services/ai.py
  <- services/response_templates (select_template, get_phase_prefix)

routers/services/clinical_engine.py
  <- services/memory         (get_medical_events)

routers/timeline.py          — no internal imports
routers/pets.py              — no internal imports
routers/chat_history.py      — no internal imports
routers/services/memory.py   — no internal imports
routers/services/risk_engine.py        — no internal imports
routers/services/episode_manager.py    — no internal imports
routers/services/response_templates.py — no internal imports
routers/services/symptom_registry.py   — no internal imports
routers/services/symptom_class_registry.py — no internal imports
routers/services/recurrence.py         — no internal imports
routers/services/episode_phase.py      — no internal imports
```
