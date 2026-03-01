# Clinical Engine v1.0.0 — Freeze Document

**Status:** FROZEN
**Version:** `v1.0.0-FROZEN`
**Frozen on:** 2026-02-27
**Scope:** `routers/chat.py`, `routers/services/clinical_engine.py`, `routers/services/risk_engine.py`

> Any change to triage logic, escalation rules, or phase engine requires a version bump
> and a new snapshot test baseline. This document is the single source of truth for v1.

---

## A. Escalation Model

Escalation is represented as a string label with a strict numeric order:

| Label      | Integer index | Meaning                              |
|------------|--------------|--------------------------------------|
| `LOW`      | 0            | Monitor at home                      |
| `MODERATE` | 1            | Contact vet if symptoms persist      |
| `HIGH`     | 2            | Urgent veterinary attention required |
| `CRITICAL` | 3            | Emergency — immediate vet visit      |

Mapping is defined in `routers/services/risk_engine.py`:

```python
ESCALATION_ORDER = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
```

Helper `escalate_min(current, target)` ensures monotonic promotion:
it raises `current` to `target` only if `target` is higher; never lowers.

---

## B. Layer Order (Official — v1)

The triage pipeline in `routers/chat.py → create_chat_message` applies layers
in this fixed sequence. **Do not reorder.**

| # | Layer | Key function / block |
|---|-------|----------------------|
| 1 | **Clinical Routing** | GI / RESPIRATORY / INGESTION / TOXIC / NEURO / URINARY routing blocks |
| 2 | **Blood Type Override** | `melena`, `coffee_ground_vomit` → min CRITICAL |
| 3 | **GDV Override** | keyword-based `gdv_flag` → CRITICAL |
| 4 | **Absolute Critical & Vital Signs** | temp ≥ 41, temp ≥ 40 + lethargy, resp\_rate ≥ 50 → CRITICAL; resp\_rate ≥ 40 → HIGH |
| 5 | **Systemic State** | lethargy model, refusing\_water, temperature, temp+lethargy combined |
| 6 | **Species & Age Multipliers** | cat+RESP→HIGH, cat+diff\_breathing+lethargy→CRITICAL, puppy<1y+GI+1, juvenile<0.5y+GI+lethargy→CRITICAL, senior≥10+systemic+1 |
| 7 | **Episode Clinical** | GI duration (species-aware), recurrence |
| 8 | **Cat Anorexia Override** | cat+anorexia+24h→HIGH; +lethargy→CRITICAL |
| 9 | **Cross-Class Override** | seizure+vomit, foreign\_body+vomit, collapse, NEURO+toxic → CRITICAL |
| 10 | **Monotonic Lock** | `apply_monotonic_lock()` — escalation never drops within episode |
| 11 | **Episode Phase Engine** | `compute_episode_phase_v1()` — trajectory label, never mutates escalation |

### Layer notes

- **Layer 5 (Systemic State)** is **skipped** for RESPIRATORY symptom class
  (lethargy is already baked into RESPIRATORY routing at Layer 1).
- **Layer 10 (Monotonic Lock)** reads previous urgency\_score from `events` table;
  it can only raise escalation, never lower it.
- **Layer 11 (Episode Phase)** is a pure annotation — it adds
  `decision["episode_phase"]` but has zero influence on escalation.

---

## C. Invariants

These invariants must hold at all times. If a test violates them,
the change must be reverted, not the test.

| # | Invariant |
|---|-----------|
| I1 | Escalation within an episode is **monotonically non-decreasing** (Monotonic Lock). |
| I2 | **Absolute Critical** rules (Layer 4) always override lower layers. |
| I3 | `episode_phase` **never influences escalation** — it is read-only metadata for the LLM tone layer. |
| I4 | The LLM (generate\_ai\_response) **never modifies** `risk_level`, `escalation`, or `clinical_decision`. It receives them as input and uses them to shape its response only. |
| I5 | `escalate_min()` is **strictly monotonic** — calling it with any target ≤ current leaves escalation unchanged. |
| I6 | RESPIRATORY lethargy is handled at Layer 1 (routing). The Systemic State layer (Layer 5) **skips lethargy** for RESPIRATORY class to prevent double-escalation. |
| I7 | `compute_episode_phase_v1()` is a **pure function** — it has no side effects and does not read from the database. |

---

## D. Known Aggressions (Intentional High-Escalation Rules)

These rules intentionally produce aggressive (high) escalation outcomes.
They are **by design** and must not be softened without a version bump.

| Rule | Trigger | Result |
|------|---------|--------|
| **Juvenile GI + lethargy/refusing\_water** | age < 0.5y, GI class, lethargy != "none" OR refusing\_water=True | CRITICAL (Layer 6 juvenile override) |
| **GI + refusing\_water** | GI symptom class, refusing\_water=True | CRITICAL (Layer 5 systemic state) |
| **Temp ≥ 40 + any lethargy** | temperature\_value ≥ 40.0, lethargy\_level != "none" | CRITICAL (Layer 4 + Layer 5 combined) |
| **Temp ≥ 39.7 + any lethargy** | temperature\_value ≥ 39.7, lethargy\_level != "none" | min HIGH (Layer 5 combined) |
| **Senior + systemic adjusted** | age ≥ 10y, systemic\_adjusted=True | +1 level (Layer 6 senior multiplier) |
| **Cat + RESPIRATORY** | species=cat, any RESPIRATORY symptom | min HIGH (Layer 6 species floor) |
| **Cat + difficulty\_breathing + lethargy** | species=cat, symptom=difficulty\_breathing, lethargy != "none" | CRITICAL |
| **GI + severe lethargy** | GI class, lethargy\_level="severe" | CRITICAL (Layer 5) |
| **Respiratory rate ≥ 50** | respiratory\_rate >= 50 | CRITICAL (Layer 4) |
| **Vomiting + diarrhea combo within 24h** | both symptoms in 24h window | min HIGH (Layer 1 cross-symptom) |
| **3+ episodes last hour (GI)** | last\_hour >= 3 | CRITICAL (Layer 1 CLINICAL\_RULES) |

---

## E. Episode Phase Engine v1

Function: `compute_episode_phase_v1(current_escalation, previous_max_urgency, monotonic_corrected, systemic_adjusted, cross_class_override)`

| Phase | Condition |
|-------|-----------|
| `initial` | previous\_max\_urgency is None (first event in episode) |
| `worsening` | current\_idx > previous\_max\_urgency |
| `progressing` | current\_idx == previous\_max\_urgency AND (systemic\_adjusted OR cross\_class\_override) |
| `stable` | current\_idx == previous\_max\_urgency, no new drivers |
| `improving` | monotonic\_corrected=True (lock held level; raw would have been lower) |

Phase labels are consumed by `get_phase_prefix()` in `response_templates.py`
to add a one-line tone prefix before the deterministic LLM prompt.

---

## F. Snapshot Baseline (v1)

The following scenario outcomes are frozen as of v1.0.0.
See `tests/test_clinical_engine_snapshot_v1.py` for executable assertions.

| Scenario | Input summary | escalation | episode\_phase |
|----------|---------------|------------|----------------|
| S2 | GI diarrhea last\_hour=3 | CRITICAL | initial |
| S4 | Juvenile 0.3y diarrhea + mild lethargy | CRITICAL | initial |
| S7 | Vomiting + refusing\_water | CRITICAL | initial |
| S11 | Previous HIGH (urgency=2), current triage → MODERATE → locked to HIGH | HIGH | improving |
| S12 | Senior 11y vomiting + mild lethargy + temp 39.8 + recurrence | CRITICAL | initial |
