"""Clinical history questionnaire — the "ontology" driving the interview.

Structure mirrors the SIH26047 problem statement:
  * General mode: chief complaint -> HPI (SOCRATES) -> past history ->
    surgical -> medications -> allergies -> family -> personal -> ROS.
  * AYUSH mode: appends Dashavidha Pariksha screening questions.

Each Question carries English + Hindi text and, optionally, tappable
options so that EVERY question is answerable by voice OR touch (FR-6).
Add languages by extending `render_question` in interview.py — it calls
Sarvam translate for languages without a bundled translation.

This file is meant to be reviewed and extended with a physician /
Ayurveda practitioner. It is deliberately plain data, not logic.
"""
from dataclasses import dataclass, field


@dataclass
class Question:
    id: str
    section: str
    slot: str                     # structured field this answer fills
    text_en: str
    text_hi: str
    options_en: list = field(default_factory=list)
    options_hi: list = field(default_factory=list)
    red_flag_watch: bool = False  # extra LLM scrutiny on the answer


GENERAL_SECTIONS = [
    ("chief_complaint", "Chief Complaint", "मुख्य समस्या", [
        dict(id="cc_main", slot="chief_complaint",
             text_en="What is the main problem you have come to the hospital for today?",
             text_hi="आज आप अस्पताल किस मुख्य समस्या के लिए आए हैं?",
             options_en=["Pain", "Fever", "Cough / breathing problem", "Stomach problem", "Something else"],
             options_hi=["दर्द", "बुखार", "खांसी / सांस की समस्या", "पेट की समस्या", "कुछ और"],
             red_flag_watch=True),
    ]),
    ("hpi", "History of Present Illness (SOCRATES)", "वर्तमान बीमारी का इतिहास", [
        dict(id="hpi_onset", slot="onset",
             text_en="When did this problem start?",
             text_hi="यह समस्या कब से है?",
             options_en=["Today", "Yesterday", "Since a week", "Since a month", "Longer"],
             options_hi=["आज से", "कल से", "एक हफ्ते से", "एक महीने से", "इससे ज़्यादा"]),
        dict(id="hpi_location", slot="location",
             text_en="Where in the body do you feel it? Show or tell me.",
             text_hi="यह शरीर के किस हिस्से में है?",
             options_en=["Head", "Chest", "Stomach", "Back", "Legs / arms", "Throat"]),
        dict(id="hpi_character", slot="character",
             text_en="What does it feel like — how would you describe it?",
             text_hi="यह कैसा महसूस होता है?",
             options_en=["Sharp", "Burning", "Throbbing", "Dull ache", "Cramping"]),
        dict(id="hpi_severity", slot="severity",
             text_en="If 0 is no pain and 10 is the worst pain, how bad is it?",
             text_hi="अगर 0 से 10 में बताएं, तो यह कितना तेज़ है?",
             options_en=["Mild", "Moderate", "Severe", "Very severe"]),
        dict(id="hpi_timing", slot="timing",
             text_en="Is it constant, or does it come and go?",
             text_hi="यह लगातार रहती है या आती-जाती है?",
             options_en=["Constant", "Comes and goes", "Only at night", "After food", "With activity"]),
        dict(id="hpi_aggravating", slot="aggravating_factors",
             text_en="What makes it worse?",
             text_hi="किन चीज़ों से यह बढ़ता है?"),
        dict(id="hpi_relieving", slot="relieving_factors",
             text_en="What makes it better?",
             text_hi="किन चीज़ों से आराम मिलता है?"),
        dict(id="hpi_associated", slot="associated_symptoms",
             text_en="Any other symptoms that came along with it?",
             text_hi="इसके साथ कोई और लक्षण हैं?",
             red_flag_watch=True),
    ]),
    ("past_history", "Past Medical & Surgical History", "पुरानी बीमारियाँ और ऑपरेशन", [
        dict(id="past_medical", slot="past_medical_history",
             text_en="Do you have any long-standing illness?",
             text_hi="क्या आपको कोई पुरानी बीमारी है?",
             options_en=["Diabetes", "High blood pressure", "Asthma", "Thyroid", "Heart disease", "Kidney disease", "None"],
             options_hi=["मधुमेह", "उच्च रक्तचाप", "दमा", "थायराइड", "दिल की बीमारी", "किडनी की बीमारी", "कोई नहीं"]),
        dict(id="past_surgical", slot="past_surgeries",
             text_en="Have you ever had an operation?",
             text_hi="क्या आपका कभी कोई ऑपरेशन हुआ है?",
             options_en=["Yes", "No"]),
    ]),
    ("medications", "Current Medications & Allergies", "वर्तमान दवाएँ और एलर्जी", [
        dict(id="meds_current", slot="current_medications",
             text_en="Are you taking any medicines at present?",
             text_hi="क्या आप इस समय कोई दवा ले रहे हैं?"),
        dict(id="meds_allergies", slot="allergies",
             text_en="Are you allergic to any medicine or food?",
             text_hi="किसी दवा या खाने से एलर्जी है?",
             options_en=["No allergy", "Medicine allergy", "Food allergy"]),
    ]),
    ("family_personal", "Family & Personal History", "पारिवारिक और व्यक्तिगत इतिहास", [
        dict(id="family_history", slot="family_history",
             text_en="Does anyone in your family have a serious illness?",
             text_hi="परिवार में किसी को कोई गंभीर बीमारी है?",
             options_en=["Diabetes", "Heart disease", "Cancer", "High blood pressure", "None"]),
        dict(id="personal_substances", slot="substance_use",
             text_en="Do you smoke or use tobacco? Do you drink alcohol?",
             text_hi="क्या आप धूम्रपान या तंबाकू का सेवन करते हैं? शराब पीते हैं?",
             options_en=["No", "Tobacco only", "Alcohol only", "Both"]),
    ]),
    ("ros", "Review of Systems", "अन्य लक्षण", [
        dict(id="ros_general", slot="ros_general",
             text_en="Any other problem — sleep, appetite, weight change, urine or bowel?",
             text_hi="कोई और समस्या — नींद, भूख, वज़न, पेशाब या पाखाना?",
             options_en=["Sleep problem", "Loss of appetite", "Weight loss", "Bowel / urine problem", "None"],
             options_hi=["नींद की समस्या", "भूख कम", "वज़न घटना", "पेशाब / पाखाने की समस्या", "कोई नहीं"],
             red_flag_watch=True),
    ]),
]

