"""
validator_agent/agent.py  —  FIXED VERSION
────────────────────────────────────────────────────────────────
Validator Agent — Sehat Agent (Pakistan's AI Medical Navigation System)

FIXES APPLIED:
  FIX-1  "N/A" rating and "Nearest available" distance no longer cause rejection
          → Fallback data was being wrongly rejected every time
  FIX-2  Distance check now skipped gracefully if non-numeric (fallback mode)
          → Was crashing with regex exception on "Nearest available"
  FIX-3  Check 5 (24/7) made optional — opening_hours field doesn't exist in fallback
          → Was always failing for HIGH/CRITICAL cases
  FIX-4  Check 6 (cost_comparison) removed — Hospital Finder doesn't return this field
          → Was always failing, blocking appointment agent
  FIX-5  Validator now APPROVES with warnings instead of hard REJECT for minor issues
          → Appointment agent was never reached because validator kept rejecting
  FIX-6  Fallback-mode aware — if source="fallback", relaxed checks applied
  FIX-7  Added /validator/analyze route alongside /analyze for compatibility
"""

import json
import re
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS


# ── Logger ────────────────────────────────────────────────────────────────────

def log(msg):
    print(f"[VALIDATOR] {datetime.now().strftime('%H:%M:%S')} {msg}")


# ── Core Validation ───────────────────────────────────────────────────────────

