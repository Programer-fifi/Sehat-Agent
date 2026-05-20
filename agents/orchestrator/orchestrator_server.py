from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from orchestrator import process_request
import os

load_dotenv()

app = Flask(__name__, static_folder=None)
CORS(app)

# In-memory session trace store
session_traces = {}
MAX_SESSIONS = 100


def _cleanup_old_sessions():
    """Remove oldest sessions if we exceed MAX_SESSIONS."""
    if len(session_traces) > MAX_SESSIONS:
        oldest_keys = list(session_traces.keys())[:-MAX_SESSIONS]
        for key in oldest_keys:
            del session_traces[key]


# ── Static file serving ───────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')


@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory('static', path)


# ── Main analyze endpoint ─────────────────────────────────────

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload provided"}), 400

    user_message = (
        data.get("message") or
        data.get("user_message") or
        ""
    ).strip()

    session_id = data.get("session_id", "").strip()
    report_image = data.get("image") or data.get("report_image")
    conversation_history = (
        data.get("history") or
        data.get("conversation_history") or
        []
    )
    language = data.get("language", "roman_urdu")

    # ── City and Area from location selector ──────────────────
    city = (data.get("city") or "").strip().lower()
    area = (data.get("area") or "").strip()

    if not user_message:
        return jsonify({
            "error": "message is required",
            "hint": "Send user_message or message field"
        }), 400

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    response = process_request(
        user_message,
        session_id,
        report_image,
        conversation_history,
        language,
        city=city,
        area=area,
    )

    session_traces[session_id] = response.get("agent_trace", [])
    _cleanup_old_sessions()

    return jsonify(response)


# ── Follow-up endpoint ────────────────────────────────────────

@app.route('/follow-up', methods=['POST'])
def follow_up():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload provided"}), 400

    user_message = (
        data.get("message") or
        data.get("user_message") or
        ""
    ).strip()

    session_id = data.get("session_id", "").strip()
    conversation_history = (
        data.get("history") or
        data.get("conversation_history") or
        []
    )
    language = data.get("language", "roman_urdu")

    # Preserve city/area for follow-up context
    city = (data.get("city") or "").strip().lower()
    area = (data.get("area") or "").strip()

    if not user_message:
        return jsonify({"error": "message is required for follow-up"}), 400

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    response = process_request(
        user_message,
        session_id,
        None,
        conversation_history,
        language,
        city=city,
        area=area,
    )

    new_traces = response.get("agent_trace", [])
    if session_id in session_traces:
        session_traces[session_id].extend(new_traces)
    else:
        session_traces[session_id] = new_traces

    response["agent_trace"] = session_traces[session_id]
    _cleanup_old_sessions()

    return jsonify(response)


# ── Health check ──────────────────────────────────────────────

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "healthy",
        "agent": "main_orchestrator",
        "port": 5000
    })


# ── Agent trace endpoint ──────────────────────────────────────

@app.route('/trace/<session_id>', methods=['GET'])
def trace(session_id):
    traces = session_traces.get(session_id, [])
    return jsonify({"session_id": session_id, "trace": traces})


# ── Entry point ───────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "false").lower() == "true"
    print(f"Starting Orchestrator Server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=debug)
