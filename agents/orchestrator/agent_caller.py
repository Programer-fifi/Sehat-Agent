"""
agent_caller.py  —  FIXED VERSION
────────────────────────────────────────────────────────────────
FIXES:
  FIX-1  Sequential chain: Hospital Finder → Appointment Agent
          (appointment agent gets hospital_name from hospital finder output)
  FIX-2  Structured payload per agent — each agent gets what IT needs
  FIX-3  call_agents_sequential() added for chained flows
  FIX-4  Timeout increased to 45s for slow Gemini calls
"""

import requests
import concurrent.futures

AGENT_TIMEOUT = 45  # FIX-4: was 30s


# ── Port → Path mapping ───────────────────────────────────────────────────────

PORT_PATHS = {
    5001: "/symptom-agent/analyze",
    5002: "/analyze",   # hospital finder
    5003: "/analyze",   # cost agent
    5004: "/analyze",   # appointment agent
    5005: "/analyze",   # validator
}


def call_agent(port, payload, log_trace):
    """Call a single agent. Returns JSON response or graceful error dict."""
    path = PORT_PATHS.get(port, "/analyze")
    url  = f"http://localhost:{port}{path}"
    log_trace(f"Calling agent on port {port} at {url}...")

    try:
        response = requests.post(url, json=payload, timeout=AGENT_TIMEOUT)
        response.raise_for_status()
        log_trace(f"Received successful response from agent on port {port}")
        return response.json()

    except requests.exceptions.Timeout:
        log_trace(f"Agent on port {port} timed out after {AGENT_TIMEOUT}s")
        return {"error": f"Agent on port {port} timed out", "port": port, "timed_out": True}

    except requests.exceptions.ConnectionError:
        log_trace(f"Agent on port {port} is not running or unreachable")
        return {"error": f"Agent on port {port} is not running", "port": port, "connection_failed": True}

    except requests.exceptions.HTTPError as e:
        log_trace(f"Agent on port {port} returned HTTP error: {str(e)}")
        return {"error": f"HTTP error from port {port}: {str(e)}", "port": port, "http_error": True}

    except Exception as e:
        log_trace(f"Unexpected error calling agent on port {port}: {str(e)}")
        return {"error": f"Unexpected error for agent {port}", "port": port, "details": str(e)}


def call_agents_parallel(ports, payload, log_trace):
    """
    Call multiple agents simultaneously.
    Returns dict of {port: response}.
    """
    agent_outputs = {}
    if not ports:
        return agent_outputs

    log_trace(f"Dispatching payloads to agents in parallel")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(ports))) as executor:
        future_to_port = {
            executor.submit(call_agent, port, payload, log_trace): port
            for port in ports
        }
        for future in concurrent.futures.as_completed(future_to_port):
            port = future_to_port[future]
            try:
                agent_outputs[port] = future.result()
            except Exception as e:
                log_trace(f"Agent {port} exception: {e}")
                agent_outputs[port] = {"error": str(e), "port": port}

    return agent_outputs


# ── FIX-1: Sequential chain for appointment flow ──────────────────────────────

