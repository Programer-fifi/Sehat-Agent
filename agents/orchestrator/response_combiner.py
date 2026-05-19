"""
response_combiner.py  —  UPDATED VERSION
────────────────────────────────────────────────────────────────
PREVIOUS FIXES (unchanged):
  FIX-1  Cost estimate extracts PKR amounts correctly
  FIX-2  Hospital recommendation: APPROVED_WITH_WARNINGS accepted
  FIX-3  Appointment booking_status check relaxed
  FIX-4  Emergency overrides applied AFTER loop
  FIX-5  hospital_recommendation passes full object

NEW IN THIS UPDATE:
  UPDATE-1  Appointment agent's internal_logs injected into trace_logs
             → UI trace panel now shows detailed booking steps
  UPDATE-2  Emergency walk-in (booking_status="emergency_walk_in") handled
             → Shows "Walk In Immediately — Nearest ER" in appointment card
"""

import time


def combine_responses(session_id, intent, agents_used, agent_outputs, start_time, trace_logs):
    total_time = round(time.time() - start_time, 2)

    # ── Defaults ──────────────────────────────────────────────────────────────
    urgency_level          = "LOW"
    symptoms_summary       = None
    recommended_department = "General Medicine"
    hospital_recommendation = None
    cost_estimate          = None
    appointment            = None
    patient_pass           = None
    sms_simulation         = None
    follow_up_question     = None
    do_not_delay           = False
    before_state           = None
    after_state            = None

    # Emergency pre-set
    if intent == "EMERGENCY":
        urgency_level          = "CRITICAL"
        recommended_department = "Emergency"
        do_not_delay           = True

    # ── Process each agent output ─────────────────────────────────────────────
    for port, output in agent_outputs.items():
        if not isinstance(output, dict):
            continue
        if output.get("error") and len(output) <= 2:
            continue

        # ── Symptom Agent (5001) ──────────────────────────────────────────────
        if port == 5001:
            if intent != "EMERGENCY":
                if output.get("urgency_level"):
                    urgency_level = output["urgency_level"]
                if output.get("recommended_department"):
                    recommended_department = output["recommended_department"]
                if output.get("do_not_delay") is not None:
                    do_not_delay = output["do_not_delay"]

            symptoms_summary = (
                output.get("symptoms_summary") or
                output.get("combined_analysis") or
                output.get("user_message") or
                symptoms_summary
            )

            if output.get("follow_up_question") and not follow_up_question:
                if intent != "EMERGENCY":
                    follow_up_question = output["follow_up_question"]

        # ── Hospital Finder (5002) ────────────────────────────────────────────
        elif port == 5002:
            top = output.get("top_recommendation")
            if isinstance(top, dict) and top.get("name"):
                hospital_recommendation = {
                    "name":      top.get("name", ""),
                    "address":   top.get("address", ""),
                    "phone":     top.get("phone", ""),
                    "maps_link": top.get("maps_link", ""),
                    "rating":    top.get("rating", "N/A"),
                    "type":      top.get("type", ""),
                    "emergency": top.get("emergency", False),
                }
            elif output.get("hospital_name"):
                hospital_recommendation = {"name": output["hospital_name"]}
            else:
                hospital_recommendation = {"name": "Please visit nearest hospital"}

        # ── Cost Agent (5003) ─────────────────────────────────────────────────
        elif port == 5003:
            if output.get("estimated_cost"):
                ec      = output["estimated_cost"]
                minimum = ec.get("minimum", 0)
                maximum = ec.get("maximum", 0)
                if minimum > 0 or maximum > 0:
                    cost_estimate = output
                else:
                    cost_estimate = {
                        **output,
                        "estimated_cost": {
                            "minimum":  1000,
                            "maximum":  5000,
                            "currency": "PKR",
                        }
                    }
            else:
                cost_estimate = output

        # ── Appointment Agent (5004) ──────────────────────────────────────────
        elif port == 5004:
            booking_status = output.get("booking_status", "")

            # UPDATE-1: inject appointment agent's internal_logs into UI trace
            appt_internal_logs = output.get("internal_logs", [])
            if appt_internal_logs:
                trace_logs.extend(appt_internal_logs)

            # UPDATE-2: emergency walk-in — no appointment needed
            if booking_status == "emergency_walk_in":
                appointment = (
                    "Walk In Immediately — No Appointment Needed | "
                    "Go to Nearest Emergency Room"
                )
                if output.get("patient_pass"):
                    patient_pass = output["patient_pass"]
                if output.get("sms_simulation"):
                    sms_simulation = output["sms_simulation"]
                before_state = output.get("before_state")
                after_state  = output.get("after_state")

            elif booking_status == "confirmed":
                token     = output.get("token_number", "N/A")
                appt_date = output.get("appointment_date", "")
                appt_time = output.get("appointment_time", "")
                hospital  = output.get("hospital", "")
                dept      = output.get("department", "")

                appointment = (
                    f"Token: {token} | "
                    f"{appt_date} at {appt_time} | "
                    f"{hospital}"
                )
                if dept:
                    appointment += f" — {dept}"

                if output.get("patient_pass"):
                    patient_pass = output["patient_pass"]
                if output.get("sms_simulation"):
                    sms_simulation = output["sms_simulation"]
                before_state = output.get("before_state")
                after_state  = output.get("after_state")

            elif booking_status == "unavailable":
                appointment = "Appointment booking temporarily unavailable. Please call hospital directly."

            else:
                token     = output.get("token_number")
                appt_date = output.get("appointment_date")
                appt_time = output.get("appointment_time")
                if token and appt_date and appt_time:
                    appointment = f"Token: {token} | {appt_date} at {appt_time}"
                    if output.get("patient_pass"):
                        patient_pass = output["patient_pass"]
                    if output.get("sms_simulation"):
                        sms_simulation = output["sms_simulation"]
                    before_state = output.get("before_state")
                    after_state  = output.get("after_state")
                else:
                    appointment = "Appointment details unavailable. Please contact the hospital directly."

        # ── Validator (5005) ─────────────────────────────────────────────────
        elif port == 5005:
            v_status = output.get("validation_status", "")
            if v_status in ("APPROVED", "APPROVED_WITH_WARNINGS"):
                approved = output.get("approved_recommendation", {})
                if isinstance(approved, dict) and approved.get("name"):
                    hospital_recommendation = {
                        "name":      approved.get("name", ""),
                        "address":   approved.get("address", ""),
                        "phone":     approved.get("phone", ""),
                        "maps_link": approved.get("maps_link", ""),
                        "rating":    approved.get("rating", "N/A"),
                        "type":      approved.get("type", ""),
                        "emergency": approved.get("emergency", False),
                    }

    # ── FIX-4: Re-apply emergency overrides AFTER loop ────────────────────────
    if intent == "EMERGENCY":
        urgency_level          = "CRITICAL"
        recommended_department = "Emergency"
        do_not_delay           = True
        follow_up_question     = None

    # ── Extract hospital display string for UI ────────────────────────────────
    hospital_display = None
    if isinstance(hospital_recommendation, dict):
        hospital_display = hospital_recommendation.get("name", "Please visit nearest hospital")
    elif isinstance(hospital_recommendation, str):
        hospital_display = hospital_recommendation

    # ── Build final response ──────────────────────────────────────────────────
    return {
        "session_id":              session_id,
        "intent":                  intent,
        "agents_used":             agents_used,
        "urgency_level":           urgency_level,
        "symptoms_summary":        symptoms_summary or "Symptoms received — see department recommendation below.",
        "recommended_department":  recommended_department,
        "hospital_recommendation": hospital_display,
        "hospital_details":        hospital_recommendation,
        "cost_estimate":           cost_estimate,
        "appointment":             appointment,
        "patient_pass":            patient_pass,
        "sms_simulation":          sms_simulation,
        "follow_up_question":      follow_up_question,
        "before_state":            before_state,
        "after_state":             after_state,
        "agent_trace":             trace_logs,
        "total_time_seconds":      total_time,
        "agents_count":            len(agents_used),
        "disclaimer":              "This is AI guidance only. Always consult a qualified doctor.",
        "do_not_delay":            do_not_delay,
    }