#!/bin/bash
set -e

echo "🚀 Starting Sehat Agent — All Services"

# Export API keys for all agents
export GEMINI_API_KEY=${GEMINI_API_KEY}
export GEMINI_API_KEY_2=${GEMINI_API_KEY_2}

# Start Symptom Agent (5001)
echo "Starting Symptom Agent on port 5001..."
cd /app/agents/symptom-agent && python symptom_agent_server.py &

# Start Hospital Finder (5002)
echo "Starting Hospital Finder on port 5002..."
cd /app/agents/hospital-finder && python agent.py &

# Start Cost Agent (5003)
echo "Starting Cost Agent on port 5003..."
cd /app/agents/cost-agent && python agent.py &

# Start Appointment Agent (5004)
echo "Starting Appointment Agent on port 5004..."
cd /app/agents/appointment-agent && python agent.py &

# Start Validator Agent (5005)
echo "Starting Validator Agent on port 5005..."
cd /app/agents/Validator\ Agent && python agent.py &

# Wait for all agents to start
echo "Waiting for agents to initialize..."
sleep 5

# Start Orchestrator (5000) — main entry point
echo "Starting Orchestrator on port 5000..."
cd /app/agents/orchestrator && python orchestrator_server.py