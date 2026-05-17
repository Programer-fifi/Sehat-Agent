import json
import re
from flask import Flask, request, jsonify
from flask_cors import CORS

def validate_hospital_output(hospital_finder_output, original_request):
    failed_checks = []
    
    # Extract data
    req_dept = original_request.get("required_department", "")
    req_urgency = original_request.get("urgency_level", "").upper()
    req_pref = original_request.get("hospital_preference", "").upper()
    
    top_rec = hospital_finder_output.get("top_recommendation", {})
    alternatives = hospital_finder_output.get("alternatives", [])
    
    # Edge Cases First
    if not top_rec or hospital_finder_output.get("total_found", 0) == 0:
        return reject_response([], [{
            "check": "EDGE CASE - No Hospitals Found",
            "reason": "No hospitals found in 25km radius. Expanding search.",
            "severity": "CRITICAL"
        }], original_request, "No hospitals found in 25km radius. Expanding search.")
        
    if not top_rec.get("open_now", True):
        return reject_response([], [{
            "check": "EDGE CASE - Hospitals Closed",
            "reason": "All recommended hospitals are closed. Find 24/7 options.",
            "severity": "CRITICAL"
        }], original_request, "All recommended hospitals are closed. Find 24/7 options.")

    if req_urgency == "CRITICAL" and not top_rec.get("emergency", False):
        return reject_response([], [{
            "check": "EDGE CASE - CRITICAL + No Emergency",
            "reason": "CRITICAL case requires emergency facility. Current recommendation has no emergency unit.",
            "severity": "CRITICAL"
        }], original_request, "CRITICAL case requires emergency facility. Current recommendation has no emergency unit.")

    # If maps_link, rating, etc. are "blurry or incomplete" -> Handle as Check 4 or Edge Case
    phone = top_rec.get("phone", "")
    address = top_rec.get("address", "")
    maps_link = top_rec.get("maps_link", "")
    rating = top_rec.get("rating", "")
    
    if not maps_link or not rating or "null" in str(maps_link).lower():
        return reject_response([], [{
            "check": "EDGE CASE - Incomplete Data",
            "reason": "Incomplete hospital data received. Request fresh search.",
            "severity": "CRITICAL"
        }], original_request, "Incomplete hospital data received. Request fresh search.")


    # Main Checks
    # Check 1 - Department Match
    dept_match = top_rec.get("department", "") == req_dept
    if req_urgency == "CRITICAL":
        if not top_rec.get("emergency", False):
            dept_match = False
            
    if not dept_match:
        failed_checks.append({
            "check": "CHECK 1 - Department Match",
            "reason": f"Expected EXACT department '{req_dept}' and emergency=True for CRITICAL cases.",
            "severity": "HIGH"
        })

    # Check 2 - Preference Match
    if req_pref in ["GOVERNMENT", "PRIVATE"]:
        if top_rec.get("type", "").upper() != req_pref:
            failed_checks.append({
                "check": "CHECK 2 - Preference Match",
                "reason": f"User requested {req_pref} but {top_rec.get('type', 'unknown')} hospital was returned",
                "severity": "HIGH"
            })

    # Check 3 - Distance Sanity
    dist_str = top_rec.get("distance", "")
    try:
        dist_val = float(re.findall(r"[\d\.]+", dist_str)[0])
        
        is_nearest = True
        for alt in alternatives:
            alt_dist_str = alt.get("distance", "")
            if alt_dist_str:
                try:
                    alt_dist_val = float(re.findall(r"[\d\.]+", alt_dist_str)[0])
                    if alt_dist_val < dist_val:
                        is_nearest = False
                        break
                except:
                    pass
        
        if dist_val > 25 or not is_nearest:
            failed_checks.append({
                "check": "CHECK 3 - Distance Sanity",
                "reason": "Distance is over 25km or closer alternative was ignored.",
                "severity": "MEDIUM"
            })
    except:
        failed_checks.append({
            "check": "CHECK 3 - Distance Sanity",
            "reason": "Could not parse distance correctly.",
            "severity": "MEDIUM"
        })

    # Check 4 - Data Completeness
    if not phone or not address or not maps_link or not rating or str(phone).lower() == "unknown":
        failed_checks.append({
            "check": "CHECK 4 - Data Completeness",
            "reason": "Critical fields missing (phone, address, maps_link, rating) or invalid.",
            "severity": "HIGH"
        })

    # Check 5 - Emergency Override Check
    if req_urgency in ["HIGH", "CRITICAL"]:
        has_emergency = top_rec.get("emergency", False)
        has_note = bool(hospital_finder_output.get("emergency_note", ""))
        is_24_7 = top_rec.get("opening_hours", "") == "24/7"
        
        if not (has_emergency and has_note and is_24_7):
            failed_checks.append({
                "check": "CHECK 5 - Emergency Override Check",
                "reason": "HIGH/CRITICAL cases require emergency: true, emergency_note, and opening_hours 24/7.",
                "severity": "CRITICAL"
            })

    # Check 6 - Cost Comparison
    cost_comp = hospital_finder_output.get("cost_comparison", {})
    if not cost_comp or "government_option" not in cost_comp or "private_option" not in cost_comp:
        failed_checks.append({
            "check": "CHECK 6 - Cost Comparison",
            "reason": "cost_comparison missing or lacks govt/private options.",
            "severity": "MEDIUM"
        })

    # Check 7 - Reasoning Quality
    reasoning = hospital_finder_output.get("reasoning", "")
    if not reasoning or len(reasoning.split()) < 5 or ("best hospital" in reasoning.lower() and len(reasoning) < 20):
        failed_checks.append({
            "check": "CHECK 7 - Reasoning Quality",
            "reason": "Reasoning is empty, too short, or generic.",
            "severity": "MEDIUM"
        })

    if not failed_checks:
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
        hospital_output = data.get(
            "hospital_finder_output", {})
        original_request = data.get(
            "original_request", {})
        result = validate_hospital_output(
            hospital_output, original_request)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5005)
