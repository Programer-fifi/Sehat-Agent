"""
orchestrator/orchestrator.py  —  UPDATED VERSION
────────────────────────────────────────────────────────────────
UPDATES (on top of existing fixes):
  UPDATE-1  process_request() now accepts city= and area= kwargs
            → Passed in from orchestrator_server from the UI location selector
  UPDATE-2  city/area injected into base_payload so all agent callers
            automatically send it to hospital finder agent
  UPDATE-3  If city not provided, falls back to keyword detection as before

All original FIX-1 through FIX-7 logic preserved unchanged.
"""

import os
import time
from datetime import datetime

from google import genai
from agent_caller import (
    call_agent,
    call_agents_parallel,
    call_agents_sequential_appointment,
    call_agents_sequential_hospital_only,
    _extract_department_hint,
    _extract_city_hint,
    _extract_hospital_type_hint,
    _extract_hospital_name_from_message,
)
from response_combiner import combine_responses


# ── Fallback Intent Detection ─────────────────────────────────────────────────

def fallback_intent(text: str) -> str:
    """
    FIX-6: Keyword-based intent — runs when Gemini quota exhausted.
    Emergency checked FIRST (highest priority).
    """
    t = text.lower()

    # ── EMERGENCY — always first ──────────────────────────────────────────────
    emergency_kw = [
        "emergency", "heart attack", "bleeding", "stroke", "dying",
        "unconscious", "heat stroke", "heatstroke", "snake bite",
        "accident", "seizure", "head injury", "poison",
        "not breathing", "ambulance", "help fast",
        "behosh", "behoshi", "hosh nahi", "hosh kho",
        "dil ka daura", "dil ka dora",
        "saanp ne kaata", "saanp kata",
        "hadsa", "haadsa",
        "khoon nahi ruk", "khoon band nahi",
        "fit agai", "fitting", "mirgi",
        "sar pe chot", "sar ki chot",
        "zeher", "zahar",
        "saans nahi", "saans ruk",
        "mar raha", "mar rahi", "maut",
        "coma",
    ]
    if any(kw in t for kw in emergency_kw):
        return "EMERGENCY"

    # ── APPOINTMENT ───────────────────────────────────────────────────────────
    appt_kw = [
        "appointment", "book", "schedule", "booking",
        "milna hai", "time lena", "time chahiye",
        "slot", "token", "register",
        "mujhe agha khan", "mujhe shifa", "mujhe pims",
        "mujhe nicvd", "mujhe civil", "mujhe liaquat",
        "hospital main appointment", "hospital mein appointment",
    ]
    if any(kw in t for kw in appt_kw):
        return "APPOINTMENT_NEEDED"

    # ── HOSPITAL SEARCH ───────────────────────────────────────────────────────
    hospital_kw = [
        "hospital", "clinic", "where to go", "kahan jaun",
        "nearest", "qareeb", "aspatal", "location",
        "konsa hospital", "kaun sa hospital",
        "kareeb hospital", "nazdeek hospital",
        "cardiology department kahan", "department kahan milega",
    ]
    if any(kw in t for kw in hospital_kw):
        return "HOSPITAL_NEEDED"

    # ── COST ──────────────────────────────────────────────────────────────────
    cost_kw = [
        "cost", "price", "fee", "fees", "charge", "charges",
        "kitna paisa", "kitni fees", "payment", "expensive",
        "kitna lagega", "kharch", "paisa kitna",
    ]
    if any(kw in t for kw in cost_kw):
        return "COST_INQUIRY"

    # ── REPORT ────────────────────────────────────────────────────────────────
    report_kw = [
        "report", "lab", "test result", "xray", "x-ray",
        "mri", "ultrasound", "cbc", "blood test", "scan", "result",
    ]
    if any(kw in t for kw in report_kw):
        return "REPORT_ANALYSIS"

    return "SYMPTOM_ONLY"


# ── Gemini Intent Detection ───────────────────────────────────────────────────

