import os
import json
import time 
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- FIX: Clean API Keys to eliminate "Illegal Header Value" gRPC Errors ---
for key in ["GEMINI_API_KEY_1", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"]:
    if os.getenv(key):
        os.environ[key] = os.getenv(key).strip()

# Import after cleaning keys to make sure modules get the clean strings
from symptom_agent import analyze_symptoms
from report_reader import process_medical_report

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
    try:
        data = request.get_json(force=True)

        if not data:
            return jsonify({"error": "No data received"}), 400

        user_message          = data.get("user_message", "").strip()
        session_id            = data.get("session_id", "default")
        report_image_b64      = data.get("report_image", None)
        conversation_history  = data.get("conversation_history", [])

        log(f"Request received - session: {session_id}")

        # No message and no report
        if not user_message and not report_image_b64:
            return jsonify({
                "agent": "symptom_report_agent",
                "status": "needs_followup",
                "follow_up_question": "Aap ki kya takleef hai? Batayein main madad karoon ga.",
                "disclaimer": "This is AI guidance only. Always consult a qualified doctor."
            })

        # Process report if provided
        report_findings = None
        if report_image_b64:
            log("Report image received - processing...")
            report_findings = process_medical_report(report_image_b64, input_type="base64")
            if report_findings.get("error"):
                log(f"Report error: {report_findings['error']}")
                # Don't block — continue with error info in findings

        # If only report uploaded with no message
        if not user_message and report_findings:
            if report_findings.get("error"):
                # Report had an error — ask for clearer image or symptoms
                return jsonify({
                    "agent": "symptom_report_agent",
                    "status": "needs_followup",
                    "follow_up_question": report_findings["error"],
                    "report_findings": report_findings,
                    "disclaimer": "This is AI guidance only. Always consult a qualified doctor."
                })
            else:
                user_message = "Patient uploaded a medical report with no symptoms described."

        result = analyze_symptoms(
            user_message=user_message,
            report_findings=report_findings,
            conversation_history=conversation_history,
            session_id=session_id
        )

        return jsonify(result)

    except Exception as e:
        log(f"ERROR in /analyze: {str(e)}")
        return jsonify({
            "agent": "symptom_report_agent",
            "status": "complete",
            "urgency_level": "MEDIUM",
            "recommended_department": "General Medicine",
            "follow_up_question": None,
            "error": str(e),
            "disclaimer": "This is AI guidance only. Always consult a qualified doctor."
        }), 500


@app.route('/symptom-agent/follow-up', methods=['POST'])
def follow_up():
    try:
        data = request.get_json(force=True)

        if not data:
            return jsonify({"error": "No data received"}), 400

        user_message          = data.get("user_message", "").strip()
        session_id            = data.get("session_id", "default")
        conversation_history  = data.get("conversation_history", [])
        report_findings       = data.get("report_findings", None)

        log(f"Follow-up received - session: {session_id}")

        if not user_message:
            return jsonify({"error": "user_message is required"}), 400

        result = analyze_symptoms(
            user_message=user_message,
            report_findings=report_findings,
            conversation_history=conversation_history,
            session_id=session_id
        )

        return jsonify(result)

    except Exception as e:
        log(f"ERROR in /follow-up: {str(e)}")
        return jsonify({
            "agent": "symptom_report_agent",
            "status": "complete",
            "urgency_level": "MEDIUM",
            "recommended_department": "General Medicine",
            "error": str(e),
            "disclaimer": "This is AI guidance only. Always consult a qualified doctor."
        }), 500


if __name__ == '__main__':
    port = int(os.getenv("PORT", 5001))
    log(f"Symptom Agent starting on port {port}")
    # FIX: debug=False for stability
    app.run(host='0.0.0.0', port=port, debug=False)