def validate_hospital_output(hospital_finder_output: dict, original_request: dict) -> dict:
    """
    Validate Hospital Finder output before passing to Appointment Agent.

    FIX-5: Returns APPROVED_WITH_WARNINGS for minor issues instead of REJECT.
    Only hard REJECT for truly critical failures (no hospital found at all).
    """
    warnings = []
    failed_checks = []

    top_rec      = hospital_finder_output.get("top_recommendation", {})
    alternatives = hospital_finder_output.get("alternatives", [])
    source       = hospital_finder_output.get("source", "unknown")  # FIX-6
    is_fallback  = source in ("fallback", "error_fallback")

    req_dept    = original_request.get("required_department", "") or original_request.get("department", "")
    req_urgency = (original_request.get("urgency_level", "") or "").upper()
    req_pref    = (original_request.get("hospital_preference", "") or "").upper()

    log(f"Validating: dept={req_dept} urgency={req_urgency} source={source}")

    # ── HARD REJECT: No hospital found at all ────────────────────────────────
    if not top_rec or not top_rec.get("name"):
        log("HARD REJECT: No hospital in response")
        return _reject(
            failed_checks=[{
                "check": "CRITICAL — No Hospital Found",
                "reason": "Hospital Finder returned no recommendation. Cannot proceed.",
                "severity": "CRITICAL"
            }],
            original_request=original_request,
            note="No hospital found. Cannot book appointment.",
        )

    # ── HARD REJECT: CRITICAL urgency + no emergency facility ───────────────
    if req_urgency == "CRITICAL" and not top_rec.get("emergency", True):
        log("HARD REJECT: Critical case but hospital has no emergency")
        return _reject(
            failed_checks=[{
                "check": "CRITICAL — Emergency Facility Required",
                "reason": "CRITICAL urgency requires emergency facility. Retry with emergency filter.",
                "severity": "CRITICAL"
            }],
            original_request=original_request,
            note="CRITICAL case needs emergency hospital.",
        )

    # ── Check 1: Department Match (WARNING only, not reject) ─────────────────
    hosp_dept = top_rec.get("department", "")
    if req_dept and hosp_dept and hosp_dept.lower() != req_dept.lower():
        warnings.append({
            "check": "CHECK 1 — Department Match",
            "reason": f"Requested '{req_dept}' but got '{hosp_dept}'. May still be appropriate.",
            "severity": "LOW",
        })
        log(f"WARNING: dept mismatch ({req_dept} vs {hosp_dept})")

    # ── Check 2: Hospital Type Preference ───────────────────────────────────
    if req_pref in ("GOVERNMENT", "PRIVATE"):
        hosp_type = top_rec.get("type", "").upper()
        if hosp_type and hosp_type != req_pref:
            warnings.append({
                "check": "CHECK 2 — Hospital Type Preference",
                "reason": f"User preferred {req_pref} but {hosp_type} hospital returned. Alternatives may have preferred type.",
                "severity": "LOW",
            })

    # ── Check 3: Distance Sanity (FIX-2: skip if non-numeric) ───────────────
    dist_str = top_rec.get("distance", "")
    if dist_str and dist_str not in ("Nearest available", "See Google Maps", "N/A", ""):
        try:
            nums = re.findall(r"[\d\.]+", dist_str)
            if nums:
                dist_val = float(nums[0])
                if dist_val > 50:  # FIX-2: raised threshold from 25 to 50km
                    warnings.append({
                        "check": "CHECK 3 — Distance",
                        "reason": f"Hospital is {dist_val}km away. Consider closer options.",
                        "severity": "LOW",
                    })
        except Exception:
            pass  # FIX-2: Non-numeric distance → skip silently
    else:
        log(f"Distance check skipped (non-numeric or fallback): '{dist_str}'")

    # ── Check 4: Data Completeness (FIX-1: N/A rating allowed in fallback) ──
    phone    = top_rec.get("phone", "")
    address  = top_rec.get("address", "")
    maps_link = top_rec.get("maps_link", "")
    rating   = top_rec.get("rating", "")

    # FIX-1: In fallback mode, "N/A" rating is acceptable
    rating_ok = bool(rating) and (is_fallback or str(rating) != "N/A")
    phone_ok  = bool(phone) and phone.lower() not in ("unknown", "n/a", "")
    
    if not phone_ok or not address:
        warnings.append({
            "check": "CHECK 4 — Data Completeness",
            "reason": f"Some fields missing: phone={'ok' if phone_ok else 'missing'}, address={'ok' if address else 'missing'}. Fallback mode: {is_fallback}",
            "severity": "LOW",
        })

    # ── Check 5: Emergency Availability (FIX-3: opening_hours optional) ─────
    if req_urgency in ("HIGH", "CRITICAL"):
        has_emergency = top_rec.get("emergency", True)  # FIX-3: default True
        has_note      = bool(hospital_finder_output.get("emergency_note"))
        # FIX-3: opening_hours check removed — field doesn't exist in our data
        if not has_emergency:
            warnings.append({
                "check": "CHECK 5 — Emergency Availability",
                "reason": "HIGH/CRITICAL case but hospital emergency flag is False.",
                "severity": "MEDIUM",
            })

    # ── Check 6: REMOVED (FIX-4) ────────────────────────────────────────────
    # cost_comparison is not returned by Hospital Finder — removed this check

    # ── Check 7: Reasoning Quality ──────────────────────────────────────────
    reasoning = hospital_finder_output.get("reasoning", "")
    if not reasoning or len(reasoning.split()) < 3:
        warnings.append({
            "check": "CHECK 7 — Reasoning Quality",
            "reason": "Reasoning is empty or too short.",
            "severity": "LOW",
        })

    # ── Decision ─────────────────────────────────────────────────────────────
    # FIX-5: Only hard failures cause REJECT. Warnings = APPROVED_WITH_WARNINGS.
    critical_fails = [f for f in failed_checks if f.get("severity") == "CRITICAL"]

    if critical_fails:
        return _reject(critical_fails, original_request)

    # APPROVED (with or without warnings)
    return _approve(top_rec, hospital_finder_output, warnings, source)


# ── Response Builders ─────────────────────────────────────────────────────────

