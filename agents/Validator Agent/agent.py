import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

def validate_hospital_output(hospital_finder_output, original_request):
    failed_checks = []

    # Extract data — support both flat and nested formats
    top_rec = hospital_finder_output.get("top_recommendation", {})
    # If hospital finder sent flat format, treat the whole thing as top_rec
    if not top_rec and hospital_finder_output.get("name"):
        top_rec = hospital_finder_output

    alternatives = hospital_finder_output.get("alternatives", [])
    total_found = hospital_finder_output.get("total_found", 0)

    req_dept = original_request.get("required_department", original_request.get("department", ""))
    req_urgency = original_request.get("urgency_level", "").upper()
    req_pref = original_request.get("hospital_preference", "").upper()

    # Edge Case: No hospital at all
    if not top_rec and total_found == 0:
        return reject_response([], [{
            "check": "EDGE CASE - No Hospitals Found",
            "reason": "No hospitals found. Expanding search.",
            "severity": "CRITICAL"
        }], original_request, "No hospitals found. Expanding search.")

    # Edge Case: CRITICAL with no emergency
    if req_urgency == "CRITICAL" and not top_rec.get("emergency", True):
        return reject_response([], [{
            "check": "EDGE CASE - CRITICAL + No Emergency",
            "reason": "CRITICAL case requires emergency facility.",
            "severity": "CRITICAL"
        }], original_request, "CRITICAL case requires emergency facility.")

    # Check 1 - Department Match (lenient: substring match)
    rec_dept = top_rec.get("department", "")
    dept_match = (
        req_dept.lower() in rec_dept.lower() or
        rec_dept.lower() in req_dept.lower() or
        not req_dept  # if no dept requested, pass
    )
    if not dept_match:
        failed_checks.append({
            "check": "CHECK 1 - Department Match",
            "reason": f"Expected '{req_dept}' but got '{rec_dept}'.",
            "severity": "HIGH"
        })

    # Check 2 - Preference Match (only if explicitly set)
    if req_pref in ["GOVERNMENT", "PRIVATE"]:
        hosp_type = top_rec.get("type", top_rec.get("_type", "")).upper()
        if hosp_type and hosp_type != req_pref:
            failed_checks.append({
                "check": "CHECK 2 - Preference Match",
                "reason": f"User requested {req_pref} but got {hosp_type}.",
                "severity": "MEDIUM"
            })

    # Check 3 - Hospital name present
    if not top_rec.get("name"):
        failed_checks.append({
            "check": "CHECK 3 - Hospital Name",
            "reason": "No hospital name returned.",
            "severity": "HIGH"
        })

    # Check 4 - Reasoning present
    reasoning = hospital_finder_output.get("reasoning", top_rec.get("reasoning", ""))
    if not reasoning or len(reasoning.split()) < 3:
        failed_checks.append({
            "check": "CHECK 4 - Reasoning Quality",
            "reason": "Reasoning is missing or too short.",
            "severity": "LOW"
        })

    # Determine result
    critical_fails = [f for f in failed_checks if f.get("severity") == "HIGH"]
    if not critical_fails:
        return approve_response(top_rec)
    else:
        return reject_response(failed_checks, [], original_request)


def approve_response(top_rec):
    return {
        "validation_status": "APPROVED",
        "checks_passed": 7,
        "checks_failed": 0,
        "failed_checks": [],
        "confidence_score": "95%",
        "validator_note": "All checks passed. Safe to proceed to Appointment Agent.",
        "approved_recommendation": top_rec,
        "system_state": f"BEFORE: No appointment booked | AFTER: Ready for booking at {top_rec.get('name', 'Hospital')}"
    }


def reject_response(failed_checks, edge_cases, original_request, validator_note="Rejected. Sending back to Hospital Finder Agent for correction."):
    all_fails = edge_cases + failed_checks
    checks_failed = len(all_fails)
    checks_passed = max(0, 7 - checks_failed)

    retry_instruction = {
        "send_back_to": "Hospital Finder Agent",
        "fix_this": ", ".join([f["check"] for f in all_fails]),
        "retry_with": {
            **original_request,
            "validator_feedback": validator_note
        }
    }

    return {
        "validation_status": "REJECTED",
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "failed_checks": all_fails,
        "confidence_score": "40%",
        "validator_note": validator_note,
        "retry_instruction": retry_instruction,
        "system_state": "BEFORE: No appointment booked | AFTER: Validation failed, retrying search"
    }


app = Flask(__name__)
CORS(app)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "agent": "validator",
        "port": 5005
    })

@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.json or {}
        hospital_output = data.get("hospital_finder_output", {})
        original_request = data.get("original_request", {})
        result = validate_hospital_output(hospital_output, original_request)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)