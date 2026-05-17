"""
cost_agent/agent.py
────────────────────────────────────────────────────────────────
Cost Agent — Sehat Agent (Pakistan's AI Medical Navigation System)

Receives structured JSON from the orchestrator (or Hospital Finder Agent),
loads the system prompt from prompt.md, calls Gemini 2.5 Flash, and
returns a validated JSON cost estimate.

Expected input (dict or JSON string):
    {
        "recommended_department": str,
        "urgency_level":          str,   # "routine" | "urgent" | "critical" | "emergency"
        "hospital_name":          str,
        "hospital_type":          str,   # "private" | "government"
        "visit_type":             str    # "OPD" | "Emergency"
    }

Returns (dict):
    {
        "estimated_cost":           { "minimum": int, "maximum": int, "currency": "PKR" },
        "breakdown":                { "consultation": str, "probable_tests": str, "medicine_estimate": str },
        "payment_advice":           str,
        "bring_checklist":          list[str],
        "insurance_applicable":     bool,
        "government_option_available": bool,
        "government_cost":          str,
        "reasoning":                str,
        "disclaimer":               str
    }
"""

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from google import genai
from google.genai import types as genai_types

# ── Constants ────────────────────────────────────────────────────────────────

MODEL_NAME = "gemini-2.5-flash"
PROMPT_FILE = Path(__file__).parent / "prompt.md"

REQUIRED_FIELDS = {
    "recommended_department",
    "urgency_level",
    "hospital_name",
    "hospital_type",
    "visit_type",
}

VALID_URGENCY = {"routine", "urgent", "critical", "emergency"}
VALID_HOSPITAL_TYPE = {"private", "government"}
VALID_VISIT_TYPE = {"opd", "emergency"}

# ── Instant Cost Lookup Table (no Gemini needed) ──────────────────────────────
# Format: keyword (lowercase) -> (min_pkr, max_pkr)
INSTANT_COST_TABLE = [
    (["emergency", "critical"],          (5000, 20000)),
    (["cardiology", "cardiac", "heart"],  (3000, 15000)),
    (["neurology", "neuro", "brain"],     (2000, 10000)),
    (["oncology", "cancer"],              (5000, 25000)),
    (["orthopedic", "ortho", "bone"],     (2000, 8000)),
    (["pediatric", "child", "children"],  (1000, 5000)),
    (["gynecology", "gynaecology", "obs"],(1500, 8000)),
    (["radiology", "imaging", "scan"],   (2000, 10000)),
    (["general medicine", "general"],     (500, 3000)),
]
DEFAULT_COST = (1000, 5000)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _load_system_prompt() -> str:
    """Read prompt.md from the same directory as this file."""
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(
            f"System prompt not found: {PROMPT_FILE}. "
            "Ensure prompt.md is present in the cost-agent directory."
        )
    return PROMPT_FILE.read_text(encoding="utf-8")


