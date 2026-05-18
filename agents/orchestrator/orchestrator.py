import os
import time
from datetime import datetime
from google import genai
from agent_caller import call_agent, call_agents_parallel
from response_combiner import combine_responses


def fallback_intent(text):
    text = text.lower()
    emergency_keywords = [
        "emergency", "heart attack", "bleeding", "stroke", "dying",
        "help fast", "urgent", "unconscious", "heat stroke", "heatstroke",
        "snake bite", "accident", "seizure", "head injury", "poison",
        "breathing stopped", "ambulance",
        "behosh", "behoshi", "behosh ho gaya", "behosh hogaya",
        "hosh nahi", "hosh kho diya",
        "dil ka daura", "saanp ne kaata", "hadsa",
        "khoon nahi ruk raha", "fit", "fitting",
        "sar pe chot", "zeher", "saans nahi",
        "maut", "mar raha",
    ]
    if any(word in text for word in emergency_keywords):
        return "EMERGENCY"
    elif any(word in text for word in ['book', 'appointment', 'schedule']):
        return "APPOINTMENT_NEEDED"
    elif any(word in text for word in ['hospital', 'clinic', 'where to go', 'location']):
        return "HOSPITAL_NEEDED"
    elif any(word in text for word in ['cost', 'price', 'fee', 'expensive', 'charge']):
        return "COST_INQUIRY"
    elif any(word in text for word in ['report', 'lab', 'test', 'result', 'xray', 'mri']):
        return "REPORT_ANALYSIS"
    return "SYMPTOM_ONLY"


def detect_intent(user_message, trace_logs):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        msg = f"[MAIN AGENT] {datetime.now().strftime('%H:%M:%S')} GEMINI_API_KEY not found. Using fallback."
        print(msg)
        trace_logs.append(msg)
        return fallback_intent(user_message)

    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""
Analyze the following user message and classify its intent into EXACTLY ONE of the following categories:
SYMPTOM_ONLY, HOSPITAL_NEEDED, APPOINTMENT_NEEDED, REPORT_ANALYSIS, COST_INQUIRY, FULL_SERVICE, EMERGENCY.

Rules for classification:
- If it's a severe medical emergency (heart attack, severe bleeding, stroke, etc.), classify as EMERGENCY.
- If they only want to know about symptoms or diseases, classify as SYMPTOM_ONLY.
- If they want to find a hospital, classify as HOSPITAL_NEEDED.
- If they want to book an appointment, classify as APPOINTMENT_NEEDED.
- If they upload or mention a medical report, classify as REPORT_ANALYSIS.
- If they ask about costs or prices, classify as COST_INQUIRY.
- If they ask for multiple things (e.g., symptoms AND booking an appointment), classify as FULL_SERVICE.

User Message: {user_message}

