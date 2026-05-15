import os
import time
from datetime import datetime
from google import genai
from agent_caller import call_agent, call_agents_parallel
from response_combiner import combine_responses

def fallback_intent(text):
    text = text.lower()
    if any(word in text for word in ['emergency', 'heart attack', 'bleeding', 'stroke', 'dying', 'help fast', 'urgent', 'behosh']):
        return "EMERGENCY"
    elif any(word in text for word in ['book', 'appointment', 'schedule']):
        return "APPOINTMENT_NEEDED"
    elif any(word in text for word in ['hospital', 'clinic', 'where to go', 'location']):
        return "HOSPITAL_NEEDED"
    elif any(word in text for word in ['cost', 'price', 'fee', 'expensive', 'charge']):
        return "COST_INQUIRY"
    elif any(word in text for word in ['report', 'lab', 'test', 'result', 'xray', 'mri']):
        return "REPORT_ANALYSIS"
    return "SYMPTOM_ONLY"

def detect_intent(user_message, trace_logs):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        msg = f"[MAIN AGENT] {datetime.now().strftime('%H:%M:%S')} GEMINI_API_KEY not found. Using fallback."
        print(msg)
        trace_logs.append(msg)
        return fallback_intent(user_message)

    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""
        Analyze the following user message and classify its intent into EXACTLY ONE of the following categories:
        SYMPTOM_ONLY, HOSPITAL_NEEDED, APPOINTMENT_NEEDED, REPORT_ANALYSIS, COST_INQUIRY, FULL_SERVICE, EMERGENCY.
        
        Rules for classification:
        - If it's a severe medical emergency (heart attack, severe bleeding, stroke, etc.), classify as EMERGENCY.
        - If they only want to know about symptoms or diseases, classify as SYMPTOM_ONLY.
        - If they want to find a hospital, classify as HOSPITAL_NEEDED.
        - If they want to book an appointment, classify as APPOINTMENT_NEEDED.
        - If they upload or mention a medical report, classify as REPORT_ANALYSIS.
        - If they ask about costs or prices, classify as COST_INQUIRY.
        - If they ask for multiple things (e.g., symptoms AND booking an appointment), classify as FULL_SERVICE.
        
        User Message: {user_message}
        
        Output ONLY the category name. No other text.
        """
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
        )
        intent = response.text.strip().upper()
        valid_intents = ["SYMPTOM_ONLY", "HOSPITAL_NEEDED", "APPOINTMENT_NEEDED", "REPORT_ANALYSIS", "COST_INQUIRY", "FULL_SERVICE", "EMERGENCY"]
        if intent not in valid_intents:
            return fallback_intent(user_message)
        return intent
    except Exception as e:
        msg = f"[MAIN AGENT] {datetime.now().strftime('%H:%M:%S')} Gemini API error (fallback triggered): {str(e)}"
        print(msg)
        trace_logs.append(msg)
        return fallback_intent(user_message)

def process_request(user_message, session_id, report_image=None, conversation_history=None):
    start_time = time.time()
    trace_logs = []
    
    def log_trace(message):
        log_msg = f"[MAIN AGENT] {datetime.now().strftime('%H:%M:%S')} {message}"
        print(log_msg)
        trace_logs.append(log_msg)

    log_trace(f"Starting orchestration for session {session_id}")
    
    intent = detect_intent(user_message, trace_logs)
    log_trace(f"Detected intent: {intent}")
    
    ports_to_call = []
    if intent == "SYMPTOM_ONLY" or intent == "REPORT_ANALYSIS":
        ports_to_call = [5001]
    elif intent == "HOSPITAL_NEEDED":
        ports_to_call = [5002]
    elif intent == "APPOINTMENT_NEEDED":
        ports_to_call = [5002, 5004]
    elif intent == "COST_INQUIRY":
        ports_to_call = [5003]
    elif intent == "FULL_SERVICE" or intent == "EMERGENCY":
        ports_to_call = [5001, 5002, 5003, 5004]
        
    log_trace(f"Routing to agents on ports: {ports_to_call}")
    
    payload = {
        "session_id": session_id,
        "user_message": user_message,
        "conversation_history": conversation_history or []
    }
    if report_image:
        payload["report_image"] = report_image
        
    log_trace("Dispatching payloads to agents in parallel")
    agent_outputs = call_agents_parallel(ports_to_call, payload, log_trace)
    agents_used = [f"Agent-{port}" for port in ports_to_call]
        
    log_trace("Combining agent responses")
    final_response = combine_responses(session_id, intent, agents_used, agent_outputs, start_time, trace_logs)
    
    # Refresh trace logs to include the latest additions
    final_response["agent_trace"] = trace_logs
    
    return final_response
