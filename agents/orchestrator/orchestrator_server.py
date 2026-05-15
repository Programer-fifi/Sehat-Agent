from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from orchestrator import process_request

load_dotenv()

app = Flask(__name__)
CORS(app)

session_traces = {}

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload provided"}), 400
        
    user_message = data.get("user_message")
    session_id = data.get("session_id")
    report_image = data.get("report_image")
    conversation_history = data.get("conversation_history", [])
    
    if not user_message or not session_id:
        return jsonify({"error": "user_message and session_id are required"}), 400
        
    response = process_request(user_message, session_id, report_image, conversation_history)
    session_traces[session_id] = response.get("agent_trace", [])
    
    return jsonify(response)

@app.route('/follow-up', methods=['POST'])
def follow_up():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload provided"}), 400
        
    user_message = data.get("user_message")
    session_id = data.get("session_id")
    conversation_history = data.get("conversation_history", [])
    previous_response = data.get("previous_response", {}) # Requested in prompt
    
    if not user_message or not session_id:
        return jsonify({"error": "user_message and session_id are required"}), 400
        
    response = process_request(user_message, session_id, None, conversation_history)
    
    # Append to existing trace if any
    if session_id in session_traces:
        session_traces[session_id].extend(response.get("agent_trace", []))
    else:
        session_traces[session_id] = response.get("agent_trace", [])
        
    response["agent_trace"] = session_traces[session_id]
    
    return jsonify(response)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy", 
        "agent": "main_orchestrator",
        "port": 5000
    })

@app.route('/trace/<session_id>', methods=['GET'])
def trace(session_id):
    traces = session_traces.get(session_id, [])
    return jsonify({"session_id": session_id, "trace": traces})

if __name__ == '__main__':
    print("Starting Orchestrator Server on port 5000...")
    app.run(host='0.0.0.0', port=5000)
