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


# ── Core Function ─────────────────────────────────────────────────────────────


def run_cost_agent(input_data: dict | str) -> dict:
    """
    Main entry point for the Cost Agent.

    Parameters
    ----------
    input_data : dict | str
        Structured input from the orchestrator. Accepts either a Python dict
        or a raw JSON string.

    Returns
    -------
    dict
        Cost estimate in the schema defined in prompt.md.

    Raises
    ------
    ValueError
        If required fields are missing/invalid, or if the model response
        cannot be parsed as JSON.
    EnvironmentError
        If the GEMINI_API_KEY environment variable is not set.
    FileNotFoundError
        If prompt.md is missing from the cost-agent directory.
    """
    # ── 1. Parse input ────────────────────────────────────────────────────────
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"input_data is not valid JSON: {exc}"
            ) from exc

    if not isinstance(input_data, dict):
        raise TypeError(
            f"input_data must be a dict or JSON string, got {type(input_data).__name__}"
        )

    # ── 2. Validate & clean ───────────────────────────────────────────────────
    validated = _validate_input(input_data)

    # ── 3. Load system prompt ────────────────────────────────────────────────
    system_prompt = _load_system_prompt()

    # ── 4. Initialise Gemini client (google-genai 2.x SDK) ───────────────────
    # Load .env from the cost-agent directory (does nothing if already set)
    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY environment variable is not set. "
            "Export it before running the Cost Agent:\n"
            "  Windows: $env:GEMINI_API_KEY = 'your-key-here'\n"
            "  Linux/Mac: export GEMINI_API_KEY='your-key-here'"
        )
    client = genai.Client(api_key=api_key)

    # ── 5. Call Gemini 2.5 Flash ──────────────────────────────────────────────
    user_message = _build_user_message(validated)

    try:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=user_message,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,          # Low temperature → deterministic, structured output
                top_p=0.95,
                max_output_tokens=8192,
            ),
        )
    except Exception as exc:
        raise RuntimeError(
            f"Gemini API call failed: {exc}"
        ) from exc

    raw_text = response.text.strip()

    # ── 6. Parse & return JSON ────────────────────────────────────────────────
    result = _extract_json_from_response(raw_text)
    return result


# ── CLI / Quick-test entry point ──────────────────────────────────────────────

if __name__ == "__main__":
    """
    Quick smoke-test. Run from the cost-agent directory:

        python agent.py
        python agent.py '{"recommended_department":"Cardiology","urgency_level":"urgent","hospital_name":"Aga Khan University Hospital","hospital_type":"private","visit_type":"OPD"}'
    """

    # Default test payload used when no argument is passed
    DEFAULT_TEST_INPUT = {
        "recommended_department": "Cardiology",
        "urgency_level": "urgent",
        "hospital_name": "Aga Khan University Hospital",
        "hospital_type": "private",
        "visit_type": "OPD",
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
        result = run_cost_agent(test_input)
        print("── Cost Estimate Output ───────────────────────────")
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (ValueError, EnvironmentError, FileNotFoundError, RuntimeError) as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(1)