def _validate_input(data: dict) -> dict:
    """
    Validate required fields and normalise values.
    Returns a cleaned copy of data, or raises ValueError with a descriptive message.
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
            f"The following fields must not be empty: {sorted(empty)}"
        )

    cleaned = dict(data)

    urgency = cleaned["urgency_level"].strip().lower()
    if urgency not in VALID_URGENCY:
        raise ValueError(
            f"Invalid urgency_level '{cleaned['urgency_level']}'. "
            f"Must be one of: {sorted(VALID_URGENCY)}"
        )
    cleaned["urgency_level"] = urgency

    hospital_type = cleaned["hospital_type"].strip().lower()
    if hospital_type not in VALID_HOSPITAL_TYPE:
        raise ValueError(
            f"Invalid hospital_type '{cleaned['hospital_type']}'. "
            f"Must be one of: {sorted(VALID_HOSPITAL_TYPE)}"
        )
    cleaned["hospital_type"] = hospital_type

    visit_type = cleaned["visit_type"].strip().lower()
    if visit_type not in VALID_VISIT_TYPE:
        raise ValueError(
            f"Invalid visit_type '{cleaned['visit_type']}'. "
            f"Must be one of: {sorted(VALID_VISIT_TYPE)}"
        )
    cleaned["visit_type"] = visit_type.upper()  # normalise back to "OPD" / "Emergency"

    return cleaned


def _extract_json_from_response(text: str) -> dict:
    """
    Extract the first valid JSON object from the model's response text.
    Handles cases where the model wraps the JSON in markdown code fences.
    """
    # Strip markdown fences (```json ... ``` or ``` ... ```)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)

    # Fallback: find the first { ... } block in the text
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


def _build_user_message(input_data: dict) -> str:
    """Format the validated input dict as the user turn sent to the model."""
    return (
        "Please calculate the cost estimate for the following patient visit.\n\n"
        "Input from Hospital Finder Agent:\n"
        f"```json\n{json.dumps(input_data, indent=2, ensure_ascii=False)}\n```\n\n"
        "Return ONLY the JSON output as specified in the system prompt. "
        "Do not include any explanation outside the JSON block."
    )


def _instant_cost_lookup(department: str, urgency: str, hospital_type: str, visit_type: str) -> dict:
    """
    Return a cost estimate instantly from the keyword table.
    No Gemini call needed — always responds in < 10ms.
    """
    dept_lower = department.lower()
    urgency_lower = urgency.lower()
    visit_lower = visit_type.lower()

    # Emergency visit overrides department cost floor
    if urgency_lower in ("critical", "emergency") or visit_lower == "emergency":
        minimum, maximum = 5000, 20000
    else:
        minimum, maximum = DEFAULT_COST
        for keywords, (mn, mx) in INSTANT_COST_TABLE:
            if any(kw in dept_lower for kw in keywords):
                minimum, maximum = mn, mx
                break

    # Government hospitals cost ~40% less
    if hospital_type.lower() == "government":
        minimum = int(minimum * 0.4)
        maximum = int(maximum * 0.5)

    govt_available = hospital_type.lower() == "private"
    govt_min = int(minimum * 0.4)
    govt_max = int(maximum * 0.5)

    return {
        "estimated_cost": {"minimum": minimum, "maximum": maximum, "currency": "PKR"},
        "breakdown": {
            "consultation": f"PKR {minimum // 3} - {maximum // 3}",
            "probable_tests": f"PKR {minimum // 3} - {maximum // 3}",
            "medicine_estimate": f"PKR {minimum // 3} - {maximum // 3}",
        },
        "payment_advice": "Please carry cash or use JazzCash / EasyPaisa. Sehat Card accepted at government hospitals.",
        "bring_checklist": [
            "CNIC / ID card",
            "Previous prescriptions or reports (if any)",
            "Cash or digital payment method",
            "Sehat Card (if applicable)",
        ],
        "insurance_applicable": False,
        "government_option_available": govt_available,
        "government_cost": f"PKR {govt_min} - {govt_max} (at nearest government hospital)" if govt_available else "N/A",
        "reasoning": f"Estimate based on {department} department, {urgency} urgency, {hospital_type} hospital.",
        "disclaimer": "Costs are approximate estimates only. Actual charges depend on tests, admission, and treatment required. Always confirm with the hospital.",
        "source": "instant_lookup",
    }


def run_cost_agent(input_data: dict | str) -> dict:
    """
    Main entry point for the Cost Agent.
    Returns an instant keyword-based estimate immediately (< 2s).
    Optionally enhances with Gemini if API key is available.
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

    # ── 2. Apply defaults for any missing fields (graceful) ───────────────────
    input_data = dict(input_data)
    input_data.setdefault("recommended_department", "General Medicine")
    input_data.setdefault("urgency_level", "urgent")
    input_data.setdefault("hospital_name", "Unknown Hospital")
    input_data.setdefault("hospital_type", "private")
    input_data.setdefault("visit_type", "OPD")

    # ── 3. Validate & clean ───────────────────────────────────────────────────
    validated = _validate_input(input_data)

    # ── 4. INSTANT keyword-based response (primary — always fast) ─────────────
    result = _instant_cost_lookup(
        department=validated["recommended_department"],
        urgency=validated["urgency_level"],
        hospital_type=validated["hospital_type"],
        visit_type=validated["visit_type"],
    )

    # ── 5. Optional: Gemini enhancement (skip gracefully if unavailable) ───────
    try:
        load_dotenv(dotenv_path=Path(__file__).parent / ".env")
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            system_prompt = _load_system_prompt()
            client = genai.Client(api_key=api_key)
            user_message = _build_user_message(validated)
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=user_message,
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    top_p=0.95,
                    max_output_tokens=2048,
                ),
            )
            enhanced = _extract_json_from_response(response.text.strip())
            enhanced["source"] = "gemini_enhanced"
            return enhanced
    except Exception:
        # Gemini failed or timed out — fall back to instant result silently
        pass

    return result


# ── CLI / Quick-test entry point ──────────────────────────────────────────────

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "agent": "cost-agent", "port": 5003})

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.json or {}
        test_input = {
            "recommended_department": data.get("recommended_department", "Cardiology"),
            "urgency_level": data.get("urgency_level", "urgent"),
            "hospital_name": data.get("hospital_name", "Aga Khan University Hospital"),
            "hospital_type": data.get("hospital_type", "private"),
            "visit_type": data.get("visit_type", "OPD"),
        }
        result = run_cost_agent(test_input)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5003)