def call_agents_sequential_appointment(base_payload, log_trace):
    """
    FIX-1: Sequential chain specifically for APPOINTMENT_NEEDED intent.

    Step 1 → Hospital Finder (5002): find hospital + department
    Step 2 → Validator (5005): validate hospital output
    Step 3 → Cost Agent (5003) + Appointment Agent (5004) in parallel
             Both get hospital_name, department, hospital_type from Step 1/2

    Returns dict of {port: response} same shape as call_agents_parallel.
    """
    agent_outputs = {}
    user_message  = base_payload.get("user_message", "")
    language      = base_payload.get("language", "roman_urdu")

    # UI-provided city/area take priority; fall back to keyword extraction
    city_from_ui  = base_payload.get("city", "").strip()
    area_from_ui  = base_payload.get("area", "").strip()
    resolved_city = city_from_ui or _extract_city_hint(user_message)

    # ── Step 1: Hospital Finder ───────────────────────────────────────────────
    log_trace("Sequential Step 1: Hospital Finder (port 5002)")

    hospital_payload = {
        **base_payload,
        "department":    _extract_department_hint(user_message),
        "city":          resolved_city,
        "area":          area_from_ui,
        "urgency_level": "routine",
        "hospital_type": _extract_hospital_type_hint(user_message),
        "raw_input":     user_message,
    }

    hospital_result = call_agent(5002, hospital_payload, log_trace)
    agent_outputs[5002] = hospital_result

    # ── CRASH FALLBACK: If hospital agent failed, use smart defaults ──────────
    hospital_crashed = (
        bool(hospital_result.get("error")) or
        bool(hospital_result.get("connection_failed")) or
        bool(hospital_result.get("timed_out")) or
        not hospital_result.get("hospital_name")
    )
    if hospital_crashed:
        log_trace("Hospital Finder crashed/unavailable — using smart fallback")
        hospital_name = _extract_hospital_name_from_message(user_message) or "Nearest Available Hospital"
        department    = _extract_department_hint(user_message)
        hospital_type = _extract_hospital_type_hint(user_message) or "any"
        urgency_level = "routine"
        visit_type    = "OPD"
        agent_outputs[5002] = {
            "agent":         "hospital_finder_agent",
            "hospital_name": hospital_name,
            "hospital_type": hospital_type,
            "department":    department,
            "urgency_level": urgency_level,
            "visit_type":    visit_type,
            "top_recommendation": {
                "name":      hospital_name,
                "address":   "Please search on Google Maps",
                "phone":     "1122",
                "maps_link": f"https://maps.google.com/?q={department}+hospital+Pakistan",
                "rating":    "N/A",
                "type":      hospital_type,
                "emergency": False,
                "distance":  "Nearest available",
            },
            "alternatives": [],
            "reasoning":    f"Orchestrator fallback — hospital agent unavailable. Dept: {department}",
            "source":       "orchestrator_fallback",
        }
    else:
        hospital_name = _extract_hospital_name(hospital_result, user_message)
        department    = _extract_dept_from_result(hospital_result)
        hospital_type = hospital_result.get("hospital_type", "private")
        urgency_level = hospital_result.get("urgency_level", "routine")
        visit_type    = hospital_result.get("visit_type", "OPD")

    log_trace(f"Hospital: {hospital_name} | dept: {department} | crashed: {hospital_crashed}")

    # ── Step 2: Validator (optional — skip if hospital finder failed) ─────────
    validation_passed = True
    if not hospital_result.get("error") and hospital_result.get("top_recommendation"):
        log_trace("Sequential Step 2: Validator (port 5005)")
        validator_payload = {
            "hospital_finder_output": hospital_result,
            "original_request": {
                "department":       department,
                "urgency_level":    urgency_level,
                "raw_input":        user_message,
            },
        }
        validator_result = call_agent(5005, validator_payload, log_trace)
        agent_outputs[5005] = validator_result

        # Use validated hospital name if approved
        v_status = validator_result.get("validation_status", "")
        if v_status in ("APPROVED", "APPROVED_WITH_WARNINGS"):
            approved = validator_result.get("approved_recommendation", {})
            if approved and approved.get("name"):
                hospital_name = approved["name"]
                log_trace(f"Validator approved: {hospital_name}")
        elif v_status == "REJECTED":
            log_trace("Validator REJECTED — using original hospital finder result")
    else:
        log_trace("Skipping validator (hospital finder error or no recommendation)")

    # ── Step 3: Cost + Appointment in parallel (both get enriched payload) ────
    log_trace("Sequential Step 3: Cost Agent (5003) + Appointment Agent (5004) in parallel")

    enriched_payload = {
        **base_payload,
        # FIX-2: Structured fields each agent needs
        "hospital_name":          hospital_name,
        "department":             department,
        "recommended_department": department,
        "hospital_type":          hospital_type,
        "urgency_level":          urgency_level,
        "visit_type":             visit_type,
        "raw_input":              user_message,
    }

    parallel_results = call_agents_parallel([5003, 5004], enriched_payload, log_trace)
    agent_outputs.update(parallel_results)

    return agent_outputs