# Dashavidha Pariksha screening — simplified kiosk-adapted questions.
# Co-author the final set with an Ayurveda practitioner before any pilot;
# AIIA (the proposing institute) will care about fidelity here.
AYUSH_SECTIONS = [
    ("dashavidha", "Dashavidha Pariksha (AYUSH)", "दशविधा परीक्षा", [
        dict(id="ayu_agni", slot="agni",
             text_en="How is your digestion (Agni)?",
             text_hi="आपकी पाचन शक्ति (अग्नि) कैसी है?",
             options_en=["Good", "Irregular", "Weak"],
             options_hi=["अच्छी", "अनियमित", "कमज़ोर"]),
        dict(id="ayu_koshtha", slot="koshtha",
             text_en="How are your bowel movements (Koshtha)?",
             text_hi="पाखाने की आदत (कोष्ठ) कैसी है?",
             options_en=["Regular", "Hard", "Loose", "Irregular"],
             options_hi=["नियमित", "कड़ा", "ढीला", "अनियमित"]),
        dict(id="ayu_ahara_shakti", slot="ahara_shakti",
             text_en="How is your appetite (Ahara Shakti)?",
             text_hi="भूख (आहार शक्ति) कैसी लगती है?",
             options_en=["Good", "Low", "Excessive"],
             options_hi=["अच्छी", "कम", "बहुत ज़्यादा"]),
        dict(id="ayu_vyayama_shakti", slot="vyayama_shakti",
             text_en="Can you climb stairs or walk fast without difficulty (Vyayama Shakti)?",
             text_hi="सीढ़ी चढ़ने या तेज़ चलने में कठिनाई होती है (व्यायाम शक्ति)?",
             options_en=["No difficulty", "Some difficulty", "A lot of difficulty"]),
        dict(id="ayu_sattva", slot="sattva",
             text_en="How do you cope with stress or worry (Sattva)?",
             text_hi="तनाव या मानसिक दबाव को कैसे सहते हैं (सत्त्व)?",
             options_en=["Well", "Some difficulty", "Poorly"]),
        dict(id="ayu_samhanana", slot="samhanana",
             text_en="How would you describe your body build (Samhanana)?",
             text_hi="शरीर की बनावट (संहनन) कैसी है?",
             options_en=["Slim", "Medium", "Heavy"]),
        dict(id="ayu_nidra", slot="nidra",
             text_en="How is your sleep (Nidra)?",
             text_hi="नींद (निद्रा) कैसी आती है?",
             options_en=["Good", "Scanty", "Irregular"],
             options_hi=["अच्छी", "कम", "अनियमित"]),
        dict(id="ayu_ahara_vihara", slot="ahara_vihara",
             text_en="Tell me about your diet and daily routine (Ahara-Vihara).",
             text_hi="अपने खान-पान और दिनचर्या के बारे में बताइए।"),
    ]),
]


def build_questionnaire(mode: str = "general") -> list:
    """Return a flat list of Questions. mode: 'general' | 'ayush'."""
    sections = list(GENERAL_SECTIONS)
    if mode == "ayush":
        sections += AYUSH_SECTIONS
    questions = []
    for sec_id, title_en, title_hi, qs in sections:
        for q in qs:
            questions.append(Question(section=sec_id, **q))
    return questions


def section_titles():
    return {sid: (ten, thi) for sid, ten, thi, _ in GENERAL_SECTIONS + AYUSH_SECTIONS}
