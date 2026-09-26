"""The interview state machine (Module A of the blueprint).

Design: a constrained dialogue over a clinical questionnaire.
  - The next question comes from the ontology (deterministic, safe).
  - The LLM never decides the topic; it only (a) extracts structured values
    from the patient's answer, (b) flags emergencies, and (c) may ask ONE
    clarifying follow-up per question when the answer is incomplete.
  - Without a key, everything degrades gracefully to naive slot-filling.

Red flags are detected with bilingual keyword rules FIRST (never depend on
the LLM for safety), then augmented by the LLM's judgement.
"""
import json
import logging
import re

from .ontology import build_questionnaire
from .prompts import (
    EXTRACTION_SYSTEM, EXTRACTION_USER_TMPL, SUMMARY_SYSTEM, FOLLOWUP_LIMIT_PER_QUESTION,
)

log = logging.getLogger("medikiosk.interview")

# Rule-based red flags. Hindi + English + common romanized forms.
REASK = {
    "hi-IN": "माफ़ कीजिए, मैं समझ नहीं पाया। क्या आप फिर बता सकते हैं?",
    "en-IN": "Sorry, I could not hear that clearly. Could you say it again?",
}
_RED_FLAG_RULES = [
    (r"(chest\s*pain|सीने\s*में\s*(दर्द|जलन|भारीपन)|seene\s*me)", "chest_pain"),
    (r"(breathless|can'?t breathe|shortness of breath|saans|सांस\s*नहीं|सांस\s*फूल)", "breathlessness"),
    (r"(heart attack|दिल\s*का\s*दौरा)", "possible_cardiac"),
    (r"(unconscious|fainted|बेहोश)", "loss_of_consciousness"),
    (r"(heavy bleeding|खून\s*बह|bleeding a lot)", "severe_bleeding"),
    (r"(face droop|slurred speech|arm weakness|चेहरा\s*टेढ़ा|लड़खड़ाती\s*बोली)", "stroke_signs"),
    (r"(suicid|आत्महत्या|जान\s*दे)", "suicidal_ideation"),
]
_COMPILED = [(re.compile(p, re.IGNORECASE), tag) for p, tag in _RED_FLAG_RULES]
# Tag combinations that justify a triage alert. Tags ACCUMULATE across the
# whole session: "chest pain" in one answer + "breathlessness" in a later
# answer is an emergency pattern, even though neither utterance alone is.
_COMBOS = [
    {"chest_pain", "breathlessness"},
    {"possible_cardiac"},
    {"stroke_signs"},
    {"severe_bleeding"},
    {"suicidal_ideation"},
    {"loss_of_consciousness"},
]


def detect_red_flag_tags(text: str) -> set[str]:
    """Return the set of symptom tags present in this utterance."""
    if not text:
        return set()
    return {tag for pattern, tag in _COMPILED if pattern.search(text)}


