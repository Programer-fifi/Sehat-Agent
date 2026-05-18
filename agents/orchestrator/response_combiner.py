import time


def _format_cost(cost_data) -> str:
    """
    Safely convert any cost format to a human-readable PKR string.
    Handles: plain string, nested dict from cost agent, None.
    """
    if cost_data is None:
        return None

    if isinstance(cost_data, str):
        # Already a string — guard against [object Object] leaking in
        if cost_data.strip() and cost_data != "[object Object]":
            return cost_data
        return None

    if isinstance(cost_data, dict):
        # Cost agent returns: { estimated_cost: { minimum, maximum, currency }, ... }
        ec = cost_data.get("estimated_cost", cost_data)
        if isinstance(ec, dict):
            currency = ec.get("currency", "PKR")
            minimum = ec.get("minimum", 0)
            maximum = ec.get("maximum", 0)
            if minimum or maximum:
                return f"{currency} {int(minimum):,} – {int(maximum):,}"

        # Some agents return breakdown dict directly
        breakdown = cost_data.get("breakdown", {})
        consult = breakdown.get("consultation", "")
        if consult:
            return consult

    return None


def combine_responses(session_id, intent, agents_used, agent_outputs, start_time, trace_logs):
    total_time = round(time.time() - start_time, 2)

    # Initialize defaults
    urgency_level = "normal"
    symptoms_summary = "Not evaluated"
    recommended_department = "General Physician"
    hospital_recommendation = None
    cost_estimate = None
    appointment = None
    follow_up_question = None
    do_not_delay = False

    # Emergency overrides
    if intent == "EMERGENCY":
        urgency_level = "CRITICAL"
        recommended_department = "Emergency"
        do_not_delay = True

    for port, output in agent_outputs.items():
        if not isinstance(output, dict):
            continue
        if output.get("error"):
            continue

        # Common fields (skip for EMERGENCY — locked above)
        if intent != "EMERGENCY":
            if "urgency_level" in output:
                urgency_level = output["urgency_level"]
            if "recommended_department" in output:
                recommended_department = output["recommended_department"]
            if "do_not_delay" in output:
                do_not_delay = output["do_not_delay"]

        if "symptoms_summary" in output:
            symptoms_summary = output["symptoms_summary"]

        # ── Hospital finder (port 5002) ───────────────────────────────────────
        if port == 5002:
            top_rec = output.get("top_recommendation", {})
            if top_rec and isinstance(top_rec, dict):
                hospital_recommendation = top_rec.get("name", output.get("hospital_recommendation"))
            elif "hospital_recommendation" in output:
                hospital_recommendation = output["hospital_recommendation"]
            else:
                hospital_recommendation = output

        # ── Cost agent (port 5003) ────────────────────────────────────────────
        if port == 5003:
            cost_estimate = _format_cost(output)

        elif "cost_estimate" in output:
            # Some agents embed a cost_estimate field
            raw = output["cost_estimate"]
            formatted = _format_cost(raw)
            if formatted and cost_estimate is None:
                cost_estimate = formatted

        # ── Appointment agent (port 5004) ─────────────────────────────────────
        if port == 5004:
            booking_status = output.get("booking_status", "")
            token = output.get("token_number", "N/A")
            appt_date = output.get("appointment_date", "")
            appt_time = output.get("appointment_time", "")
            hosp = output.get("hospital", "")
            dept = output.get("department", "")

            if booking_status == "confirmed" and token:
                # Build the pipe-delimited string the UI expects
                appointment = (
                    f"Token: {token} | "
                    f"{appt_date} at {appt_time} | "
                    f"{hosp} — {dept}"
                )
            elif booking_status == "failed":
                appointment = (
                    f"Appointment booking failed: {output.get('error', 'Unknown error')}. "
                    f"Please call the hospital directly."
                )
            elif booking_status == "unavailable":
                appointment = (
                    "Appointment booking temporarily unavailable. "
                    "Please call the hospital directly."
                )
            elif output.get("appointment"):
                appointment = output["appointment"]

        # ── Follow-up question ────────────────────────────────────────────────
        if "follow_up_question" in output and output["follow_up_question"]:
            if not follow_up_question:
                follow_up_question = output["follow_up_question"]

    # Re-apply EMERGENCY overrides AFTER agent loop
    if intent == "EMERGENCY":
        urgency_level = "CRITICAL"
        recommended_department = "Emergency"
        do_not_delay = True
        follow_up_question = None

    return {
        "session_id": session_id,
        "intent": intent,
        "agents_used": agents_used,
        "urgency_level": urgency_level,
        "symptoms_summary": symptoms_summary,
        "recommended_department": recommended_department,
        "hospital_recommendation": hospital_recommendation,
        "cost_estimate": cost_estimate,
        "appointment": appointment,
        "follow_up_question": follow_up_question,
        "agent_trace": trace_logs,
        "total_time_seconds": total_time,
        "agents_count": len(agents_used),
        "disclaimer": "This is AI guidance only. Always consult a qualified doctor.",
        "do_not_delay": do_not_delay
    }