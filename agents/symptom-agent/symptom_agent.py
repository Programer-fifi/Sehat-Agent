import os
import json
import re
from datetime import datetime
from google import genai
from departments import SYMPTOM_DEPARTMENT_MAP
from questions import get_follow_up_question, is_emergency

def get_client(use_backup=False):
    key_name = "GEMINI_API_KEY_2" if use_backup else "GEMINI_API_KEY"
    api_key = os.getenv(key_name)
    if not api_key:
        raise ValueError(f"{key_name} environment variable not set")
    return genai.Client(api_key=api_key)

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[SYMPTOM AGENT] {timestamp} {message}")

def detect_language(text):
    urdu_script = re.search(r'[\u0600-\u06FF]', text)
    if urdu_script:
        return "urdu"
    roman_urdu_keywords = ["mujhe", "hai", "hain", "karo", "dard", "bukhar", 
                            "khansi", "seena", "pet", "sar", "bacha", "mere",
                            "meri", "abbu", "ammi", "bhai", "yaar", "bohat"]
    text_lower = text.lower()
    for word in roman_urdu_keywords:
        if word in text_lower:
            return "roman_urdu"
    return "english"

# Canonical display name for each department key
DEPT_DISPLAY_NAMES = {
    "cardiology":       "Cardiology",
    "neurology":        "Neurology",
    "orthopedics":      "Orthopedics",
    "gastroenterology": "Gastroenterology",
    "pulmonology":      "Pulmonology",
    "dermatology":      "Dermatology",
    "pediatrics":       "Pediatrics",
    "gynecology":       "Gynecology",
    "general_medicine": "General Medicine",
}

VALID_DEPT_KEYS = list(DEPT_DISPLAY_NAMES.keys())


def normalize_department(raw: str) -> str:
    """Convert any Gemini output format to a canonical display name."""
    if not raw:
        return "General Medicine"
    raw_lower = raw.lower().strip()
    # Direct key match
    if raw_lower in DEPT_DISPLAY_NAMES:
        return DEPT_DISPLAY_NAMES[raw_lower]
    # Substring match against keys
    for key, display in DEPT_DISPLAY_NAMES.items():
        if key in raw_lower or raw_lower in key:
            return display
    # Substring match against display names
    for key, display in DEPT_DISPLAY_NAMES.items():
        if display.lower() in raw_lower or raw_lower in display.lower():
            return display
    return raw  # return as-is if nothing matches


def keyword_fallback(user_message):
    text_lower = user_message.lower()
    for key, value in SYMPTOM_DEPARTMENT_MAP.items():
        for keyword in value.get("keywords", []):
            if keyword.lower() in text_lower:
                return {
                    # Return canonical display name, not the description
                    "department": DEPT_DISPLAY_NAMES.get(key, value["description"]),
                    "urgency": value["urgency_levels"][0] if value["urgency_levels"] else "MEDIUM"
                }
    return {
        "department": "General Medicine",
        "urgency": "LOW"
    }