def call_agents_sequential_hospital_only(base_payload, log_trace):
    """
    Sequential flow for HOSPITAL_NEEDED + COST_INQUIRY.
    Step 1 → Hospital Finder (5002)
    Step 2 → Cost Agent (5003) with hospital details
    """
    agent_outputs = {}
    user_message  = base_payload.get("user_message", "")

    # UI-provided city/area take priority; fall back to keyword extraction
    city_from_ui  = base_payload.get("city", "").strip()
    area_from_ui  = base_payload.get("area", "").strip()
    resolved_city = city_from_ui or _extract_city_hint(user_message)

    # Step 1: Hospital Finder
    log_trace("Sequential Step 1: Hospital Finder (port 5002)")
    hospital_payload = {
        **base_payload,
        "department":    _extract_department_hint(user_message),
        "city":          resolved_city,
        "area":          area_from_ui,
        "urgency_level": "routine",
        "hospital_type": _extract_hospital_type_hint(user_message),
        "raw_input":     user_message,
    }
    hospital_result = call_agent(5002, hospital_payload, log_trace)
    agent_outputs[5002] = hospital_result

    # ── CRASH FALLBACK for hospital_only flow ────────────────────────────────
    if hospital_result.get("error") or hospital_result.get("connection_failed") or not hospital_result.get("hospital_name"):
        log_trace("Hospital Finder unavailable — cost agent will use dept-based estimate")
        hospital_name = _extract_hospital_name_from_message(user_message) or "Nearest Hospital"
        department    = _extract_department_hint(user_message)
        hospital_type = _extract_hospital_type_hint(user_message) or "any"
        urgency_level = "routine"
        visit_type    = "OPD"
    else:
        hospital_name = _extract_hospital_name(hospital_result, user_message)
        department    = _extract_dept_from_result(hospital_result)
        hospital_type = hospital_result.get("hospital_type", "private")
        urgency_level = hospital_result.get("urgency_level", "routine")
        visit_type    = hospital_result.get("visit_type", "OPD")

    log_trace(f"Hospital: {hospital_name} | dept: {department}")

    # Step 2: Cost Agent with enriched payload
    log_trace("Sequential Step 2: Cost Agent (port 5003)")
    cost_payload = {
        **base_payload,
        "hospital_name":          hospital_name,
        "department":             department,
        "recommended_department": department,
        "hospital_type":          hospital_type,
        "urgency_level":          urgency_level,
        "visit_type":             visit_type,
    }
    cost_result = call_agent(5003, cost_payload, log_trace)
    agent_outputs[5003] = cost_result

    return agent_outputs


# ── Helper: Extract hints from user message ───────────────────────────────────

CITY_HINTS = {
    "karachi": "karachi", "khi": "karachi",
    "lahore": "lahore",   "lhr": "lahore",
    "islamabad": "islamabad", "isb": "islamabad",
    "rawalpindi": "rawalpindi", "pindi": "rawalpindi",
    "peshawar": "peshawar",
    "multan": "multan", "faisalabad": "faisalabad", "quetta": "quetta",
}

DEPT_HINTS = {
    # Cardiology
    "cardio": "Cardiology", "heart": "Cardiology", "dil": "Cardiology",
    "cardiac": "Cardiology", "seena": "Cardiology", "dil ka": "Cardiology",
    # Neurology
    "neuro": "Neurology", "brain": "Neurology", "dimagh": "Neurology",
    "sar dard": "Neurology", "paralysis": "Neurology",
    # Oncology
    "cancer": "Oncology", "oncology": "Oncology", "tumor": "Oncology",
    # Orthopedics
    "ortho": "Orthopedics", "bone": "Orthopedics", "haddi": "Orthopedics",
    "joint": "Orthopedics", "joron": "Orthopedics", "fracture": "Orthopedics",
    # Pediatrics
    "child": "Pediatrics", "bacha": "Pediatrics", "bachcha": "Pediatrics",
    "paeds": "Pediatrics", "pediatric": "Pediatrics", "baby": "Pediatrics",
    "infant": "Pediatrics", "bachon": "Pediatrics",
    # Gynecology — EXPANDED (was missing gyni, gyne, gynecology)
    "gynae": "Gynecology", "gyne": "Gynecology", "gyni": "Gynecology",
    "gynecology": "Gynecology", "gynaecology": "Gynecology",
    "women": "Gynecology", "aurat": "Gynecology", "hamal": "Gynecology",
    "pregnancy": "Gynecology", "delivery": "Gynecology", "obs": "Gynecology",
    "maternity": "Gynecology", "period": "Gynecology", "mahwari": "Gynecology",
    # Dermatology
    "skin": "Dermatology", "jild": "Dermatology", "derma": "Dermatology",
    "rash": "Dermatology", "kharish": "Dermatology", "daane": "Dermatology",
    # Ophthalmology
    "eye": "Ophthalmology", "aankh": "Ophthalmology", "ophthal": "Ophthalmology",
    "vision": "Ophthalmology", "aankhon": "Ophthalmology",
    # Urology
    "kidney": "Urology", "urology": "Urology", "urine": "Urology",
    "peshab": "Urology", "gurda": "Urology",
    # ENT
    "ent": "ENT", "ear": "ENT", "kaan": "ENT", "nose": "ENT",
    "naak": "ENT", "throat": "ENT", "gala": "ENT",
    # Psychiatry
    "psych": "Psychiatry", "mental": "Psychiatry", "dimagi": "Psychiatry",
    "anxiety": "Psychiatry", "depression": "Psychiatry",
    # Endocrinology
    "diabetes": "Endocrinology", "sugar": "Endocrinology", "thyroid": "Endocrinology",
    "endocrine": "Endocrinology",
    # Gastroenterology
    "gastro": "Gastroenterology", "stomach": "Gastroenterology", "pet": "Gastroenterology",
    "liver": "Gastroenterology", "diarrhea": "Gastroenterology", "ulcer": "Gastroenterology",
    # Pulmonology
    "lung": "Pulmonology", "phephra": "Pulmonology", "asthma": "Pulmonology",
    "cough": "Pulmonology", "khansi": "Pulmonology", "breathing": "Pulmonology",
    # General Medicine — DEFAULT
    "general": "General Medicine", "fever": "General Medicine",
    "bukhar": "General Medicine", "flu": "General Medicine",
    "zukam": "General Medicine", "cold": "General Medicine",
}

