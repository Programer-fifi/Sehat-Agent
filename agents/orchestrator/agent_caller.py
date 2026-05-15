import requests
import concurrent.futures

def call_agent(port, payload, log_trace):
    if port == 5001:
        path = "/symptom-agent/analyze"
    else:
        path = "/analyze"
    url = f"http://localhost:{port}{path}"
    log_trace(f"Calling agent on port {port} at {url}...")
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        log_trace(f"Received successful response from agent on port {port}")
        return response.json()
    except requests.exceptions.RequestException as e:
        log_trace(f"Agent on port {port} failed or timed out: {str(e)}")
        return {
            "error": True,
            "message": f"Failed to reach agent on port {port}",
            "details": str(e)
        }

def call_agents_parallel(ports, payload, log_trace):
    agent_outputs = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(ports))) as executor:
        future_to_port = {executor.submit(call_agent, port, payload, log_trace): port for port in ports}
        for future in concurrent.futures.as_completed(future_to_port):
            port = future_to_port[future]
            try:
                agent_outputs[port] = future.result()
            except Exception as e:
                log_trace(f"Agent {port} generated an exception: {e}")
                agent_outputs[port] = {"error": True, "message": "Exception", "details": str(e)}
    return agent_outputs

