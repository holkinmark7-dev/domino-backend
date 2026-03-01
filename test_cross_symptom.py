import requests
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "http://localhost:8000/chat"
USER_ID = "11111111-1111-1111-1111-111111111111"

# NOTE: Rule 1 and Rule 2 (blood + vomiting/diarrhea) cannot be tested
# because the extraction prompt has no "blood" field — it is never stored.
# Only Rule 3 (vomiting + diarrhea combo within 24h) is testable.

# PET_COMBO may accumulate history across runs — Rule 3 fires earlier each time,
# but the PASS check (urgency in final response) remains valid regardless.
PET_COMBO   = "7252a391-6b9e-441d-9ebe-469996eb4c45"

# PET_CONTROL must be fresh: only diarrhea, never vomiting.
# Uses ae5dde8f — 0 events before first test run.
# Each run adds only diarrhea events to this pet; vomiting is never sent here,
# so Rule 3 (needs both) never fires no matter how many runs.
PET_CONTROL = "ae5dde8f-be06-4779-8807-2c846821de9a"

URGENCY_WORDS = ["высок", "срочно", "немедленно", "опасн", "риск", "критич", "обратитесь"]

SEP = "=" * 60
SEP2 = "-" * 60


def send(pet_id: str, message: str) -> str:
    try:
        r = requests.post(
            URL,
            json={"user_id": USER_ID, "pet_id": pet_id, "message": message},
            timeout=15
        )
        data = r.json()
        return data.get("ai_response", f"ERR: {list(data.keys())}")
    except Exception as e:
        return f"ERR: {e}"


def has_urgency(text: str) -> bool:
    lo = text.lower()
    return any(w in lo for w in URGENCY_WORDS)


# ---------------------------------------------------------------------------
# S1 — Rule 3: vomiting + diarrhea combo → override to HIGH
# ---------------------------------------------------------------------------
# Flow rationale:
#   apply_cross_symptom_override runs BEFORE save_medical_event.
#   So the current message's event is NOT yet in the DB when the override runs.
#   Therefore the combo only fires when a previous vomiting event is already saved.
#
#   M1  "у питомца понос"  → diarrhea event saved; vomiting stats=0 → LOW
#   M2  "собака рвёт"      → vomiting event 1 saved; override: diarrhea=True,
#                             vomiting=False (M2 not saved yet) → no fire → LOW
#   M3  "рвота снова"      → vomiting event 2; override: diarrhea=True,
#                             vomiting=True (M2 IS in DB) → FIRE → HIGH
#
# Expected: M3 response shows urgency; M2 shows data-gathering (no urgency).
# ---------------------------------------------------------------------------

def test_s1_combo():
    print(SEP)
    print("S1 — Rule 3: vomiting + diarrhea combo → HIGH override")
    print(SEP)

    print(f'\n[M1] "у питомца понос"  →  creates diarrhea event')
    r1 = send(PET_COMBO, "у питомца понос")
    print(f"Bot: {r1[:160]}...")

    print(f'\n[M2] "собака рвёт"  →  vomiting #1; override not yet active')
    r2 = send(PET_COMBO, "собака рвёт")
    print(f"Bot: {r2[:160]}...")
    m2_has_urgency = has_urgency(r2)
    print(f"M2 urgency words present: {m2_has_urgency}  (expected: False — override not fired yet)")

    print(f'\n[M3] "рвота снова"  →  vomiting #2; Rule 3 should fire: HIGH override')
    r3 = send(PET_COMBO, "рвота снова")
    print(f"\nBot (M3 — full response):\n{r3}")

    m3_has_urgency = has_urgency(r3)
    m3_no_questions = "?" not in r3

    print(f"\n{SEP2}")
    print(f"M3 urgency words present : {m3_has_urgency}")
    print(f"M3 no questions          : {m3_no_questions}")

    # PASS: M3 shows urgency (override fired → HIGH → URGENT_QUESTIONS)
    # The response type at HIGH is URGENT_QUESTIONS which includes urgency language.
    if m3_has_urgency:
        print("PASS: Rule 3 override raised escalation — urgency detected in M3")
        return True
    else:
        print("FAIL: No urgency in M3 — override may not have fired")
        print(f"  Checked words: {URGENCY_WORDS}")
        return False