class InterviewSession:
    def __init__(self, backend, language: str = "hi-IN", mode: str = "general"):
        self.backend = backend
        self.language = language if language != "hi" else "hi-IN"
        self.mode = mode
        self.questions = build_questionnaire(mode)
        self.idx = 0
        self.slots: dict[str, str] = {}
        self.transcript: list[dict] = []          # {"question", "answer", "qid"}
        self.red_flags: list[str] = []
        self.finished = False
        self._followups_asked: dict[str, int] = {}
        self._pending_followup: tuple[str, str] | None = None   # (question_text, slot)
        self._flag_hits: set[str] = set()         # symptom tags seen so far
        self._raised_combos: set[frozenset] = set()

    def _update_red_flags(self, answer: str) -> list[str]:
        """Accumulate symptom tags across the session and raise an alert when a
        danger combination is completed. Returns NEW alert messages only."""
        self._flag_hits |= detect_red_flag_tags(answer)
        new_msgs = []
        for combo in _COMBOS:
            key = frozenset(combo)
            if combo <= self._flag_hits and key not in self._raised_combos:
                self._raised_combos.add(key)
                new_msgs.append(
                    f"RED FLAG: {', '.join(sorted(combo))} — alert triage immediately")
        self.red_flags.extend(new_msgs)
        return new_msgs

    # ---------- question rendering ----------
    def render_question(self, q) -> tuple[str, list[str]]:
        """Return (text, options) in the session language."""
        if self.language.startswith("hi"):
            text, options = q.text_hi, list(q.options_hi or [])
        elif self.language.startswith("en"):
            text, options = q.text_en, list(q.options_en or [])
        else:
            # Languages without bundled translations: machine-translate once (cached).
            text = self.backend.translate(q.text_en, self.language)
            options = [self.backend.translate(o, self.language) for o in (q.options_en or [])]
        return text, options

    def current_question(self) -> tuple[str, str, list[str], str]:
        """Returns (qid, section, text, options) for the question to ask now."""
        if self._pending_followup is not None:
            text, slot = self._pending_followup
            return ("followup", "followup", text, [])
        q = self.questions[self.idx]
        text, options = self.render_question(q)
        return (q.id, q.section, text, options)

    @property
    def progress(self) -> tuple[int, int]:
        return (self.idx + 1, len(self.questions))

    # ---------- answer handling ----------
    def _extract(self, q, question_text: str, answer: str) -> dict:
        """Ask the LLM to normalize the answer. Always returns a dict."""
        fallback = {
            "understood": bool(answer.strip()),
            "slot_values": {q.slot: answer.strip()} if q.slot else {},
            "red_flag": False,
            "follow_up": None,
        }
        if not answer.strip() or self.backend.mock:
            return fallback
        user = EXTRACTION_USER_TMPL.format(
            qid=q.id, slot=q.slot, question=question_text, answer=answer,
            language=self.language,
        )
        raw = self.backend.chat(system=EXTRACTION_SYSTEM, user=user)
        if not raw:
            return fallback
        try:
            cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                return fallback
            data.setdefault("understood", True)
            data.setdefault("slot_values", {q.slot: answer.strip()})
            data.setdefault("red_flag", False)
            data.setdefault("follow_up", None)
            if not isinstance(data["slot_values"], dict):
                data["slot_values"] = {q.slot: answer.strip()}
            # Always ensure the asked field exists
            data["slot_values"].setdefault(q.slot, answer.strip())
            return data
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("extraction JSON parse failed: %s", e)
            return fallback

    def record_answer(self, answer: str) -> list[str]:
        """Process one patient answer (voice transcript or touched option).

        Returns the list of NEW red-flag messages, if any.
        """
        new_flags = self._update_red_flags(answer)

        if self._pending_followup is not None:
            # Merge the clarification into the current question's slot, then move on.
            q = self.questions[self.idx]
            question_text, _ = self._pending_followup
            self._pending_followup = None
            self._ingest(q, question_text, answer)
            self.idx += 1
            self._check_finished()
            return new_flags

        q = self.questions[self.idx]
        question_text, _options = self.render_question(q)

        if not answer.strip():
            # Skip / unintelligible: record the miss and move on. (Voice answers
            # that fail to transcribe are re-asked by the server before this point.)
            self._ingest(q, question_text, answer)
            self.idx += 1
            self._check_finished()
            return new_flags

        extraction = self._extract(q, question_text, answer)
        self._ingest(q, question_text, answer, extraction)

        if extraction.get("red_flag"):
            llm_flag = "RED FLAG: possible emergency mentioned — alert triage"
            if llm_flag not in self.red_flags:
                self.red_flags.append(llm_flag)
            new_flags.append(llm_flag)

        if not extraction.get("understood", True):
            # The LLM could not understand a NON-empty answer: give the patient
            # one clarifying re-ask via the follow-up mechanism, then move on.
            asked = self._followups_asked.get(q.id, 0)
            if asked >= FOLLOWUP_LIMIT_PER_QUESTION:
                self.idx += 1
                self._check_finished()
            else:
                self._followups_asked[q.id] = asked + 1
                self._pending_followup = (REASK.get(self.language, REASK["en-IN"]), q.slot)
            return new_flags

        asked = self._followups_asked.get(q.id, 0)
        follow_up = extraction.get("follow_up")
        if follow_up and asked < FOLLOWUP_LIMIT_PER_QUESTION:
            self._followups_asked[q.id] = asked + 1
            self._pending_followup = (follow_up, q.slot)
        else:
            self.idx += 1
        self._check_finished()
        return new_flags

    def _ingest(self, q, question_text: str, answer: str, extraction: dict | None = None):
        if extraction is None:  # naive path (mock / LLM unavailable)
            if q.slot and answer.strip():
                self.slots[q.slot] = answer.strip()
        else:
            for k, v in extraction.get("slot_values", {}).items():
                if v not in (None, "", []):
                    self.slots[k] = v
        self.transcript.append({
            "qid": q.id, "section": q.section,
            "question": question_text, "answer": answer.strip() or "(no answer)",
        })

    def _check_finished(self):
        self.finished = self.idx >= len(self.questions)

    # ---------- summary ----------
    def structured(self) -> dict:
        return {
            "language": self.language,
            "mode": self.mode,
            "slots": dict(self.slots),
            "transcript": self.transcript,
            "red_flags": self.red_flags,
        }

    def build_summary(self) -> dict:
        """LLM-formatted physician summary (Module C-lite) + raw structure."""
        data = self.structured()
        if self.backend.mock:
            formatted = self._template_summary()
        else:
            formatted = self.backend.chat(
                system=SUMMARY_SYSTEM, user=json.dumps(data, ensure_ascii=False, indent=2),
                temperature=0.2,
            ) or self._template_summary()
        return {"structured": data, "formatted": formatted}

    def _template_summary(self) -> str:
        lines = ["# Clinical History (draft) — auto-generated at kiosk", ""]
        for entry in self.transcript:
            lines.append(f"**{entry['question']}**")
            lines.append(f"- {entry['answer']}")
            lines.append("")
        if self.red_flags:
            lines.append("## Red Flags")
            lines.extend(f"- {f}" for f in self.red_flags)
        return "\n".join(lines)
