"""Dry-run test: full interview flow WITHOUT a Sarvam API key (mock mode).

Run:  python -m tests.test_interview_dry   (from the backend/ directory)

It walks the whole questionnaire, feeds answers as if the patient spoke or
tapped, includes one emergency utterance, and prints the generated summary.
"""
import sys

from app.interview import InterviewSession
from app.sarvam_client import SarvamBackend


def main() -> int:
    backend = SarvamBackend(api_key=None)          # mock mode
    assert backend.mock, "expected mock mode (no API key)"

    session = InterviewSession(backend=backend, language="en-IN", mode="general")
    print(f"Questions in questionnaire: {len(session.questions)}\n")

    # Canned answers simulating a mix of voice and touch input.
    answers = {
        "cc_main": "I have chest pain since yesterday",
        "hpi_onset": "Since yesterday",
        "hpi_location": "Chest, centre",
        "hpi_character": "Heavy pressure",
        "hpi_severity": "Severe",
        "hpi_timing": "Comes and goes",
        "hpi_aggravating": "Walking upstairs",
        "hpi_relieving": "Rest",
        "hpi_associated": "Sweating and breathlessness",   # should trigger red flag
        "past_medical": "High blood pressure",
        "past_surgical": "No",
        "meds_current": "Telmisartan 40 mg once daily",
        "meds_allergies": "No allergy",
        "family_history": "Father had heart disease",
        "personal_substances": "Tobacco only",
        "ros_general": "Sleep problem",
    }

    step = 0
    while not session.finished:
        qid, section, text, options = session.current_question()
        answer = answers.get(qid, "Not sure")
        print(f"[{step:02d}] {qid:22s} <- {answer}")
        session.record_answer(answer)
        step += 1
        assert step < 100, "runaway interview loop"

    print("\n--- RED FLAGS ---")
    for f in session.red_flags:
        print(" ", f)
    assert session.red_flags, "expected the chest-pain + breathlessness answer to raise a red flag"

    print("\n--- CAPTURED SLOTS ---")
    for k, v in session.slots.items():
        print(f"  {k:22s} = {v}")
    assert session.slots.get("chief_complaint")
    assert session.slots.get("current_medications") == "Telmisartan 40 mg once daily"

    summary = session.build_summary()
    print("\n--- SUMMARY (draft) ---")
    print(summary["formatted"][:800])

    # AYUSH mode smoke test
    ayush = InterviewSession(backend=backend, language="hi-IN", mode="ayush")
    ids = [q.id for q in ayush.questions]
    assert "ayu_agni" in ids and "cc_main" in ids, "AYUSH mode should append Dashavidha questions"
    print(f"\nAYUSH mode OK — {len(ayush.questions)} questions (incl. Dashavidha Pariksha).")

    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
