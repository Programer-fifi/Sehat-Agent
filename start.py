"""
start.py — Sehat Agent unified launcher for Render free deployment
All 6 agents run in one process on separate ports via threads.
"""

import threading
import sys
import os
import time
import importlib.util

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_and_run(agent_dir, server_filename, port):
    """Load an agent module and run its Flask app."""
    agent_path = os.path.join(ROOT, 'agents', agent_dir)

    # Add to sys.path so relative imports inside agents work
    if agent_path not in sys.path:
        sys.path.insert(0, agent_path)

    os.environ['PORT'] = str(port)

    full_path = os.path.join(agent_path, server_filename)
    spec = importlib.util.spec_from_file_location(f"mod_{port}", full_path)
    mod = importlib.util.new_module(f"mod_{port}")
    spec.loader.exec_module(mod)

    print(f"[LAUNCHER] {agent_dir} running on :{port}", flush=True)
    mod.app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def start_thread(agent_dir, server_filename, port):
    t = threading.Thread(
        target=load_and_run,
        args=(agent_dir, server_filename, port),
        daemon=True,
        name=f"agent-{port}"
    )
    t.start()
    return t


if __name__ == '__main__':
    print("[LAUNCHER] Starting Sehat Agent — all services", flush=True)

    # Sub-agents — start in background threads
    start_thread('symptom-agent',     'symptom_agent_server.py', 5001)
    start_thread('hospital-finder',   'agent.py',                5002)
    start_thread('cost-agent',        'agent.py',                5003)
    start_thread('appointment-agent', 'agent.py',                5004)
    start_thread('Validator Agent',   'agent.py',                5005)

    # Wait for sub-agents to bind their ports before orchestrator calls them
    print("[LAUNCHER] Waiting 5s for sub-agents to bind...", flush=True)
    time.sleep(5)

    # Orchestrator — runs on main thread (keeps process alive)
    # Add all agent paths so cross-imports work
    for d in ['orchestrator', 'symptom-agent', 'hospital-finder',
              'cost-agent', 'appointment-agent', 'Validator Agent']:
        p = os.path.join(ROOT, 'agents', d)
        if p not in sys.path:
            sys.path.insert(0, p)

    orch_path = os.path.join(ROOT, 'agents', 'orchestrator', 'orchestrator_server.py')
    spec = importlib.util.spec_from_file_location("orchestrator_server", orch_path)
    mod = importlib.util.new_module("orchestrator_server")
    spec.loader.exec_module(mod)

    port = int(os.environ.get('PORT', 10000))
    print(f"[LAUNCHER] Orchestrator live on :{port} ✅", flush=True)
    mod.app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)