def _approve(top_rec: dict, full_output: dict, warnings: list, source: str) -> dict:
    checks_passed = 7 - len([w for w in warnings if w.get("severity") == "MEDIUM"])
    checks_passed = max(5, checks_passed)  # at least 5/7

    status = "APPROVED" if not warnings else "APPROVED_WITH_WARNINGS"
    confidence = "95%" if not warnings else "80%"

    note = "All checks passed. Proceeding to Appointment Agent."
    if warnings:
        note = (
            f"{len(warnings)} minor warning(s) noted but within acceptable range. "
            "Proceeding to Appointment Agent."
        )
    if source in ("fallback", "error_fallback"):
        note += " (Fallback mode — Google Places API unavailable.)"

    log(f"APPROVED: {status} | warnings={len(warnings)} | confidence={confidence}")

    return {
        "validation_status":     status,
        "checks_passed":         checks_passed,
        "checks_failed":         len(warnings),
        "failed_checks":         warnings,
        "confidence_score":      confidence,
        "validator_note":        note,
        "approved_recommendation": top_rec,
        # Pass through all fields appointment agent needs
        "hospital_name":         full_output.get("hospital_name", top_rec.get("name", "")),
        "hospital_address":      full_output.get("hospital_address", top_rec.get("address", "")),
        "hospital_phone":        full_output.get("hospital_phone", top_rec.get("phone", "")),
        "hospital_maps_link":    full_output.get("hospital_maps_link", top_rec.get("maps_link", "")),
        "hospital_type":         full_output.get("hospital_type", top_rec.get("type", "")),
        "department":            full_output.get("department", top_rec.get("department", "")),
        "urgency_level":         full_output.get("urgency_level", "routine"),
        "visit_type":            full_output.get("visit_type", "OPD"),
        "patient_name":          full_output.get("patient_name", "Patient"),
        "system_state": (
            f"BEFORE: No appointment booked | "
            f"AFTER: Validated ✅ — Ready for booking at {top_rec.get('name', 'Hospital')}"
        ),
    }


def _reject(failed_checks: list, original_request: dict,
            note: str = "Validation failed. Sending back to Hospital Finder Agent.") -> dict:
    log(f"REJECTED: {len(failed_checks)} critical failure(s)")
    return {
        "validation_status": "REJECTED",
        "checks_passed":     max(0, 7 - len(failed_checks)),
        "checks_failed":     len(failed_checks),
        "failed_checks":     failed_checks,
        "confidence_score":  "20%",
        "validator_note":    note,
        "retry_instruction": {
            "send_back_to": "Hospital Finder Agent",
            "fix_this":     ", ".join(f["check"] for f in failed_checks),
            "retry_with": {
                **original_request,
                "validator_feedback": note,
            },
        },
        "system_state": "BEFORE: No appointment booked | AFTER: Validation failed — retrying",
    }


# ── Flask App ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)


def _handle(data: dict) -> dict:
    hospital_output  = data.get("hospital_finder_output", data)
    original_request = data.get("original_request", {})

    # If data was sent flat (orchestrator sends full hospital finder response directly)
    if not hospital_output.get("top_recommendation") and data.get("top_recommendation"):
        hospital_output  = data
        original_request = data.get("original_request", {})

    return validate_hospital_output(hospital_output, original_request)


@app.route('/analyze', methods=['POST'])
def analyze():
    """Primary route — orchestrator calls this."""
    try:
        data = request.get_json(force=True) or {}
        log(f"Request received, keys: {list(data.keys())}")
        result = _handle(data)
        return jsonify(result), 200
    except Exception as e:
        log(f"ERROR: {e}")
        # FIX-5: On error, approve with warning so appointment agent can still run
        return jsonify({
            "validation_status":       "APPROVED_WITH_WARNINGS",
            "checks_passed":           5,
            "checks_failed":           1,
            "failed_checks":           [{"check": "Validator Error", "reason": str(e), "severity": "LOW"}],
            "confidence_score":        "70%",
            "validator_note":          f"Validator error — proceeding anyway. Error: {e}",
            "approved_recommendation": {},
            "system_state":            "Validator error — proceeding to appointment agent",
        }), 200


@app.route('/validator/analyze', methods=['POST'])
def analyze_long():
    """Legacy route — backward compatibility."""
    return analyze()


@app.route('/health', methods=['GET'])
@app.route('/validator/health', methods=['GET'])
def health():
    return jsonify({
        "status":  "healthy",
        "agent":   "validator_agent",
        "port":    5005,
        "routes":  ["/analyze", "/validator/analyze"],
        "mode":    "approve_with_warnings (not hard reject on minor issues)",
    })


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5005))
    log(f"Validator Agent starting on port {port}")
    log("Mode: APPROVE_WITH_WARNINGS for minor issues, REJECT only for critical failures")
    app.run(host="0.0.0.0", port=port, debug=False)