def detect_intent(user_message: str, trace_logs: list) -> str:
    """
    FIX-7: Gemini-based intent — falls back to keyword matching on any failure.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY_2")
    if not api_key:
        trace_logs.append(f"[MAIN AGENT] {_ts()} No API key — using fallback intent")
        return fallback_intent(user_message)

    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""
Analyze this user message and classify intent into EXACTLY ONE of these categories:
SYMPTOM_ONLY, HOSPITAL_NEEDED, APPOINTMENT_NEEDED, REPORT_ANALYSIS,
COST_INQUIRY, FULL_SERVICE, EMERGENCY

Rules:
- EMERGENCY: severe medical emergency (heart attack, unconscious, severe bleeding,
  stroke, poisoning, accident, not breathing, behosh, dil ka daura)
- SYMPTOM_ONLY: describing symptoms, asking about illness
- HOSPITAL_NEEDED: wants to find a hospital/clinic, asking where to go
- APPOINTMENT_NEEDED: wants to book/schedule an appointment at a specific or any hospital
- REPORT_ANALYSIS: uploading or mentioning a medical report/lab result
- COST_INQUIRY: asking about fees, costs, charges
- FULL_SERVICE: asking for multiple things simultaneously

User Message: {user_message}

Output ONLY the category name. Nothing else.
"""
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        intent = response.text.strip().upper()
        valid = {"SYMPTOM_ONLY", "HOSPITAL_NEEDED", "APPOINTMENT_NEEDED",
                 "REPORT_ANALYSIS", "COST_INQUIRY", "FULL_SERVICE", "EMERGENCY"}

        if intent not in valid:
            trace_logs.append(f"[MAIN AGENT] {_ts()} Invalid Gemini intent '{intent}' — fallback")
            return fallback_intent(user_message)

        return intent

    except Exception as e:
        trace_logs.append(f"[MAIN AGENT] {_ts()} Gemini API error (fallback triggered): {str(e)}")
        return fallback_intent(user_message)


def _ts():
    return datetime.now().strftime("%H:%M:%S")


# ── Main Orchestration ────────────────────────────────────────────────────────

