import time

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
    
    # If emergency, override urgency level and do_not_delay
    if intent == "EMERGENCY":
        urgency_level = "CRITICAL"
        recommended_department = "Emergency"
        do_not_delay = True
    
    for port, output in agent_outputs.items():
        if type(output) != dict:
            continue
        if output.get("error"):
            continue
            
        # Try to extract common fields regardless of port if they exist
        # (Skipped for EMERGENCY — those values are locked in below)
        if intent != "EMERGENCY":
            if "urgency_level" in output:
                urgency_level = output["urgency_level"]
            if "recommended_department" in output:
                recommended_department = output["recommended_department"]
            if "do_not_delay" in output:
                do_not_delay = output["do_not_delay"]
        if "symptoms_summary" in output:
            symptoms_summary = output["symptoms_summary"]
            
        # Extract specific fields based on port or standard structure
        if port == 5002 or "hospital_recommendation" in output:
            hospital_recommendation = output.get("hospital_recommendation", output)
        if port == 5003:
            # Cost agent returns full dict — preserve it as-is
            cost_estimate = output
        elif "cost_estimate" in output:
            cost_estimate = output.get("cost_estimate")
        if port == 5004:
            # Appointment agent returns token_number, booking_status, etc.
            if output.get("booking_status") == "confirmed":
                appointment = (
                    f"Token: {output.get('token_number', 'N/A')} | "
                    f"{output.get('appointment_date', '')} at {output.get('appointment_time', '')} | "
                    f"{output.get('hospital', '')} — {output.get('department', '')}"
                )
            elif output.get("booking_status") == "unavailable":
                appointment = "Appointment booking temporarily unavailable. Please call the hospital directly."
            elif "appointment" in output and output["appointment"]:
                appointment = output["appointment"]
            
        # Follow up logic
        if "follow_up_question" in output and output["follow_up_question"]:
            if not follow_up_question:
                follow_up_question = output["follow_up_question"]
    
    # Re-apply EMERGENCY overrides AFTER agent loop to prevent agents overwriting them
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
