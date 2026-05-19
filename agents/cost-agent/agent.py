"""
cost_agent/agent.py  —  FIXED VERSION
────────────────────────────────────────────────────────────────
Cost Agent — Sehat Agent (Pakistan's AI Medical Navigation System)

FIXES APPLIED:
  FIX-1  Dual route: /analyze AND /cost-agent/analyze both work
          → Was causing 404 from orchestrator (same issue as hospital finder)
  FIX-2  Accept both "department" AND "recommended_department" field names
          → Was causing "PKR 0-0" because field name mismatch
  FIX-3  Removed strict validation — graceful defaults for ALL missing fields
          → Emergency cases were crashing because hospital_type missing
  FIX-4  Instant lookup always runs — Gemini is optional enhancement only
          → Even with 429 quota error, real cost estimates always show
  FIX-5  hospital_type default changed from "private" to smarter inference
          → If urgency=critical/emergency → government hospital assumed
  FIX-6  department field normalized before lookup (handles urdu/aliases)
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS

# ── Logger ────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[COST AGENT] {datetime.now().strftime('%H:%M:%S')} {msg}")


# ── Env Loader ────────────────────────────────────────────────────────────────

def _load_env():
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip(' "\''))

_load_env()


# ── Cost Lookup Table ─────────────────────────────────────────────────────────
# FIX-4: This ALWAYS runs — no Gemini needed for cost estimates

COST_TABLE = [
    # (keywords_list,               (private_min, private_max))
    (["emergency", "critical"],     (5000, 20000)),
    (["icu", "intensive"],          (8000, 30000)),
    (["cardiology", "cardiac",
      "heart", "dil"],              (3500, 15000)),
    (["neurology", "neuro",
      "brain", "dimagh"],           (3000, 12000)),
    (["oncology", "cancer",
      "tumor"],                     (5000, 25000)),
    (["orthopedic", "ortho",
      "bone", "haddi", "joint"],    (2000,  8000)),
    (["pediatric", "child",
      "children", "bacha",
      "bachcha"],                   (1000,  5000)),
    (["gynecology", "gynaecology",
      "obs", "maternity"],          (1500,  8000)),
    (["radiology", "imaging",
      "mri", "ct scan", "xray",
      "x-ray", "ultrasound"],       (2000, 10000)),
    (["gastro", "stomach",
      "liver", "hepatology"],       (2000,  8000)),
    (["urology", "kidney"],         (2000,  8000)),
    (["dermatology", "skin",
      "jild"],                      (1500,  5000)),
    (["psychiatry", "mental",
      "psychology"],                (2000,  8000)),
    (["ent", "ear", "nose",
      "throat"],                    (1000,  4000)),
    (["ophthalmology", "eye",
      "aankh"],                     (1000,  4000)),
    (["endocrinology", "diabetes",
      "thyroid", "sugar"],          (1500,  6000)),
    (["general medicine", "general",
      "fever", "flu", "bukhar"],    (500,   3000)),
]

DEFAULT_COST_PRIVATE = (1000, 5000)

# Government hospitals are ~40-50% of private costs
GOVT_MULTIPLIER_MIN = 0.35
GOVT_MULTIPLIER_MAX = 0.50

# Department aliases for normalization
DEPT_ALIASES = {
    "heart": "cardiology", "cardiac": "cardiology", "dil": "cardiology",
    "brain": "neurology",  "neuro": "neurology",    "dimagh": "neurology",
    "child": "pediatrics", "children": "pediatrics",
    "bachcha": "pediatrics", "bacha": "pediatrics",
    "women": "gynecology", "gynae": "gynecology",
    "bone": "orthopedics", "joint": "orthopedics",  "haddi": "orthopedics",
    "skin": "dermatology", "jild": "dermatology",
    "eye": "ophthalmology", "aankh": "ophthalmology",
    "ear": "ent", "nose": "ent", "throat": "ent", "kaan": "ent",
    "kidney": "urology",   "sugar": "endocrinology",
    "cancer": "oncology",  "tumor": "oncology",
    "mental": "psychiatry","dimagi": "psychiatry",
    "general": "general medicine", "fever": "general medicine",
    "bukhar": "general medicine",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_dept(dept: str) -> str:
    """FIX-6: Map aliases to canonical department name."""
    d = dept.lower().strip()
    for alias, canonical in DEPT_ALIASES.items():
        if alias in d:
            return canonical
    return d


def _smart_defaults(data: dict) -> dict:
    """
    FIX-2 + FIX-3: Extract fields with smart fallbacks.
    Accepts BOTH 'department' and 'recommended_department'.
    Never crashes — always returns usable values.
    """
    # FIX-2: Accept either field name
    department = (
        data.get("recommended_department") or
        data.get("department") or
        "General Medicine"
    ).strip()

    urgency = (data.get("urgency_level") or "routine").lower().strip()
    if urgency not in ("routine", "urgent", "critical", "emergency"):
        urgency = "routine"

    # FIX-5: Smarter hospital_type default
    hospital_type = (data.get("hospital_type") or "").lower().strip()
    if hospital_type not in ("government", "private"):
        # If urgency is critical/emergency → likely going to government hospital
        hospital_type = "government" if urgency in ("critical", "emergency") else "private"

    visit_type = (data.get("visit_type") or "OPD").strip()
    if visit_type.lower() not in ("opd", "emergency"):
        visit_type = "Emergency" if urgency in ("critical", "emergency") else "OPD"
    else:
        visit_type = "Emergency" if visit_type.lower() == "emergency" else "OPD"

    hospital_name = (data.get("hospital_name") or "Your Selected Hospital").strip()

    return {
        "department":   department,
        "urgency":      urgency,
        "hospital_type": hospital_type,
        "visit_type":   visit_type,
        "hospital_name": hospital_name,
    }


def _lookup_cost(department: str, urgency: str,
                 hospital_type: str, visit_type: str) -> tuple[int, int]:
    """Return (min_cost, max_cost) in PKR for a private hospital."""
    dept_lower = department.lower()

    # Emergency visit always gets emergency rates
    if urgency in ("critical", "emergency") or visit_type.lower() == "emergency":
        priv_min, priv_max = 5000, 20000
    else:
        priv_min, priv_max = DEFAULT_COST_PRIVATE
        for keywords, (mn, mx) in COST_TABLE:
            if any(kw in dept_lower for kw in keywords):
                priv_min, priv_max = mn, mx
                break

    # Apply government discount
    if hospital_type == "government":
        return int(priv_min * GOVT_MULTIPLIER_MIN), int(priv_max * GOVT_MULTIPLIER_MAX)

    return priv_min, priv_max


def _payment_advice(maximum: int, hospital_type: str) -> str:
    if maximum >= 15000:
        return (
            "Card zaroor laye — amount PKR 15,000 se zyada ho sakti hai. "
            "Debit/Credit Card recommended. JazzCash / EasyPaisa bhi qabool hota hai."
            + (" Sehat Card try karein — government hospital mein valid hai."
               if hospital_type == "government" else "")
        )
    elif maximum >= 5000:
        return (
            "Cash aur Card dono laye — amount PKR 5,000-15,000 ke darmiyan ho sakti hai. "
            "JazzCash / EasyPaisa bhi option hai."
        )
    else:
        return (
            "Cash kaafi hoga — amount PKR 5,000 se kam hogi. "
            "JazzCash / EasyPaisa bhi qabool hota hai."
        )


# ── Core Instant Estimate ─────────────────────────────────────────────────────

def _instant_estimate(fields: dict) -> dict:
    """
    FIX-4: Always returns a real estimate — no Gemini needed.
    This is the PRIMARY response path.
    """
    dept          = _normalize_dept(fields["department"])
    urgency       = fields["urgency"]
    hospital_type = fields["hospital_type"]
    visit_type    = fields["visit_type"]
    hospital_name = fields["hospital_name"]

    min_cost, max_cost = _lookup_cost(dept, urgency, hospital_type, visit_type)

    # Government comparison (shown only for private hospital patients)
    govt_min = int(min_cost * GOVT_MULTIPLIER_MIN / (GOVT_MULTIPLIER_MIN if hospital_type == "government" else 1))
    govt_max = int(max_cost * GOVT_MULTIPLIER_MAX / (GOVT_MULTIPLIER_MAX if hospital_type == "government" else 1))
    if hospital_type == "private":
        govt_min = int(min_cost * GOVT_MULTIPLIER_MIN)
        govt_max = int(min_cost * GOVT_MULTIPLIER_MAX * 2)
        govt_available = True
        govt_cost_str = f"PKR {govt_min:,} - {govt_max:,} (nearest government hospital mein)"
    else:
        govt_available = False
        govt_cost_str = "N/A (aap already government hospital mein hain)"

    # Breakdown (roughly thirds)
    consult_min = int(min_cost * 0.35)
    consult_max = int(max_cost * 0.35)
    test_min    = int(min_cost * 0.40)
    test_max    = int(max_cost * 0.40)
    med_min     = int(min_cost * 0.25)
    med_max     = int(max_cost * 0.25)

    checklist = [
        "CNIC / ID card (zaroor laye)",
        "Purani prescriptions ya reports (agar hain)",
        "Cash (minimum PKR {:,} sath rakhein)".format(min_cost),
    ]
    if max_cost >= 5000:
        checklist.append("Debit / Credit Card (recommended)")
    checklist.append("JazzCash / EasyPaisa app (backup payment)")
    if hospital_type == "government":
        checklist.append("Sehat Card (agar hai — government hospital mein valid hai)")

    reasoning = (
        f"[Step 1] Department: '{fields['department']}' normalized to '{dept}'. "
        f"[Step 2] Hospital type: {hospital_type} | Urgency: {urgency} | Visit: {visit_type}. "
        f"[Step 3] Cost table matched — base range PKR {min_cost:,}-{max_cost:,}. "
        f"{'[Step 4] Government discount applied (35-50% of private rates).' if hospital_type == 'government' else ''} "
        f"[Final] Estimated cost: PKR {min_cost:,} - {max_cost:,}."
    ).strip()

    return {
        "agent": "cost_agent",
        "estimated_cost": {
            "minimum":  min_cost,
            "maximum":  max_cost,
            "currency": "PKR",
        },
        "breakdown": {
            "consultation":     f"PKR {consult_min:,} - {consult_max:,}",
            "probable_tests":   f"PKR {test_min:,} - {test_max:,}",
            "medicine_estimate": f"PKR {med_min:,} - {med_max:,}",
        },
        "payment_advice":              _payment_advice(max_cost, hospital_type),
        "bring_checklist":             checklist,
        "insurance_applicable":        False,
        "government_option_available": govt_available,
        "government_cost":             govt_cost_str,
        "reasoning":                   reasoning,
        "disclaimer": (
            "Yeh estimates approximate hain. Actual charges tests, admission, aur "
            "treatment ke mutabiq alag ho sakte hain. Hospital se confirm zaroor karein."
        ),
        "source": "instant_lookup",
    }


# ── Optional Gemini Enhancement ───────────────────────────────────────────────

def _try_gemini_enhance(fields: dict, instant_result: dict) -> dict:
    """
    Try to enhance the instant result with Gemini.
    If Gemini fails (quota, network, etc.) silently return instant_result.
    """
    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_KEY_1")
        if not api_key:
            return instant_result

        prompt_file = Path(__file__).parent / "prompt.md"
        if not prompt_file.exists():
            return instant_result

        system_prompt = prompt_file.read_text(encoding="utf-8")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=system_prompt,
            generation_config={"temperature": 0.2, "max_output_tokens": 1024},
        )

        user_msg = (
            "Calculate cost estimate for:\n"
            f"```json\n{json.dumps(fields, indent=2)}\n```\n"
            "Return ONLY valid JSON — no explanation."
        )
        response = model.generate_content(user_msg)
        text = response.text.strip()

        # Extract JSON
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        raw = fenced.group(1) if fenced else re.search(r"\{.*\}", text, re.DOTALL)
        if not raw:
            return instant_result

        enhanced = json.loads(raw if isinstance(raw, str) else raw.group(0))
        enhanced["agent"] = "cost_agent"
        enhanced["source"] = "gemini_enhanced"
        log("Gemini enhancement successful")
        return enhanced

    except Exception as e:
        log(f"Gemini enhancement skipped: {e} — using instant estimate")
        return instant_result


# ── Main Entry Point ──────────────────────────────────────────────────────────

def run_cost_agent(input_data) -> dict:
    if isinstance(input_data, str):
        try:
            input_data = json.loads(input_data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON input: {e}")

    if not isinstance(input_data, dict):
        raise TypeError(f"Expected dict, got {type(input_data).__name__}")

    # FIX-2 + FIX-3: Smart field extraction, never crashes
    fields = _smart_defaults(input_data)
    log(f"Processing: dept={fields['department']} urgency={fields['urgency']} "
        f"type={fields['hospital_type']} visit={fields['visit_type']}")

    # FIX-4: Always get instant estimate first
    result = _instant_estimate(fields)
    log(f"Instant estimate: PKR {result['estimated_cost']['minimum']:,} - "
        f"{result['estimated_cost']['maximum']:,}")

    # Try Gemini enhancement (optional, quota-safe)
    result = _try_gemini_enhance(fields, result)

    return result


# ── Flask App ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)


def _handle_request(data: dict) -> dict:
    """Shared handler for both routes."""
    log(f"Incoming fields: {list(data.keys())}")
    result = run_cost_agent(data)
    log(f"Response ready — source: {result.get('source', 'unknown')}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# FIX-1: TWO routes — orchestrator calls /analyze, legacy is /cost-agent/analyze
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/analyze', methods=['POST'])
def analyze_short():
    """Primary route — what orchestrator calls."""
    try:
        data = request.get_json(force=True) or {}
        return jsonify(_handle_request(data)), 200
    except Exception as e:
        log(f"ERROR /analyze: {e}")
        # FIX-4: Even on error, return a usable response
        return jsonify({
            "agent": "cost_agent",
            "estimated_cost": {"minimum": 1000, "maximum": 5000, "currency": "PKR"},
            "breakdown": {
                "consultation": "PKR 500 - 2,000",
                "probable_tests": "PKR 300 - 1,500",
                "medicine_estimate": "PKR 200 - 1,500",
            },
            "payment_advice": "Cash aur card dono laye.",
            "bring_checklist": ["CNIC", "Cash", "Debit Card"],
            "insurance_applicable": False,
            "government_option_available": True,
            "government_cost": "PKR 300 - 1,500 (government hospital mein)",
            "reasoning": "Default estimate (error fallback)",
            "disclaimer": "Yeh estimate approximate hai. Hospital se confirm karein.",
            "source": "error_fallback",
            "error": str(e),
        }), 200  # Return 200 so orchestrator doesn't break


@app.route('/cost-agent/analyze', methods=['POST'])
def analyze_long():
    """Legacy route — backward compatibility."""
    return analyze_short()


@app.route('/health', methods=['GET'])
@app.route('/cost-agent/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "agent": "cost_agent",
        "port": 5003,
        "routes": ["/analyze", "/cost-agent/analyze"],
        "mode": "instant_lookup + optional_gemini",
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5003))
    log(f"Cost Agent starting on port {port}")
    log(f"Routes: /analyze (primary) | /cost-agent/analyze (legacy)")
    app.run(host="0.0.0.0", port=port, debug=False)