def analyze_symptoms(user_message, report_findings=None, conversation_history=None, session_id="default"):
    log(f"Input received: text symptoms")
    log(f"Session ID: {session_id}")

    language = detect_language(user_message)
    log(f"Language detected: {language}")

    if is_emergency(user_message):
        log("EMERGENCY KEYWORDS DETECTED - marking CRITICAL")
        log("Department: Emergency")
        log("JSON handoff ready -> Main Agent")
        return {
            "agent": "symptom_report_agent",
            "status": "complete",
            "session_id": session_id,
            "symptoms_summary": user_message,
            "report_findings": report_findings,
            "combined_analysis": "Emergency situation detected. Immediate medical attention required.",
            "urgency_level": "CRITICAL",
            "recommended_department": "Emergency",
            "sub_department": None,
            "do_not_delay": True,
            "follow_up_question": None,
            "reasoning": "Emergency keywords detected in patient message.",
            "red_flags": ["Emergency situation"],
            "disclaimer": "This is AI guidance only. Always consult a qualified doctor.",
            "confidence": "HIGH",
            "language": language
        }

    try:
        client = get_client()
        departments_json = json.dumps(SYMPTOM_DEPARTMENT_MAP)

        history_text = ""
        if conversation_history:
            history_text = f"Previous conversation: {json.dumps(conversation_history)}"

        report_text = ""
        if report_findings:
            report_text = f"Medical report findings: {json.dumps(report_findings)}"

        valid_keys_str = ", ".join(VALID_DEPT_KEYS)

        prompt = f"""
You are Sehat Agent's medical symptom analyzer for Pakistani patients.
You understand Urdu, Roman Urdu, and English.
Never diagnose definitively. Be warm and empathetic.
Never use Hindi/Devanagari script. Use Roman Urdu for Urdu responses.
Detected language: {language}

Patient message: "{user_message}"
{report_text}
{history_text}

VALID DEPARTMENT KEYS (you MUST use EXACTLY one of these, lowercase as shown):
{valid_keys_str}

Department details for reference: {departments_json}

Your task:
1. Analyze ALL symptoms carefully.
2. Consider MULTIPLE possible departments (differential diagnosis).
3. Rule out less likely departments with reasoning.
4. Choose the SINGLE most appropriate department key from the valid list above.
5. Set urgency honestly — only CRITICAL if truly life-threatening.

Respond ONLY in strict JSON (no markdown, no extra text):
{{
    "symptoms_summary": "brief summary of reported symptoms",
    "combined_analysis": "clinical analysis combining all symptoms",
    "urgency_level": "LOW or MEDIUM or HIGH or CRITICAL",
    "recommended_department": "EXACT KEY from valid list above (e.g. cardiology, general_medicine)",
    "differential_considered": ["other departments you considered"],
    "ruled_out_reason": "why other departments were ruled out",
    "sub_department": "sub-specialty if applicable or null",
    "do_not_delay": true or false,
    "follow_up_needed": true or false,
    "reasoning": "step-by-step reasoning for chosen department",
    "red_flags": ["any warning signs found"],
    "confidence": "HIGH or MEDIUM or LOW"
}}
"""

        log("Sending to Gemini 2.0 Flash for analysis...")
        try:
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt
            )
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                log("Quota exceeded on primary key. Switching to GEMINI_API_KEY_2...")
                client = get_client(use_backup=True)
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=prompt
                )
            else:
                raise e

        text_response = response.text.strip()
        if text_response.startswith("```json"):
            text_response = text_response[7:-3].strip()
        elif text_response.startswith("```"):
            text_response = text_response[3:-3].strip()

        analysis = json.loads(text_response)
        log(f"Urgency determined: {analysis.get('urgency_level', 'MEDIUM')}")
        log(f"Department: {analysis.get('recommended_department', 'General Medicine')}")

        follow_up = get_follow_up_question(user_message)
        needs_followup = analysis.get("follow_up_needed", False) and follow_up is not None
        log(f"Follow-up needed: {'Yes' if needs_followup else 'No'}")
        log("JSON handoff ready -> Main Agent")

        # Normalize department key to a proper display name
        raw_dept = analysis.get("recommended_department", "general_medicine")
        normalized_dept = normalize_department(raw_dept)

        return {
            "agent": "symptom_report_agent",
            "status": "needs_followup" if needs_followup else "complete",
            "session_id": session_id,
            "symptoms_summary": analysis.get("symptoms_summary", user_message),
            "report_findings": report_findings,
            "combined_analysis": analysis.get("combined_analysis", ""),
            "urgency_level": analysis.get("urgency_level", "MEDIUM"),
            "recommended_department": normalized_dept,
            "differential_considered": analysis.get("differential_considered", []),
            "ruled_out_reason": analysis.get("ruled_out_reason", ""),
            "sub_department": analysis.get("sub_department", None),
            "do_not_delay": analysis.get("do_not_delay", False),
            "follow_up_question": follow_up if needs_followup else None,
            "reasoning": analysis.get("reasoning", ""),
            "red_flags": analysis.get("red_flags", []),
            "disclaimer": "This is AI guidance only. Always consult a qualified doctor.",
            "confidence": analysis.get("confidence", "MEDIUM"),
            "language": language
        }

    except Exception as e:
        log(f"Gemini failed - using keyword fallback. Error: {str(e)}")
        fallback = keyword_fallback(user_message)
        
        if language == "roman_urdu":
            follow_up = "Kya aap apni takleef ke baare mein aur tafseel bata sakte hain?"
        elif language == "urdu":
            follow_up = "کیا آپ اپنی تکلیف کے بارے میں مزید تفصیل بتا سکتے ہیں؟"
        else:
            follow_up = get_follow_up_question(user_message)
        log(f"Fallback department: {fallback['department']}")
        log("JSON handoff ready -> Main Agent")
        return {
            "agent": "symptom_report_agent",
            "status": "needs_followup" if follow_up else "complete",
            "session_id": session_id,
            "symptoms_summary": user_message,
            "report_findings": report_findings,
            "combined_analysis": "Basic analysis using keyword matching (AI temporarily unavailable).",
            "urgency_level": fallback["urgency"],
            "recommended_department": fallback["department"],
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