Output ONLY the category name. No other text.
"""
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        intent = response.text.strip().upper()
        valid_intents = [
            "SYMPTOM_ONLY", "HOSPITAL_NEEDED", "APPOINTMENT_NEEDED",
            "REPORT_ANALYSIS", "COST_INQUIRY", "FULL_SERVICE", "EMERGENCY"
        ]
        if intent not in valid_intents:
            return fallback_intent(user_message)
        return intent
    except Exception as e:
        msg = f"[MAIN AGENT] {datetime.now().strftime('%H:%M:%S')} Gemini API error (fallback triggered): {str(e)}"
        print(msg)
        trace_logs.append(msg)
        return fallback_intent(user_message)


def process_request(user_message, session_id, report_image=None, conversation_history=None):
    start_time = time.time()
    trace_logs = []

    def log_trace(message):
        log_msg = f"[MAIN AGENT] {datetime.now().strftime('%H:%M:%S')} {message}"
        print(log_msg)
        trace_logs.append(log_msg)

    log_trace(f"Starting orchestration for session {session_id}")

    intent = detect_intent(user_message, trace_logs)
    log_trace(f"Detected intent: {intent}")

    # Base payload sent to all agents
    base_payload = {
        "session_id": session_id,
        "user_message": user_message,
        "conversation_history": conversation_history or []
    }
    if report_image:
        base_payload["report_image"] = report_image

    agent_outputs = {}
    agents_used = []

    # ── PHASE 1: Always call Symptom Agent first (port 5001) ─────────────────
    # We need its output (department, urgency) to feed hospital finder
    # and appointment agent correctly.
    if intent not in ("COST_INQUIRY",):
        log_trace("Phase 1: Calling Symptom Agent (5001)...")
        symptom_out = call_agent(5001, base_payload, log_trace)
        agent_outputs[5001] = symptom_out
        agents_used.append("Agent-5001")
    else:
        # Cost inquiry — still call symptom agent for department context
        log_trace("Phase 1: Calling Symptom Agent (5001) for department context...")
        symptom_out = call_agent(5001, base_payload, log_trace)
        agent_outputs[5001] = symptom_out
        agents_used.append("Agent-5001")

    # Extract symptom agent results to enrich downstream payloads
    recommended_department = "General Medicine"
    urgency_level = "urgent"
    hospital_name = "Aga Khan University Hospital"

    if symptom_out and not symptom_out.get("error"):
        recommended_department = symptom_out.get("recommended_department", "General Medicine")
        raw_urgency = symptom_out.get("urgency_level", "MEDIUM").lower()
        urgency_map = {
            "low": "routine",
            "medium": "urgent",
            "high": "urgent",
            "critical": "emergency",
            "emergency": "emergency",
        }
        urgency_level = urgency_map.get(raw_urgency, "urgent")
        log_trace(f"Symptom Agent → Department: {recommended_department}, Urgency: {urgency_level}")

    # ── EMERGENCY OVERRIDE: force correct dept/urgency regardless of symptom agent ──
    if intent == "EMERGENCY":
        recommended_department = "Emergency"
        urgency_level = "emergency"
        log_trace("EMERGENCY intent → overriding department=Emergency, urgency=emergency")

    # ── PHASE 2: Determine which agents to call ───────────────────────────────
    needs_hospital  = intent in ("HOSPITAL_NEEDED", "APPOINTMENT_NEEDED", "FULL_SERVICE", "EMERGENCY")
    needs_cost      = intent in ("COST_INQUIRY", "FULL_SERVICE", "EMERGENCY")
    needs_appt      = intent in ("APPOINTMENT_NEEDED", "FULL_SERVICE", "EMERGENCY")

    import concurrent.futures

    # ── PHASE 2a: Hospital Finder runs FIRST (appointment agent depends on it) ─
    if needs_hospital:
        log_trace("Phase 2a: Calling Hospital Finder (5002)...")
        hospital_payload = {
            **base_payload,
            "recommended_department": recommended_department,
            "urgency_level": urgency_level,
        }
        hosp_out = call_agent(5002, hospital_payload, log_trace)
        agent_outputs[5002] = hosp_out
        agents_used.append("Agent-5002")

        # Extract the actual recommended hospital name for downstream agents
        if hosp_out and not hosp_out.get("error"):
            top_rec = hosp_out.get("top_recommendation", {})
            hospital_name = top_rec.get("name", hospital_name)
            log_trace(f"Hospital Finder → Top hospital: {hospital_name}")

    # ── PHASE 2b: Cost + Appointment run in parallel after hospital finder ─────
    phase2b_ports = []
    if needs_cost:
        phase2b_ports.append(5003)
    if needs_appt:
        phase2b_ports.append(5004)

    if phase2b_ports:
        log_trace(f"Phase 2b: Calling agents {phase2b_ports} with resolved hospital name...")

        cost_payload = {
            **base_payload,
            "recommended_department": recommended_department,
            "urgency_level": urgency_level,
            "hospital_type": "private",
            "visit_type": "OPD",
        }
        appointment_payload = {
            **base_payload,
            "hospital_name": hospital_name,
            "department": recommended_department,
            "urgency_level": urgency_level,
            "patient_name": "Patient",
            "recommended_department": recommended_department,
        }

        port_payloads = {}
        for port in phase2b_ports:
            if port == 5003:
                port_payloads[port] = cost_payload
            elif port == 5004:
                port_payloads[port] = appointment_payload
            else:
                port_payloads[port] = base_payload

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(phase2b_ports)) as executor:
            future_to_port = {
                executor.submit(call_agent, port, port_payloads[port], log_trace): port
                for port in phase2b_ports
            }
            for future in concurrent.futures.as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    agent_outputs[port] = future.result()
                    agents_used.append(f"Agent-{port}")
                except Exception as e:
                    log_trace(f"Agent {port} exception: {e}")
                    agent_outputs[port] = {"error": True, "message": str(e)}

    # ── Validator Agent (5005) ────────────────────────────────────────────────
    if needs_hospital and 5002 in agent_outputs:
        hospital_output = agent_outputs.get(5002, {})

        original_request = {
            "required_department": recommended_department,
            "urgency_level": urgency_level,
            "hospital_preference": "GOVERNMENT"
        }

        log_trace("Calling Validator Agent (5005)...")
        validator_result = call_agent(5005, {
            "hospital_finder_output": hospital_output,
            "original_request": original_request
        }, log_trace)

        validation_status = validator_result.get("validation_status", "UNKNOWN")
        log_trace(f"Validator returned: {validation_status}")

        if validation_status == "REJECTED":
            log_trace(f"Validator REJECTED: {validator_result.get('validator_note', 'No reason')}")
            log_trace("Proceeding with best available result despite rejection")
        elif validation_status == "APPROVED":
            log_trace("Validator APPROVED hospital recommendation ✓")

        agent_outputs[5005] = validator_result
        agents_used.append("Agent-5005")

    # ── Combine all agent responses ───────────────────────────────────────────
    log_trace("Combining agent responses")
    final_response = combine_responses(
        session_id, intent, agents_used, agent_outputs, start_time, trace_logs
    )

    final_response["agent_trace"] = trace_logs
    return final_response