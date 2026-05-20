import os
import json
import re
from datetime import datetime

import google.generativeai as genai
from dotenv import load_dotenv
from departments import SYMPTOM_DEPARTMENT_MAP
from questions import get_follow_up_question, is_emergency

load_dotenv()

MODEL_NAME = "gemini-2.0-flash"

# Module-level constants — defined once, not inside function
CRITICAL_PATTERNS = [
    "turning blue", "lips blue", "face blue", "nails blue",
    "fainted", "passed out", "unconscious", "not responding",
    "can't breathe", "cannot breathe", "not breathing", "gasping",
    "no pulse", "heart stopped", "collapsed",
    "behosh", "hosh nahi", "saans nahi aa rahi", "neela ho",
    "lips neeli", "chehra neela",
]


def _configure_client(use_backup=False):
    key_name = "GEMINI_API_KEY_2" if use_backup else "GEMINI_API_KEY"
    api_key = os.getenv(key_name)
    if not api_key:
        raise ValueError(f"{key_name} environment variable not set")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel(
        model_name=MODEL_NAME,
        generation_config={
            "temperature": 0.3,
            "top_p": 0.95,
            "max_output_tokens": 1024,
        }
    )


def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[SYMPTOM AGENT] {timestamp} {message}")


def detect_language(text):
    urdu_script = re.search(r'[\u0600-\u06FF]', text)
    if urdu_script:
        return "urdu"
    roman_urdu_keywords = [
        "mujhe", "hai", "hain", "karo", "dard", "bukhar",
        "khansi", "seena", "pet", "sar", "bacha", "mere",
        "meri", "abbu", "ammi", "bhai", "yaar", "bohat",
        "nahi", "aur", "ka", "ki", "ke", "se", "mein",
        "ho", "raha", "rahi", "gaya", "gayi", "bahut",
        "thoda", "zyada", "kam", "achha", "bura", "tez"
    ]
    text_lower = text.lower()
    matches = sum(1 for word in roman_urdu_keywords if word in text_lower.split())
    if matches >= 1:
        return "roman_urdu"
    return "english"


def keyword_fallback(user_message):
    text_lower = user_message.lower()
    best_match = None
    best_urgency = "LOW"

    for key, value in SYMPTOM_DEPARTMENT_MAP.items():
        for keyword in value.get("keywords", []):
            if keyword.lower() in text_lower:
                dept = value.get("department", value.get("description", "General Medicine"))
                urgency_list = value.get("urgency_levels", value.get("urgency", ["MEDIUM"]))
                if isinstance(urgency_list, list):
                    urgency = urgency_list[0] if urgency_list else "MEDIUM"
                else:
                    urgency = str(urgency_list)

                urgency_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
                if urgency_rank.get(urgency, 0) > urgency_rank.get(best_urgency, 0):
                    best_match = dept
                    best_urgency = urgency

    if best_match:
        return {"department": best_match, "urgency": best_urgency}
    return {"department": "General Medicine", "urgency": "LOW"}


