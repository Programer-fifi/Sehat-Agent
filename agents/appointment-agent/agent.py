"""
appointment_agent/agent.py
────────────────────────────────────────────────────────────────
Appointment Agent — Sehat Agent (Pakistan's AI Medical Navigation System)

Receives structured JSON from the orchestrator, selects the best available
appointment slot based on urgency, simulates booking (before/after state),
generates a formatted Patient Pass via Gemini 2.5 Flash, and returns a
strict JSON response.

Expected input (dict or JSON string):
    {
        "hospital_name":  str,            # required
        "department":     str,            # required
        "urgency_level":  str,            # required: "routine"|"urgent"|"critical"|"emergency"
        "patient_name":   str  (optional) # defaults to "Patient"
    }

Returns (dict):
    {
        "token_number":       str,
        "appointment_date":   str,        # "YYYY-MM-DD"
        "appointment_time":   str,        # "HH:MM"
        "hospital":           str,
        "department":         str,
        "patient_pass":       str,        # formatted multi-line Patient Pass
        "booking_status":     str,        # "confirmed" | "failed"
        "before_state":       dict,       # slot state before booking
        "after_state":        dict,       # slot state after booking
        "sms_simulation":     str         # short SMS reminder text
    }
"""

import copy
import json
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from flask_cors import CORS

from google import genai
from google.genai import types as genai_types

# ── Constants ────────────────────────────────────────────────────────────────

MODEL_NAME = "gemini-2.5-flash"

REQUIRED_FIELDS = {"hospital_name", "department", "urgency_level"}

VALID_URGENCY = {"routine", "urgent", "critical", "emergency"}

# Urgency groups: slots picked from earliest available same-day for high urgency
HIGH_URGENCY = {"urgent", "critical", "emergency"}

# ── Mock Slot Database ────────────────────────────────────────────────────────
# Structure:
#   SLOT_DB[hospital_name][department] = list of slot dicts
#   Each slot: { "date": str, "time": str, "available": bool, "token": str }
#
# Dates are computed relative to today so the demo always works regardless of
# when it is run.

