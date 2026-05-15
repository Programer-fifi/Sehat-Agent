import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from symptom_agent import analyze_symptoms
from report_reader import process_medical_report

load_dotenv()

app = Flask(__name__)
CORS(app)

def log(message):
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[SYMPTOM AGENT] {timestamp} {message}")

@app.route('/symptom-agent/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "agent": "symptom_report_agent",
        "port": 5001
    })

@app.route('/symptom-agent/analyze', methods=['POST'])
def analyze():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data received"}), 400

    user_message = data.get("user_message", "").strip()
    session_id = data.get("session_id", "default")
    report_image_b64 = data.get("report_image", None)
    conversation_history = data.get("conversation_history", [])

    log(f"Request received - session: {session_id}")

    if not user_message and not report_image_b64:
        return jsonify({
            "agent": "symptom_report_agent",
            "status": "needs_followup",
            "follow_up_question": "Aap ki kya takleef hai? Batayein main madad karoon ga.",
            "disclaimer": "This is AI guidance only. Always consult a qualified doctor."
        })

    report_findings = None
    if report_image_b64:
        log("Report image received - processing...")
        report_findings = process_medical_report(report_image_b64, input_type="base64")
        if "error" in report_findings:
            log(f"Report error: {report_findings['error']}")

    if not user_message and report_findings:
        user_message = "Patient uploaded a medical report with no symptoms described."

    result = analyze_symptoms(
        user_message=user_message,
        report_findings=report_findings,
        conversation_history=conversation_history,
        session_id=session_id
    )

    return jsonify(result)

@app.route('/symptom-agent/follow-up', methods=['POST'])
def follow_up():
    data = request.get_json()

    if not data:
        return jsonify({"error": "No data received"}), 400

    user_message = data.get("user_message", "").strip()
    session_id = data.get("session_id", "default")
    conversation_history = data.get("conversation_history", [])
    report_findings = data.get("report_findings", None)

    log(f"Follow-up received - session: {session_id}")

    result = analyze_symptoms(
        user_message=user_message,
        report_findings=report_findings,
        conversation_history=conversation_history,
        session_id=session_id
    )

    return jsonify(result)

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5001))
    log(f"Symptom Agent starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