def process_request(
    user_message,
    session_id,
    report_image=None,
    conversation_history=None,
    language="roman_urdu",
    city="",        # UPDATE-1: city from UI location selector
    area="",        # UPDATE-1: area from UI location selector
):
    start_time = time.time()
    trace_logs = []

    def log_trace(message):
        msg = f"[MAIN AGENT] {_ts()} {message}"
        print(msg)
        trace_logs.append(msg)

    log_trace(f"Starting orchestration for session {session_id}")

    # UPDATE-2: Resolve city — UI selection takes priority over keyword detection
    resolved_city = city.strip().lower() if city and city.strip() else _extract_city_hint(user_message)
    resolved_area = area.strip() if area and area.strip() else ""

    if resolved_city:
        log_trace(f"Location: city='{resolved_city}' area='{resolved_area}'")
    else:
        log_trace("No city provided — agents will use keyword detection")

    # ── Detect Intent ─────────────────────────────────────────────────────────
    intent = detect_intent(user_message, trace_logs)
    log_trace(f"Detected intent: {intent}")

    # ── Base payload ──────────────────────────────────────────────────────────
    # UPDATE-2: city and area always included so hospital finder gets them
    base_payload = {
        "session_id":            session_id,
        "user_message":          user_message,
        "conversation_history":  conversation_history or [],
        "language":              language,
        "raw_input":             user_message,
        "city":                  resolved_city,   # ← from UI selector
        "area":                  resolved_area,   # ← from UI selector
    }
    if report_image:
        base_payload["report_image"] = report_image

    # ── Route by Intent ───────────────────────────────────────────────────────
    agent_outputs = {}

    # ── SYMPTOM_ONLY ──────────────────────────────────────────────────────────
   if intent in ("SYMPTOM_ONLY", "REPORT_ANALYSIS"):
        log_trace("Flow: Symptom Agent → Hospital Finder → Cost Agent")
        symptom_result = call_agent(5001, base_payload, log_trace)
        agent_outputs[5001] = symptom_result

        symptom_dept = symptom_result.get("recommended_department") or _extract_department_hint(user_message)
        symptom_urgency = symptom_result.get("urgency_level", "routine") or "routine"

        enriched = {
            **base_payload,
            "department": symptom_dept,
            "urgency_level": symptom_urgency,
            "hospital_type": "any",
        }

        hospital_result = call_agent(5002, enriched, log_trace)
        agent_outputs[5002] = hospital_result

        hospital_name = _extract_hospital_name(hospital_result, user_message)

        cost_payload = {
            **base_payload,
            "department": symptom_dept,
            "recommended_department": symptom_dept,
            "urgency_level": symptom_urgency,
            "hospital_name": hospital_name,
            "hospital_type": "any",
            "visit_type": "OPD",
        }
        cost_result = call_agent(5003, cost_payload, log_trace)
        agent_outputs[5003] = cost_result
    # ── HOSPITAL_NEEDED ───────────────────────────────────────────────────────
    elif intent == "HOSPITAL_NEEDED":
        log_trace("Flow: Sequential — Hospital Finder → Cost Agent")
        agent_outputs = call_agents_sequential_hospital_only(base_payload, log_trace)

    # ── APPOINTMENT_NEEDED ────────────────────────────────────────────────────
    elif intent == "APPOINTMENT_NEEDED":
        log_trace("Flow: Sequential — Hospital Finder → Validator → Cost + Appointment")
        specific_hospital = _extract_hospital_name_from_message(user_message)
        if specific_hospital:
            log_trace(f"User mentioned specific hospital: {specific_hospital}")
        agent_outputs = call_agents_sequential_appointment(base_payload, log_trace)

    # ── COST_INQUIRY ──────────────────────────────────────────────────────────
    elif intent == "COST_INQUIRY":
        log_trace("Flow: Sequential — Hospital Finder → Cost Agent")
        agent_outputs = call_agents_sequential_hospital_only(base_payload, log_trace)

    # ── FULL_SERVICE ──────────────────────────────────────────────────────────
    elif intent == "FULL_SERVICE":
        log_trace("Flow: Symptom Agent → Sequential Appointment Chain")
        symptom_result = call_agent(5001, base_payload, log_trace)
        agent_outputs[5001] = symptom_result

        symptom_dept = (
            symptom_result.get("recommended_department") or
            _extract_department_hint(user_message)
        )
        symptom_urgency = symptom_result.get("urgency_level", "routine")

        enriched = {
            **base_payload,
            "department":    symptom_dept,
            "urgency_level": symptom_urgency,
        }
        chain_results = call_agents_sequential_appointment(enriched, log_trace)
        agent_outputs.update(chain_results)

    # ── EMERGENCY ─────────────────────────────────────────────────────────────
    elif intent == "EMERGENCY":
        log_trace("Flow: EMERGENCY — all agents parallel (speed priority)")
        emergency_payload = {
            **base_payload,
            "urgency_level":          "critical",
            "department":             "Emergency",
            "recommended_department": "Emergency",
            "visit_type":             "Emergency",
            "hospital_type":          "any",
        }
        agent_outputs = call_agents_parallel([5001, 5002, 5003, 5004], emergency_payload, log_trace)

    # ── UNKNOWN ───────────────────────────────────────────────────────────────
    else:
        log_trace(f"Unknown intent '{intent}' — defaulting to symptom only")
        agent_outputs = call_agents_parallel([5001], base_payload, log_trace)

    # ── Combine responses ─────────────────────────────────────────────────────
    agents_used = [f"Agent-{port}" for port in agent_outputs.keys()]
    log_trace("Combining agent responses")

    final_response = combine_responses(
        session_id, intent, agents_used,
        agent_outputs, start_time, trace_logs,
    )
    final_response["agent_trace"] = trace_logs

    return final_response