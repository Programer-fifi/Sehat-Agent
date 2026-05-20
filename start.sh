#!/bin/bash
set -e

echo "Starting Sehat Agent — All Services"

export GEMINI_API_KEY=${GEMINI_API_KEY}
export GEMINI_API_KEY_2=${GEMINI_API_KEY_2}
export GOOGLE_PLACES_API_KEY=${GOOGLE_PLACES_API_KEY}

# Start Symptom Agent (5001)
cd /app/agents/symptom-agent && PORT=5001 python symptom_agent_server.py &

# Start Hospital Finder (5002)
cd /app/agents/hospital-finder && PORT=5002 python agent.py &

# Start Cost Agent (5003)
cd /app/agents/cost-agent && PORT=5003 python agent.py &

# Start Appointment Agent (5004)
cd /app/agents/appointment-agent && PORT=5004 python agent.py &

# Start Validator Agent (5005)
cd /app/agents/Validator\ Agent && PORT=5005 python agent.py &

# Wait for agents to start
sleep 5

# Start Orchestrator on port 7860 (HuggingFace default)
cd /app/agents/orchestrator && PORT=7860 python orchestrator_server.py