def _build_slot_db() -> dict:
    """
    Build the mock slot database with dates relative to today.
    Calling this function each time ensures dates stay current.
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    next_week = today + timedelta(days=7)

    def fmt(d: date) -> str:
        return d.strftime("%Y-%m-%d")

    return {
        "Aga Khan University Hospital": {
            "Cardiology": [
                {"date": fmt(today),      "time": "09:00", "available": True,  "token": "AKU-C-001"},
                {"date": fmt(today),      "time": "11:30", "available": True,  "token": "AKU-C-002"},
                {"date": fmt(today),      "time": "14:00", "available": False, "token": "AKU-C-003"},
                {"date": fmt(tomorrow),   "time": "10:00", "available": True,  "token": "AKU-C-004"},
                {"date": fmt(next_week),  "time": "09:30", "available": True,  "token": "AKU-C-005"},
            ],
            "Neurology": [
                {"date": fmt(today),      "time": "10:00", "available": False, "token": "AKU-N-001"},
                {"date": fmt(today),      "time": "12:00", "available": True,  "token": "AKU-N-002"},
                {"date": fmt(tomorrow),   "time": "09:00", "available": True,  "token": "AKU-N-003"},
                {"date": fmt(next_week),  "time": "11:00", "available": True,  "token": "AKU-N-004"},
            ],
            "General Medicine": [
                {"date": fmt(today),      "time": "08:30", "available": True,  "token": "AKU-G-001"},
                {"date": fmt(today),      "time": "10:30", "available": True,  "token": "AKU-G-002"},
                {"date": fmt(tomorrow),   "time": "08:30", "available": True,  "token": "AKU-G-003"},
            ],
            "Orthopedics": [
                {"date": fmt(today),      "time": "13:00", "available": True,  "token": "AKU-O-001"},
                {"date": fmt(tomorrow),   "time": "15:00", "available": True,  "token": "AKU-O-002"},
                {"date": fmt(day_after),  "time": "10:00", "available": True,  "token": "AKU-O-003"},
            ],
        },
        "Shaukat Khanum Memorial Cancer Hospital": {
            "Oncology": [
                {"date": fmt(today),      "time": "09:30", "available": True,  "token": "SKM-ON-001"},
                {"date": fmt(today),      "time": "11:00", "available": True,  "token": "SKM-ON-002"},
                {"date": fmt(tomorrow),   "time": "10:00", "available": True,  "token": "SKM-ON-003"},
                {"date": fmt(next_week),  "time": "09:00", "available": True,  "token": "SKM-ON-004"},
            ],
            "Radiology": [
                {"date": fmt(today),      "time": "08:00", "available": False, "token": "SKM-R-001"},
                {"date": fmt(today),      "time": "10:00", "available": True,  "token": "SKM-R-002"},
                {"date": fmt(tomorrow),   "time": "09:00", "available": True,  "token": "SKM-R-003"},
            ],
            "General Medicine": [
                {"date": fmt(today),      "time": "09:00", "available": True,  "token": "SKM-G-001"},
                {"date": fmt(tomorrow),   "time": "09:00", "available": True,  "token": "SKM-G-002"},
            ],
        },
        "Jinnah Postgraduate Medical Centre": {
            "Emergency": [
                {"date": fmt(today),      "time": "08:00", "available": True,  "token": "JPMC-E-001"},
                {"date": fmt(today),      "time": "09:00", "available": True,  "token": "JPMC-E-002"},
                {"date": fmt(today),      "time": "10:00", "available": True,  "token": "JPMC-E-003"},
                {"date": fmt(today),      "time": "11:00", "available": True,  "token": "JPMC-E-004"},
            ],
            "Cardiology": [
                {"date": fmt(today),      "time": "10:30", "available": True,  "token": "JPMC-C-001"},
                {"date": fmt(tomorrow),   "time": "09:30", "available": True,  "token": "JPMC-C-002"},
                {"date": fmt(next_week),  "time": "10:00", "available": True,  "token": "JPMC-C-003"},
            ],
            "General Medicine": [
                {"date": fmt(today),      "time": "08:00", "available": True,  "token": "JPMC-G-001"},
                {"date": fmt(today),      "time": "09:30", "available": True,  "token": "JPMC-G-002"},
                {"date": fmt(today),      "time": "11:00", "available": False, "token": "JPMC-G-003"},
                {"date": fmt(tomorrow),   "time": "08:30", "available": True,  "token": "JPMC-G-004"},
            ],
            "Orthopedics": [
                {"date": fmt(tomorrow),   "time": "14:00", "available": True,  "token": "JPMC-O-001"},
                {"date": fmt(day_after),  "time": "11:00", "available": True,  "token": "JPMC-O-002"},
            ],
        },
        "Services Hospital Lahore": {
            "General Medicine": [
                {"date": fmt(today),      "time": "08:00", "available": True,  "token": "SHL-G-001"},
                {"date": fmt(today),      "time": "10:00", "available": True,  "token": "SHL-G-002"},
                {"date": fmt(tomorrow),   "time": "09:00", "available": True,  "token": "SHL-G-003"},
            ],
            "Neurology": [
                {"date": fmt(today),      "time": "11:00", "available": True,  "token": "SHL-N-001"},
                {"date": fmt(tomorrow),   "time": "10:00", "available": True,  "token": "SHL-N-002"},
            ],
            "Pediatrics": [
                {"date": fmt(today),      "time": "09:00", "available": True,  "token": "SHL-P-001"},
                {"date": fmt(today),      "time": "11:30", "available": False, "token": "SHL-P-002"},
                {"date": fmt(tomorrow),   "time": "09:30", "available": True,  "token": "SHL-P-003"},
                {"date": fmt(next_week),  "time": "10:00", "available": True,  "token": "SHL-P-004"},
            ],
        },
        "Lady Reading Hospital Peshawar": {
            "General Medicine": [
                {"date": fmt(today),      "time": "08:30", "available": True,  "token": "LRH-G-001"},
                {"date": fmt(today),      "time": "10:30", "available": True,  "token": "LRH-G-002"},
                {"date": fmt(tomorrow),   "time": "09:30", "available": True,  "token": "LRH-G-003"},
            ],
            "Cardiology": [
                {"date": fmt(today),      "time": "09:00", "available": False, "token": "LRH-C-001"},
                {"date": fmt(today),      "time": "12:00", "available": True,  "token": "LRH-C-002"},
                {"date": fmt(tomorrow),   "time": "10:00", "available": True,  "token": "LRH-C-003"},
            ],
            "Orthopedics": [
                {"date": fmt(tomorrow),   "time": "13:00", "available": True,  "token": "LRH-O-001"},
                {"date": fmt(day_after),  "time": "11:00", "available": True,  "token": "LRH-O-002"},
            ],
        },
    }


# Cost estimate placeholders by urgency (PKR)
COST_ESTIMATES = {
    "routine":   "PKR 500 – 1,500",
    "urgent":    "PKR 1,000 – 3,000",
    "critical":  "PKR 2,000 – 8,000",
    "emergency": "PKR 5,000 – 20,000 (may vary)",
}

# Bring checklist by urgency
BRING_CHECKLIST = {
    "routine": [
        "National ID Card (CNIC)",
        "Previous medical records (if any)",
        "Prescription from last visit (if any)",
        "Cash / JazzCash / EasyPaisa for payment",
    ],
    "urgent": [
        "National ID Card (CNIC)",
        "All recent medical reports and test results",
        "Current medication list",
        "Emergency contact details",
        "Cash / JazzCash / EasyPaisa for payment",
        "Sehat Card / Health insurance card (if applicable)",
    ],
    "critical": [
        "National ID Card (CNIC)",
        "All recent medical reports, scans, and lab results",
        "List of all current medications",
        "Blood group information",
        "Emergency contact details (at least 2 people)",
        "Sehat Card / Health insurance card (if applicable)",
        "Advance cash or digital payment method",
    ],
    "emergency": [
        "National ID Card (CNIC)",
        "All available medical records",
        "Medication list (critical to bring)",
        "Blood group card",
        "Emergency contacts",
        "Sehat Card / Health insurance card (if applicable)",
        "Sufficient cash / digital payment",
        "Companion or guardian MANDATORY",
    ],
}

# ── Helpers ──────────────────────────────────────────────────────────────────


def _validate_input(data: dict) -> dict:
    """
    Validate required fields and normalise values.
    Returns a cleaned copy of data, or raises ValueError.
    """
    missing = REQUIRED_FIELDS - set(data.keys())
    if missing:
        raise ValueError(
            f"Missing required input fields: {sorted(missing)}. "
            f"All of the following must be provided: {sorted(REQUIRED_FIELDS)}"
        )

    empty = [k for k in REQUIRED_FIELDS if not str(data.get(k, "")).strip()]
    if empty:
        raise ValueError(
            f"The following required fields must not be empty: {sorted(empty)}"
        )

    cleaned = dict(data)

    urgency = cleaned["urgency_level"].strip().lower()
    if urgency not in VALID_URGENCY:
        raise ValueError(
            f"Invalid urgency_level '{cleaned['urgency_level']}'. "
            f"Must be one of: {sorted(VALID_URGENCY)}"
        )
    cleaned["urgency_level"] = urgency
    cleaned["patient_name"] = str(cleaned.get("patient_name", "") or "Patient").strip() or "Patient"

    return cleaned


def _find_best_slot(
    slot_db: dict,
    hospital_name: str,
    department: str,
    urgency: str,
) -> tuple[dict | None, str]:
    """
    Select the best available slot from the mock DB.

    Strategy:
    - high urgency (urgent/critical/emergency): earliest same-day slot first,
      then earliest future slot if no same-day slots are available.
    - routine: earliest available slot (any date), preferring future dates to
      avoid same-day pressure.

    Returns
    -------
    (slot, message) where slot is a copy of the chosen slot dict (or None),
    and message is a human-readable explanation.
    """
    today_str = date.today().strftime("%Y-%m-%d")

    # Normalise hospital / department lookup (case-insensitive)
    hospital_key = next(
        (k for k in slot_db if k.lower() == hospital_name.lower()), None
    )
    if hospital_key is None:
        return None, (
            f"Hospital '{hospital_name}' not found in the booking system. "
            f"Available hospitals: {list(slot_db.keys())}"
        )

    dept_map = slot_db[hospital_key]
    dept_key = next(
        (k for k in dept_map if k.lower() == department.lower()), None
    )
    if dept_key is None:
        return None, (
            f"Department '{department}' not found at '{hospital_key}'. "
            f"Available departments: {list(dept_map.keys())}"
        )

    slots = dept_map[dept_key]
    available = [s for s in slots if s["available"]]

    if not available:
        return None, (
            f"No available slots for {dept_key} at {hospital_key}. "
            "All slots are currently booked."
        )

    # Sort by date then time
    available_sorted = sorted(available, key=lambda s: (s["date"], s["time"]))

    if urgency in HIGH_URGENCY:
        # Prefer same-day
        same_day = [s for s in available_sorted if s["date"] == today_str]
        chosen = same_day[0] if same_day else available_sorted[0]
        msg = (
            "Earliest same-day slot selected due to high urgency."
            if same_day
            else "No same-day slots available; earliest future slot selected."
        )
    else:
        # routine: pick earliest slot overall
        chosen = available_sorted[0]
        msg = "Earliest available slot selected for routine appointment."

    return copy.deepcopy(chosen), msg


def _capture_slot_state(slot_db: dict, hospital_name: str, department: str) -> dict:
    """
    Return a snapshot of all slots for the given hospital+department.
    Used to capture before/after booking state.
    """
    hospital_key = next(
        (k for k in slot_db if k.lower() == hospital_name.lower()), None
    )
    if hospital_key is None:
        return {}
    dept_map = slot_db[hospital_key]
    dept_key = next(
        (k for k in dept_map if k.lower() == department.lower()), None
    )
    if dept_key is None:
        return {}
    return {
        "hospital": hospital_key,
        "department": dept_key,
        "slots": copy.deepcopy(dept_map[dept_key]),
    }


def _mark_slot_taken(slot_db: dict, hospital_name: str, department: str, token: str) -> None:
    """
    Mark a specific slot (by token) as unavailable in-place.
    """
    hospital_key = next(
        (k for k in slot_db if k.lower() == hospital_name.lower()), None
    )
    if hospital_key is None:
        return
    dept_map = slot_db[hospital_key]
    dept_key = next(
        (k for k in dept_map if k.lower() == department.lower()), None
    )
    if dept_key is None:
        return
    for slot in dept_map[dept_key]:
        if slot["token"] == token:
            slot["available"] = False
            return


def _extract_json_from_response(text: str) -> dict:
    """
    Extract the first valid JSON object from the model's response text.
    Handles markdown code fences.
    """
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        text = brace_match.group(0)

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Model did not return valid JSON.\n"
            f"Parse error: {exc}\n"
            f"Raw response snippet: {text[:500]}"
        ) from exc


def _build_patient_pass_prompt(
    patient_name: str,
    token: str,
    appointment_date: str,
    appointment_time: str,
    hospital: str,
    department: str,
    urgency: str,
    cost_estimate: str,
    checklist: list[str],
) -> str:
    """Build the user message sent to Gemini for Patient Pass generation."""
    checklist_text = "\n".join(f"  - {item}" for item in checklist)
    return (
        "You are the Appointment Agent of Sehat — Pakistan's AI Medical Navigation System.\n"
        "Generate a professional, warm, and clearly formatted Patient Pass for the following booking.\n"
        "The pass must be in English with occasional Urdu/Roman Urdu phrases for a Pakistani audience.\n"
        "Include ALL fields below exactly as given. Do NOT add any explanation outside the pass.\n\n"
        "=== BOOKING DETAILS ===\n"
        f"  Patient Name    : {patient_name}\n"
        f"  Token Number    : {token}\n"
        f"  Date            : {appointment_date}\n"
        f"  Time            : {appointment_time}\n"
        f"  Hospital        : {hospital}\n"
        f"  Department      : {department}\n"
        f"  Urgency Level   : {urgency.upper()}\n"
        f"  Cost Estimate   : {cost_estimate}\n"
        f"  Bring Checklist :\n{checklist_text}\n\n"
        "Format the pass as a beautifully structured text block with a header, separator lines, "
        "all the fields, a warm closing note in Urdu (e.g., 'Allah aap ko sehat de'), "
        "and a footer. Return ONLY the formatted pass text — no JSON, no extra commentary."
    )


def _build_sms(
    patient_name: str,
    token: str,
    appointment_date: str,
    appointment_time: str,
    hospital: str,
    department: str,
) -> str:
    """Generate a short SMS reminder simulation."""
    return (
        f"[SEHAT ALERT] Salam {patient_name}! "
        f"Your appointment is confirmed. "
        f"Token: {token} | {department}, {hospital} | "
        f"Date: {appointment_date} at {appointment_time}. "
        f"Please arrive 15 mins early. Apna khayal rakhein! — Sehat Agent"
    )


# ── Core Function ─────────────────────────────────────────────────────────────


def run_appointment_agent(input_data: dict | str) -> dict:
    """
    Main entry point for the Appointment Agent.

    Parameters
    ----------
    input_data : dict | str
        Structured input from the orchestrator. Accepts a Python dict or
        a raw JSON string.

    Returns
    -------
    dict
        Appointment confirmation with Patient Pass and before/after slot state.

    Raises
    ------
    ValueError
        If required fields are missing/invalid, or model response cannot be parsed.
    EnvironmentError
        If the GEMINI_API_KEY environment variable is not set.
    RuntimeError
        If the Gemini API call fails.
    """
    # ── 1. Parse input ────────────────────────────────────────────────────────
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except json.JSONDecodeError as exc:
            raise ValueError(f"input_data is not valid JSON: {exc}") from exc

    if not isinstance(input_data, dict):
        raise TypeError(
            f"input_data must be a dict or JSON string, got {type(input_data).__name__}"
        )

    # ── 2. Validate & clean ───────────────────────────────────────────────────
    validated = _validate_input(input_data)
    hospital_name  = validated["hospital_name"]
    department     = validated["department"]
    urgency        = validated["urgency_level"]
    patient_name   = validated["patient_name"]

    # ── 3. Build fresh slot database ──────────────────────────────────────────
    slot_db = _build_slot_db()

    # ── 4. Capture BEFORE state ───────────────────────────────────────────────
    before_state = _capture_slot_state(slot_db, hospital_name, department)

    # ── 5. Find best slot ─────────────────────────────────────────────────────
    chosen_slot, slot_message = _find_best_slot(slot_db, hospital_name, department, urgency)

    if chosen_slot is None:
        # Return a failed booking response without calling Gemini
        return {
            "token_number":       None,
            "appointment_date":   None,
            "appointment_time":   None,
            "hospital":           hospital_name,
            "department":         department,
            "patient_pass":       None,
            "booking_status":     "failed",
            "before_state":       before_state,
            "after_state":        before_state,  # unchanged
            "sms_simulation":     None,
            "error":              slot_message,
        }

    token            = chosen_slot["token"]
    appointment_date = chosen_slot["date"]
    appointment_time = chosen_slot["time"]
    cost_estimate    = COST_ESTIMATES.get(urgency, "PKR varies")
    checklist        = BRING_CHECKLIST.get(urgency, BRING_CHECKLIST["routine"])

    # ── 6. Simulate booking (mark slot taken) ─────────────────────────────────
    _mark_slot_taken(slot_db, hospital_name, department, token)

    # ── 7. Capture AFTER state ────────────────────────────────────────────────
    after_state = _capture_slot_state(slot_db, hospital_name, department)

    # ── 8. Load API key ───────────────────────────────────────────────────────
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is not set. "
            "Export it before running the Appointment Agent:\n"
            "  Windows: $env:GEMINI_API_KEY = 'your-key-here'\n"
            "  Linux/Mac: export GEMINI_API_KEY='your-key-here'"
        )
    client = genai.Client(api_key=api_key)

    # ── 9. Generate Patient Pass via Gemini ───────────────────────────────────
    patient_pass_prompt = _build_patient_pass_prompt(
        patient_name=patient_name,
        token=token,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        hospital=hospital_name,
        department=department,
        urgency=urgency,
        cost_estimate=cost_estimate,
        checklist=checklist,
    )

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=patient_pass_prompt,
            config=genai_types.GenerateContentConfig(
                temperature=0.7,       # Slightly creative for warm, human-like pass
                top_p=0.95,
                max_output_tokens=2048,
            ),
        )
    except Exception as exc:
        raise RuntimeError(f"Gemini API call failed: {exc}") from exc

    patient_pass = response.text.strip()

    # ── 10. Build SMS simulation ──────────────────────────────────────────────
    sms = _build_sms(
        patient_name=patient_name,
        token=token,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
        hospital=hospital_name,
        department=department,
    )

    # ── 11. Assemble and return result ────────────────────────────────────────
    return {
        "token_number":       token,
        "appointment_date":   appointment_date,
        "appointment_time":   appointment_time,
        "hospital":           hospital_name,
        "department":         department,
        "patient_pass":       patient_pass,
        "booking_status":     "confirmed",
        "before_state":       before_state,
        "after_state":        after_state,
        "sms_simulation":     sms,
    }


# ── CLI / Quick-test entry point ──────────────────────────────────────────────

def _run_cli() -> None:
    """
    Quick smoke-test. Run from the appointment-agent directory:

        python agent.py
        python agent.py '{"hospital_name":"Aga Khan University Hospital","department":"Cardiology","urgency_level":"urgent","patient_name":"Ali Hassan"}'
    """

    DEFAULT_TEST_INPUT = {
        "hospital_name":  "Aga Khan University Hospital",
        "department":     "Cardiology",
        "urgency_level":  "urgent",
        "patient_name":   "Ali Hassan",
    }

    raw_arg = sys.argv[1] if len(sys.argv) > 1 else None

    if raw_arg:
        try:
            test_input = json.loads(raw_arg)
        except json.JSONDecodeError:
            print("ERROR: Argument is not valid JSON.", file=sys.stderr)
            sys.exit(1)
    else:
        test_input = DEFAULT_TEST_INPUT
        print("No argument provided — using default test input.\n")

    print("── Input ──────────────────────────────────────────")
    print(json.dumps(test_input, indent=2, ensure_ascii=False))
    print()

    try:
        result = run_appointment_agent(test_input)
        print("── Appointment Agent Output ────────────────────────")
        # Pretty-print everything except patient_pass (print it separately for readability)
        display = {k: v for k, v in result.items() if k != "patient_pass"}
        print(json.dumps(display, indent=2, ensure_ascii=False))
        print()
        print("── Patient Pass ────────────────────────────────────")
        print(result.get("patient_pass", "(none)"))
    except (ValueError, EnvironmentError, FileNotFoundError, RuntimeError, TypeError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)


# ── Flask Server ──────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "agent": "appointment-agent", "port": 5004})


@app.route("/analyze", methods=["POST"])
def analyze():
    """Receive appointment request, run agent, return JSON result."""
    try:
        payload = request.get_json(force=True) or {}

        # Case 1 — Orchestrator payload: has user_message but no hospital_name
        if "user_message" in payload and not payload.get("hospital_name"):
            input_data = {
                "hospital_name": "Aga Khan University Hospital",
                "department":    "General Medicine",
                "urgency_level": "urgent",
                "patient_name":  "Patient",
            }
        # Case 2 — Direct payload: hospital_name is provided
        else:
            input_data = {
                "hospital_name": payload.get("hospital_name"),
                "department":    payload.get("department"),
                "urgency_level": payload.get("urgency_level"),
                "patient_name":  payload.get("patient_name"),
            }

        result = run_appointment_agent(input_data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5004)