def analyze_symptoms(
    user_message,
    report_findings=None,
    conversation_history=None,
    session_id="default"
):
    log(f"Input received: text symptoms")
    log(f"Session ID: {session_id}")

    language = detect_language(user_message)
    log(f"Language detected: {language}")

    # ── PRE-CHECK: force CRITICAL if emergency/critical keywords detected ─────
    force_critical = is_emergency(user_message) or any(p in user_message.lower() for p in CRITICAL_PATTERNS)
    if force_critical:
        log("Force CRITICAL detected — running Gemini for summary only")
    # ── CHECK 3: Gemini analysis ──────────────────────────────────────────────
    try:
        model = _configure_client(use_backup=False)

        departments_json = json.dumps(SYMPTOM_DEPARTMENT_MAP, ensure_ascii=False)

        history_text = ""
        if conversation_history:
            history_text = f"\nPrevious conversation: {json.dumps(conversation_history, ensure_ascii=False)}"

        report_text = ""
        if report_findings and not report_findings.get("error"):
            report_text = f"\nMedical report findings: {json.dumps(report_findings, ensure_ascii=False)}"

        prompt = f"""You are Sehat Agent's medical symptom analyzer for Pakistani patients.
You understand Urdu, Roman Urdu, and English.
NEVER diagnose definitively. Be warm and empathetic.
NEVER use Hindi/Devanagari script. Use Roman Urdu only for Urdu responses.
Detected language: {language}

Patient message: "{user_message}"{report_text}{history_text}

Available departments: {departments_json}

Respond ONLY in strict JSON (no markdown, no extra text):
{{
   "symptoms_summary": "medical description of what the patient is experiencing — describe the clinical significance, possible causes, NOT just repeat their words",
    "combined_analysis": "analysis combining symptoms and report if available",
    "urgency_level": "LOW or MEDIUM or HIGH or CRITICAL",
    "recommended_department": "exact department name from the available departments map",
    "sub_department": "sub-specialty if applicable or null",
    "do_not_delay": true or false,
    "follow_up_needed": true or false,
    "reasoning": "why this department was chosen — explain clearly",
    "red_flags": ["any warning signs found"],
    "confidence": "HIGH or MEDIUM or LOW"
}}

URGENCY RULES — override everything else:
- For CRITICAL cases, symptoms_summary MUST describe the medical emergency (e.g. 'Loss of consciousness with cyanosis — possible oxygen deprivation or cardiac event')
- CRITICAL if: unconscious, not breathing, turning blue, cyanosis, no pulse, collapsed, seizure
- CRITICAL if: fainted + any other symptom present
- HIGH if: severe chest pain, severe bleeding, high fever in infant
- When in doubt between HIGH and CRITICAL, always choose CRITICAL
- NEVER return LOW for any message involving loss of consciousness

RULES for follow_up_needed:
- Set TRUE if urgency is LOW or MEDIUM and more info would help
- Set FALSE if urgency is HIGH or CRITICAL (go immediately)
- Set FALSE if symptoms are very clear and department is obvious
"""

        log(f"Sending to Gemini {MODEL_NAME} for analysis...")

        try:
            response = model.generate_content(prompt)
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
                log("Quota exceeded on primary key. Switching to GEMINI_API_KEY_2...")
                model = _configure_client(use_backup=True)
                response = model.generate_content(prompt)
            else:
                raise e

        text_response = response.text.strip()

        # Clean markdown fences
        if text_response.startswith("```json"):
            text_response = text_response[7:]
            if text_response.endswith("```"):
                text_response = text_response[:-3]
            text_response = text_response.strip()
        elif text_response.startswith("```"):
            text_response = text_response[3:]
            if text_response.endswith("```"):
                text_response = text_response[:-3]
            text_response = text_response.strip()

        brace_match = re.search(r'\{.*\}', text_response, re.DOTALL)
        if brace_match:
            text_response = brace_match.group(0)

        analysis = json.loads(text_response)

        urgency = "CRITICAL" if force_critical else analysis.get("urgency_level", "MEDIUM")
        dept = "Emergency" if force_critical else analysis.get("recommended_department", "General Medicine")
        log(f"Urgency determined: {urgency}")
        log(f"Department: {dept}")

        follow_up = None if force_critical else get_follow_up_question(user_message, language=language)
        gemini_wants_followup = analysis.get("follow_up_needed", False)
        needs_followup = False if force_critical else (gemini_wants_followup and follow_up is not None and urgency not in ("HIGH", "CRITICAL"))
        log(f"Follow-up needed: {'Yes' if needs_followup else 'No'}")
        log("JSON handoff ready -> Main Agent")

        return {
            "agent": "symptom_report_agent",
            "status": "needs_followup" if needs_followup else "complete",
            "session_id": session_id,
            "symptoms_summary": analysis.get("symptoms_summary", user_message),
            "report_findings": report_findings,
            "combined_analysis": analysis.get("combined_analysis", ""),
            "urgency_level": urgency,
            "recommended_department": dept,
            "sub_department": analysis.get("sub_department", None),
            "do_not_delay": True if force_critical else analysis.get("do_not_delay", False),
            "follow_up_question": follow_up if needs_followup else None,
            "reasoning": analysis.get("reasoning", ""),
            "red_flags": analysis.get("red_flags", []),
            "disclaimer": "This is AI guidance only. Always consult a qualified doctor.",
            "confidence": analysis.get("confidence", "MEDIUM"),
            "language": language
        }

    except Exception as e:
        log(f"Gemini failed — using keyword fallback. Error: {str(e)}")
        fallback = keyword_fallback(user_message)
        follow_up = get_follow_up_question(user_message, language=language)
        log(f"Fallback department: {fallback['department']}")
        log("JSON handoff ready -> Main Agent")

        return {
            "agent": "symptom_report_agent",
            "status": "needs_followup" if follow_up else "complete",
            "session_id": session_id,
            "symptoms_summary": "CRITICAL: Behoshi (loss of consciousness) — possible causes include low blood pressure, cardiac event, or oxygen deprivation. Immediate emergency care required." if force_critical else user_message,
            "report_findings": report_findings,
            "combined_analysis": "Basic analysis using keyword matching (AI temporarily unavailable).",
            "urgency_level": "CRITICAL" if force_critical else fallback["urgency"],
            "recommended_department": "Emergency" if force_critical else fallback["department"],
            "sub_department": None,
            "do_not_delay": fallback["urgency"] in ["HIGH", "CRITICAL"],
            "follow_up_question": follow_up,
            "reasoning": "Keyword-based fallback used due to API error.",
            "red_flags": [],
            "disclaimer": "This is AI guidance only. Always consult a qualified doctor.",
            "confidence": "LOW",
            "language": language,
            "fallback_used": True
        }