import requests
import sys
import io
from routers.services.risk_engine import ESCALATION_ORDER

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

URL = "http://localhost:8000/chat"
USER_ID = "11111111-1111-1111-1111-111111111111"

# One fresh pet per scenario (0 events before first run)
PETS = {
    "S1":  "402830d5-f9f6-460d-8909-a94cdfaa81e1",
    "S2":  "e203c066-989a-49cd-8665-d6eb7a6d030e",
    "S3":  "703c967c-6182-406e-bdbe-05d8c1d58fda",
    "S4":  "a38da287-8614-4d98-bfa8-3154aedfce2b",
    "S5":  "82c42754-92ad-45f3-b589-f54e6bdf87f2",
    "S6":  "c43a1e7b-07c8-4748-970a-166aecb415b5",
    "S7":  "01da114a-65de-4473-9fb4-ccfdef86a3a5",
    "S8":  "ea836615-27c5-40e7-8760-0740ae1da690",
    "S9":  "adfa1a41-b89b-4577-8208-d13badec92e2",
    "S10": "f2432202-ff69-40fa-ad87-d8199f14ca2f",
}

SEP  = "=" * 64
SEP2 = "-" * 64


def send(pet_id: str, message: str) -> dict:
    """Send one message and return the full response dict."""
    try:
        r = requests.post(
            URL,
            json={"user_id": USER_ID, "pet_id": pet_id, "message": message},
            timeout=20,
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def print_result(label: str, message: str, data: dict):
    debug = data.get("debug") or {}
    ai   = data.get("ai_response", data.get("error", "NO RESPONSE"))
    print(f"  Msg : {message}")
    print(f"  Bot : {ai[:160]}{'...' if len(ai) > 160 else ''}")
    print(f"  old_escalation        : {debug.get('old_escalation', 'n/a')}")
    print(f"  calculated_escalation : {debug.get('calculated_escalation', 'n/a')}")
    print(f"  risk_score            : {debug.get('risk_score', 'n/a')}")


def run_scenario(key: str, title: str, messages: list[str]):
    pet_id = PETS[key]
    print(SEP)
    print(f"{key} — {title}")
    print(f"pet_id: {pet_id}")
    print(SEP2)

    last_data = {}
    for msg in messages:
        last_data = send(pet_id, msg)

    print_result(key, messages[-1], last_data)

    # Monotonic invariant check
    debug = last_data.get("debug")
    if debug:
        old  = debug.get("old_escalation")
        calc = debug.get("calculated_escalation")
        if old and calc:
            assert ESCALATION_ORDER[calc] >= ESCALATION_ORDER[old], (
                f"{key}: INVARIANT VIOLATED — calculated={calc} < old={old}"
            )
            print(f"  invariant: ESCALATION_ORDER[{calc}]={ESCALATION_ORDER[calc]} "
                  f">= ESCALATION_ORDER[{old}]={ESCALATION_ORDER[old]}  OK")

    print()
    return last_data


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

def main():
    print("RISK ENGINE v1 — CALIBRATION TEST")
    print(f"URL: {URL}\n")

    # S1 — single vomiting → LOW or MODERATE (score ~1-2)
    run_scenario(
        "S1",
        "Single vomiting — expect LOW/MODERATE",
        ["собака рвёт"],
    )

    # S2 — vomiting twice → score should rise
    run_scenario(
        "S2",
        "Vomiting twice — expect MODERATE",
        ["собака рвёт", "рвота снова"],
    )

    # S3 — vomiting three times (3+ in last hour) → CRITICAL
    run_scenario(
        "S3",
        "Vomiting x3 in session — expect CRITICAL",
        ["собака рвёт", "рвота снова", "ещё раз вырвало"],
    )

    # S4 — single vomiting with blood → HIGH (blood +3, base +1 = score 4)
    run_scenario(
        "S4",
        "Vomiting with blood — expect HIGH",
        ["у собаки рвота с кровью"],
    )

    # S5 — single diarrhea → LOW/MODERATE
    run_scenario(
        "S5",
        "Single diarrhea — expect LOW/MODERATE",
        ["у питомца понос"],
    )

    # S6 — diarrhea three times → MODERATE/HIGH
    run_scenario(
        "S6",
        "Diarrhea x3 — expect MODERATE/HIGH",
        ["у питомца понос", "понос снова", "ещё раз жидкий стул"],
    )

    # S7 — diarrhea with blood → HIGH
    run_scenario(
        "S7",
        "Diarrhea with blood — expect HIGH",
        ["у собаки понос с кровью"],
    )

    # S8 — vomiting + diarrhea combo → HIGH (cross-symptom override)
    run_scenario(
        "S8",
        "Vomiting + diarrhea combo — expect HIGH (override)",
        ["у питомца понос", "собака рвёт", "рвота снова"],
    )

    # S9 — vomiting + diarrhea + blood → HIGH or CRITICAL
    run_scenario(
        "S9",
        "Vomiting + diarrhea + blood — expect HIGH/CRITICAL",
        ["у питомца рвота с кровью", "ещё и понос"],
    )

    # S10 — fresh pet, single vomiting (control repeat of S1)
    run_scenario(
        "S10",
        "Fresh pet single vomiting (control) — expect LOW/MODERATE",
        ["собака рвёт"],
    )

    print(SEP)
    print("Calibration run complete")
    print(SEP)


if __name__ == "__main__":
    main()