# ---------------------------------------------------------------------------
# S2 — Control: vomiting alone (no diarrhea history) → no override → LOW
# ---------------------------------------------------------------------------
# Flow:
#   M1  "собака рвёт"   → vomiting #1; no diarrhea in DB → no override → LOW
#   M2  "рвота снова"   → vomiting #2; still no diarrhea → no override → LOW
#
# Expected: M2 response asks clarifying questions (LOW → ASSESS).
# No urgency words expected — override must NOT fire.
# ---------------------------------------------------------------------------

def test_s2_control():
    print(f"\n{SEP}")
    print("S2 — Control: diarrhea only (no vomiting ever sent) → override must NOT fire")
    print(SEP)
    print("Rationale: Rule 3 requires BOTH vomiting AND diarrhea in DB.")
    print("  PET_CONTROL only receives diarrhea messages — has_recent_vomiting stays False.")
    print("  Override cannot fire regardless of how many runs accumulate.\n")

    print(f'[M1] "у питомца понос"  →  diarrhea; no vomiting in DB → Rule 3 cannot fire')
    r1 = send(PET_CONTROL, "у питомца понос")
    print(f"\nBot (M1 — full response):\n{r1}")

    m1_has_urgency = has_urgency(r1)
    m1_has_questions = "?" in r1

    print(f"\n{SEP2}")
    print(f"M1 urgency words present   : {m1_has_urgency}  (expected: False — override cannot fire)")
    print(f"M1 has clarifying questions: {m1_has_questions}  (expected: True — LOW/ASSESS or data-gathering)")

    # PASS: no urgency (override didn't fire) AND bot asks questions (ASSESS mode)
    # Note: if this pet has accumulated many diarrhea events, stats alone
    # may reach MODERATE/HIGH after many runs. The override still doesn't fire
    # (no vomiting), but the urgency check may eventually fail from stats alone.
    # In that case the note below will explain it.
    if not m1_has_urgency:
        print("PASS: Override did not fire — no urgency from Rule 3")
        return True
    else:
        print("FAIL: Urgency detected — check if diarrhea stats alone reached HIGH")
        print("  (Rule 3 override cannot be the cause: no vomiting events on this pet)")
        return False


# ---------------------------------------------------------------------------
# S3 — Dead-code note: blood rules (Rules 1 & 2) — informational only
# ---------------------------------------------------------------------------

def test_s3_blood_note():
    print(f"\n{SEP}")
    print("S3 — NOTE: Rules 1 & 2 (blood + vomiting/diarrhea)")
    print(SEP)
    print("""
  The extraction prompt (ai.py extract_event_data) has no 'blood' field.
  Fields extracted: symptom, food, medication, behavior, urgency_score.

  Because 'blood' is never stored in event content,
  apply_cross_symptom_override() → has_blood is always False.

  Rules 1 and Rule 2 are structurally correct but unreachable
  until the extraction prompt adds a 'blood: boolean' field.

  ACTION REQUIRED (separate task):
    Add 'blood' to extraction prompt fields.

  S3 result: SKIP (not testable)
""")
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("CROSS-SYMPTOM RISK OVERRIDE — TEST SUITE")
    print(f"URL: {URL}")
    print(f"PET_COMBO   : {PET_COMBO}")
    print(f"PET_CONTROL : {PET_CONTROL}")

    r1 = test_s1_combo()
    r2 = test_s2_control()
    r3 = test_s3_blood_note()

    print(f"\n{SEP}")
    print("SUMMARY")
    print(SEP)

    results = [
        ("S1  Rule 3 combo override", r1),
        ("S2  Control no override  ", r2),
        ("S3  Blood rules (dead)   ", r3),
    ]

    passed = 0
    total  = 0
    for name, ok in results:
        if ok is None:
            print(f"[SKIP] {name}")
        elif ok:
            print(f"[PASS] {name}")
            passed += 1
            total  += 1
        else:
            print(f"[FAIL] {name}")
            total  += 1

    print(f"\n{passed}/{total} tests passed  ({len([r for _, r in results if r is None])} skipped)")


if __name__ == "__main__":
    main()