HOSPITAL_TYPE_HINTS = {
    "government": "government", "govt": "government", "sarkari": "government",
    "private": "private", "niji": "private",
}

# Known hospital names in user messages
HOSPITAL_NAME_HINTS = {
    "aga khan":    "Aga Khan University Hospital",
    "aku":         "Aga Khan University Hospital",
    "nicvd":       "National Institute of Cardiovascular Diseases (NICVD)",
    "kihd":        "Karachi Institute of Heart Diseases (KIHD)",
    "tabba":       "Tabba Heart Institute",
    "jpmc":        "Jinnah Postgraduate Medical Centre (JPMC)",
    "jinnah":      "Jinnah Postgraduate Medical Centre (JPMC)",
    "civil hospital": "Civil Hospital Karachi",
    "liaquat":     "Liaquat National Hospital",
    "shaukat khanum": "Shaukat Khanum Memorial Cancer Hospital",
    "pims":        "Pakistan Institute of Medical Sciences (PIMS)",
    "shifa":       "Shifa International Hospital",
    "services hospital": "Services Hospital Lahore",
    "mayo":        "Mayo Hospital Lahore",
    "holy family": "Holy Family Hospital",
    "lady reading": "Lady Reading Hospital",
    "khyber teaching": "Khyber Teaching Hospital",
    "nich":        "National Institute of Child Health (NICH)",
    "dow":         "Dow University Hospital",
    "duhs":        "Dow University Hospital",
    "dow hospital": "Dow University Hospital",
    "pic":         "Punjab Institute of Cardiology (PIC)",
    "hameed latif": "Hameed Latif Hospital",
}


def _extract_city_hint(text: str) -> str:
    text_lower = text.lower()
    for kw, city in CITY_HINTS.items():
        if kw in text_lower:
            return city
    return ""


def _extract_department_hint(text: str) -> str:
    text_lower = text.lower()
    for kw, dept in DEPT_HINTS.items():
        if kw in text_lower:
            return dept
    return "General Medicine"


def _extract_hospital_type_hint(text: str) -> str:
    text_lower = text.lower()
    for kw, h_type in HOSPITAL_TYPE_HINTS.items():
        if kw in text_lower:
            return h_type
    return "any"


def _extract_hospital_name_from_message(text: str) -> str | None:
    """Extract explicitly mentioned hospital name from user message."""
    text_lower = text.lower()
    for kw, name in HOSPITAL_NAME_HINTS.items():
        if kw in text_lower:
            return name
    return None


def _extract_hospital_name(hospital_result: dict, user_message: str) -> str:
    """
    Get hospital name — priority:
    1. Explicitly mentioned in user message
    2. Hospital finder top_recommendation
    3. hospital_finder hospital_name field
    4. Safe default
    """
    # Priority 1: User explicitly said hospital name
    from_msg = _extract_hospital_name_from_message(user_message)
    if from_msg:
        return from_msg

    # Priority 2: Hospital finder top_recommendation
    top = hospital_result.get("top_recommendation", {})
    if isinstance(top, dict) and top.get("name"):
        return top["name"]

    # Priority 3: hospital_name field
    if hospital_result.get("hospital_name"):
        return hospital_result["hospital_name"]

    return "Aga Khan University Hospital"


def _extract_dept_from_result(hospital_result: dict) -> str:
    return (
        hospital_result.get("department") or
        hospital_result.get("recommended_department") or
        "General Medicine"
    )