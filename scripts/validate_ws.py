#!/usr/bin/env python3
import os
import sys
import subprocess
import threading
import time
import http.server
import socketserver

# Beautiful premium dark-mode HTML Validator Page
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vocalis WebSocket Integration Validator</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Fira+Code:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #090c15;
            --card-bg: rgba(17, 24, 39, 0.7);
            --border-glow: rgba(139, 92, 246, 0.3);
            --primary-grad: linear-gradient(135deg, #7c3aed 0%, #3b82f6 100%);
            --accent-green: #10b981;
            --accent-blue: #3b82f6;
            --accent-yellow: #fbbf24;
            --accent-purple: #8b5cf6;
            --accent-red: #ef4444;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-dark);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            background-image: radial-gradient(circle at 10% 20%, rgba(124, 58, 237, 0.08) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(59, 130, 246, 0.08) 0%, transparent 40%);
            padding: 2rem;
        }

        .container {
            max-width: 1200px;
            width: 100%;
            margin: 0 auto;
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
            flex-grow: 1;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 1rem;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }

        h1 {
            font-size: 1.75rem;
            font-weight: 700;
            background: linear-gradient(to right, #c084fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -0.5px;
        }

        .connection-badge {
            font-size: 0.8rem;
            font-weight: 600;
            padding: 0.3rem 0.8rem;
            border-radius: 99px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 0.4rem;
            border: 1px solid transparent;
            transition: all 0.3s ease;
        }

        .connection-badge.connected {
            background: rgba(16, 185, 129, 0.1);
            border-color: var(--accent-green);
            color: #34d399;
        }

        .connection-badge.disconnected {
            background: rgba(239, 68, 68, 0.1);
            border-color: var(--accent-red);
            color: #f87171;
            animation: blink 1.5s infinite alternate;
        }

        @keyframes blink {
            from { opacity: 0.6; }
            to { opacity: 1; }
        }

        .grid {
            display: grid;
            grid-template-columns: 1fr 1.2fr;
            gap: 1.5rem;
            flex-grow: 1;
        }

        @media (max-width: 900px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }

        .panel {
            background: var(--card-bg);
            border: 1px solid var(--border-glow);
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            display: flex;
            flex-direction: column;
            gap: 1.2rem;
            backdrop-filter: blur(12px);
        }

        .panel-title {
            font-size: 1.1rem;
            font-weight: 600;
            color: #c084fc;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            padding-bottom: 0.5rem;
        }

        .state-card {
            padding: 1.5rem;
            border-radius: 8px;
            text-align: center;
            font-weight: 700;
            font-size: 2rem;
            letter-spacing: 1px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid rgba(255, 255, 255, 0.05);
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            box-shadow: inset 0 2px 10px rgba(0,0,0,0.5);
        }

        .state-card .sub-label {
            font-size: 0.75rem;
            font-weight: 500;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* Color States for Server */
        .state-idle { background: rgba(16, 185, 129, 0.1); border-color: var(--accent-green); color: #34d399; text-shadow: 0 0 10px rgba(16,185,129,0.3); }
        .state-speaking { background: rgba(59, 130, 246, 0.1); border-color: var(--accent-blue); color: #60a5fa; text-shadow: 0 0 10px rgba(59,130,246,0.3); }
        .state-listening { background: rgba(251, 191, 36, 0.1); border-color: var(--accent-yellow); color: #fbbf24; text-shadow: 0 0 10px rgba(251,191,36,0.3); animation: pulse 1.5s infinite alternate; }
        .state-processing { background: rgba(139, 92, 246, 0.1); border-color: var(--accent-purple); color: #c084fc; text-shadow: 0 0 10px rgba(139,92,246,0.3); }
        .state-challenging { background: rgba(239, 68, 68, 0.1); border-color: var(--accent-red); color: #f87171; text-shadow: 0 0 10px rgba(239,68,68,0.3); animation: pulse 1s infinite alternate; }

        @keyframes pulse {
            from { box-shadow: 0 0 5px rgba(251, 191, 36, 0.1); }
            to { box-shadow: 0 0 20px rgba(251, 191, 36, 0.4); }
        }

        .form-row {
            display: flex;
            flex-direction: column;
            gap: 0.4rem;
        }

        .form-row label {
            font-size: 0.75rem;
            font-weight: 600;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        input[type="text"], input[type="number"], select {
            background: rgba(10, 15, 30, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            color: var(--text-main);
            font-family: inherit;
            font-size: 0.9rem;
            padding: 0.6rem;
            outline: none;
            width: 100%;
            transition: all 0.2s ease;
        }

        input[type="text"]:focus, select:focus {
            border-color: #8b5cf6;
            box-shadow: 0 0 0 1px rgba(139, 92, 246, 0.4);
        }

        .form-checkbox-group {
            display: flex;
            gap: 1.5rem;
            margin-top: 0.2rem;
        }

        .checkbox-container {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.85rem;
            cursor: pointer;
            color: var(--text-main);
        }

        .checkbox-container input {
            cursor: pointer;
            accent-color: #8b5cf6;
            width: 15px;
            height: 15px;
        }

        .btn {
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 600;
            padding: 0.6rem 1.2rem;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            color: white;
            background: var(--primary-grad);
            box-shadow: 0 4px 12px rgba(124, 58, 237, 0.2);
            transition: all 0.2s ease;
            text-align: center;
        }

        .btn:hover {
            opacity: 0.95;
            box-shadow: 0 4px 16px rgba(124, 58, 237, 0.35);
            transform: translateY(-1px);
        }

        .btn-cancel {
            background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);
        }

        .btn-cancel:hover {
            box-shadow: 0 4px 16px rgba(239, 68, 68, 0.4);
        }

        /* Logs Console */
        .logs-panel {
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            gap: 0.8rem;
        }

        .logs-controls {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .filter-buttons {
            display: flex;
            gap: 0.4rem;
        }

        .btn-filter {
            font-family: inherit;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.25rem 0.6rem;
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 4px;
            color: var(--text-muted);
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-filter.active, .btn-filter:hover {
            background: rgba(139, 92, 246, 0.15);
            border-color: var(--accent-purple);
            color: #c084fc;
        }

        .btn-clear {
            font-family: inherit;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.25rem 0.6rem;
            background: transparent;
            border: 1px solid rgba(239, 68, 68, 0.3);
            border-radius: 4px;
            color: #f87171;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-clear:hover {
            background: rgba(239, 68, 68, 0.1);
        }

        .console {
            background: #04060b;
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 1rem;
            font-family: 'Fira Code', monospace;
            font-size: 0.8rem;
            flex-grow: 1;
            min-height: 400px;
            max-height: 600px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
            box-shadow: inset 0 2px 8px rgba(0,0,0,0.8);
        }

        .console-row {
            padding: 0.4rem 0.6rem;
            border-radius: 4px;
            background: rgba(255, 255, 255, 0.02);
            border-left: 3px solid transparent;
            line-height: 1.4;
            animation: fadeIn 0.2s ease-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .console-row .timestamp {
            color: #6b7280;
            font-size: 0.7rem;
            margin-right: 0.5rem;
        }

        .console-row .event-name {
            font-weight: 600;
            margin-right: 0.5rem;
            text-transform: uppercase;
            font-size: 0.75rem;
        }

        .console-row.state-change { border-color: var(--accent-blue); }
        .console-row.state-change .event-name { color: #60a5fa; }
        
        .console-row.wake { border-color: var(--accent-green); }
        .console-row.wake .event-name { color: #34d399; }
        
        .console-row.result { border-color: var(--accent-purple); }
        .console-row.result .event-name { color: #c084fc; }

        .console-row.cancellation { border-color: var(--accent-red); }
        .console-row.cancellation .event-name { color: #f87171; }

        .console-row.handshake { border-color: #6b7280; }
        .console-row.handshake .event-name { color: #9ca3af; }

        .json-payload {
            display: block;
            margin-top: 0.3rem;
            padding: 0.3rem;
            background: rgba(0,0,0,0.3);
            border-radius: 3px;
            color: #d1d5db;
            font-size: 0.75rem;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Vocalis WebSocket Event Validator</h1>
            <div id="connectionBadge" class="connection-badge disconnected">
                <span style="width: 8px; height: 8px; border-radius: 50%; background-color: currentColor;"></span>
                <span id="connectionText">Disconnected</span>
            </div>
        </header>

        <div class="grid">
            <!-- Left Panel: Controls and Triggers -->
            <div class="panel">
                <div class="panel-title">Engine Status</div>
                <div id="stateCard" class="state-card state-idle">
                    <span id="stateText">IDLE</span>
                    <span class="sub-label">Current State Machine State</span>
                </div>

                <div class="panel-title">Trigger TTS (Say)</div>
                 <div class="form-row">
                    <label for="sayText">Message to Speak</label>
                    <input type="text" id="sayText" value="Hola, probando la integración con Node Red.">
                </div>
                <div class="form-row">
                    <label for="sayPriority">Priority</label>
                    <input type="number" id="sayPriority" value="0" min="0" step="1" style="margin-top: 0.2rem;">
                </div>
                <button class="btn" onclick="triggerSay()">Execute /say Request</button>

                <div class="panel-title">Trigger Voice Capture (Ask)</div>
                <div class="form-row">
                    <label for="askPrompt">Prompt Text</label>
                    <input type="text" id="askPrompt" value="¿Qué comando desea ejecutar?">
                </div>
                <div class="form-row">
                    <label>Options</label>
                    <div class="form-checkbox-group">
                        <label class="checkbox-container">
                            <input type="checkbox" id="askBargeIn" checked> Barge-in (Interrupt)
                        </label>
                        <label class="checkbox-container">
                            <input type="checkbox" id="askSpeakerId"> Verify Speaker ID
                        </label>
                    </div>
                </div>
                <div class="form-row">
                    <label for="askOutputFormat">Output Format</label>
                    <select id="askOutputFormat" style="margin-top: 0.2rem;">
                        <option value="both" selected>Both (Text + Audio)</option>
                        <option value="text">Text (Transcription Only)</option>
                        <option value="audio">Audio (WAV Base64 Only)</option>
                    </select>
                </div>
                <div class="form-row">
                    <label for="askPriority">Priority</label>
                    <input type="number" id="askPriority" value="0" min="0" step="1" style="margin-top: 0.2rem;">
                </div>
                <button class="btn" onclick="triggerAsk()">Execute /ask Request</button>

                <div class="panel-title">Cancel Active Request</div>
                <div class="form-row">
                    <label for="cancelContextId">Context ID to Cancel</label>
                    <input type="text" id="cancelContextId" placeholder="e.g. wake_17196000">
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem;">
                    <button class="btn btn-cancel" onclick="sendCancelWS()">Cancel via WS</button>
                    <button class="btn btn-cancel" onclick="sendCancelHTTP()">Cancel via HTTP</button>
                </div>
            </div>

            <!-- Right Panel: Logs -->
            <div class="panel logs-panel">
                <div class="panel-title">Real-Time Event stream</div>
                <div class="logs-controls">
                    <div class="filter-buttons">
                        <button class="btn-filter active" onclick="setFilter('all')">All</button>
                        <button class="btn-filter" onclick="setFilter('state-change')">State Changes</button>
                        <button class="btn-filter" onclick="setFilter('wake')">Wakeword</button>
                        <button class="btn-filter" onclick="setFilter('result')">Results</button>
                    </div>
                    <button class="btn-clear" onclick="clearLogs()">Clear Console</button>
                </div>
                <div class="console" id="console">
                    <div class="console-row handshake">
                        <span class="timestamp">--:--:--</span>
                        <span class="event-name">SYSTEM</span>
                        <span>Waiting for WebSocket connection...</span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const wsUrl = "ws://localhost:8080/ws";
        let ws = null;
        let activeFilter = 'all';

        const connectionBadge = document.getElementById('connectionBadge');
        const connectionText = document.getElementById('connectionText');
        const stateCard = document.getElementById('stateCard');
        const stateText = document.getElementById('stateText');
        const consolePanel = document.getElementById('console');

        function logEvent(eventClass, eventName, message, jsonPayload = null) {
            const timeStr = new Date().toLocaleTimeString();
            const row = document.createElement('div');
            row.className = `console-row ${eventClass}`;
            row.dataset.type = eventClass;
            
            let jsonHtml = "";
            if (jsonPayload) {
                jsonHtml = `<code class="json-payload">${JSON.stringify(jsonPayload, null, 2)}</code>`;
            }

            row.innerHTML = `
                <span class="timestamp">${timeStr}</span>
                <span class="event-name">${eventName}</span>
                <span>${message}</span>
                ${jsonHtml}
            `;

            consolePanel.appendChild(row);
            consolePanel.scrollTop = consolePanel.scrollHeight;
            applyFilter();
        }

        function setFilter(filter) {
            activeFilter = filter;
            document.querySelectorAll('.btn-filter').forEach(btn => {
                btn.classList.toggle('active', btn.getAttribute('onclick').includes(filter));
            });
            applyFilter();
        }

        function applyFilter() {
            const rows = consolePanel.querySelectorAll('.console-row');
            rows.forEach(row => {
                if (activeFilter === 'all') {
                    row.style.display = 'block';
                } else {
                    row.style.display = row.classList.contains(activeFilter) ? 'block' : 'none';
                }
            });
        }

        function clearLogs() {
            consolePanel.innerHTML = '';
        }

        function updateStateCard(state) {
            stateText.textContent = state;
            stateCard.className = `state-card state-${state.toLowerCase()}`;
        }

        function connectWS() {
            connectionText.textContent = "Connecting...";
            connectionBadge.className = "connection-badge disconnected";

            ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                connectionText.textContent = "Connected";
                connectionBadge.className = "connection-badge connected";
                logEvent('handshake', 'WS OPEN', 'Connected to Vocalis Event WebSocket channel.');
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.event === "handshake") {
                        logEvent('handshake', 'HANDSHAKE', 'Server connected.', data);
                        updateStateCard(data.state);
                    } else if (data.event === "state_change") {
                        logEvent('state-change', 'STATE', `${data.old_state} ➔ ${data.new_state}`, data);
                        updateStateCard(data.new_state);
                    } else if (data.event === "wake_detected") {
                        logEvent('wake', 'WAKE', `Wake word heard! Model: ${data.model} (Score: ${data.score.toFixed(3)})`, data);
                    } else if (data.event === "ask_result") {
                        let audioHtml = "";
                        if (data.audio_wav_base64) {
                            audioHtml = `<br><audio controls src="data:audio/wav;base64,${data.audio_wav_base64}" style="margin-top: 0.5rem; height: 32px;"></audio>`;
                        }
                        logEvent('result', 'ASK RESULT', `Status: ${data.status} | Text: "${data.transcription || ''}"${audioHtml}`, data);
                    } else if (data.event === "cancellation_result") {
                        logEvent('cancellation', 'CANCEL RESULT', `Cancelled Context: ${data.context_id} | Success: ${data.success}`, data);
                    }
                } catch (e) {
                    console.error("Failed to parse event data:", e);
                }
            };

            ws.onclose = () => {
                connectionText.textContent = "Disconnected";
                connectionBadge.className = "connection-badge disconnected";
                logEvent('handshake', 'WS CLOSE', 'WebSocket closed. Reconnecting in 3 seconds...');
                setTimeout(connectWS, 3000);
            };

            ws.onerror = (err) => {
                console.error("WS error: ", err);
            };
        }

        async function triggerSay() {
            const text = document.getElementById('sayText').value.trim();
            const priority = parseInt(document.getElementById('sayPriority').value) || 0;
            const ctxId = `nr_say_${Math.floor(Math.random() * 100000)}`;
            if (!text) return alert("Please specify text to speak.");

            try {
                const res = await fetch("http://localhost:8080/say", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ context_id: ctxId, text: text, priority: priority })
                });
                const result = await res.json();
                console.log("/say triggered:", result);
            } catch (err) {
                alert("Failed to trigger /say API: " + err.message);
            }
        }

        async function triggerAsk() {
            const prompt = document.getElementById('askPrompt').value.trim();
            const bargeIn = document.getElementById('askBargeIn').checked;
            const speakerId = document.getElementById('askSpeakerId').checked;
            const outputFormat = document.getElementById('askOutputFormat').value;
            const priority = parseInt(document.getElementById('askPriority').value) || 0;
            const ctxId = `nr_ask_${Math.floor(Math.random() * 100000)}`;

            if (!prompt) return alert("Please specify prompt text.");

            try {
                const res = await fetch("http://localhost:8080/ask", {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        context_id: ctxId,
                        tts_text: prompt,
                        barge_in: bargeIn,
                        require_speaker_id: speakerId,
                        output_format: outputFormat,
                        vad_timeout_seconds: 10.0,
                        priority: priority
                    })
                });
                const result = await res.json();
                console.log("/ask triggered:", result);
            } catch (err) {
                alert("Failed to trigger /ask API: " + err.message);
            }
        }

        function sendCancelWS() {
            const ctxId = document.getElementById('cancelContextId').value.trim();
            if (!ctxId) return alert("Please specify a Context ID to cancel.");

            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                    command: "cancel",
                    context_id: ctxId
                }));
                logEvent('cancellation', 'WS SEND', `Sent cancellation request for Context ID: ${ctxId}`);
            } else {
                alert("WebSocket is not connected.");
            }
        }

        async function sendCancelHTTP() {
            const ctxId = document.getElementById('cancelContextId').value.trim();
            if (!ctxId) return alert("Please specify a Context ID to cancel.");

            try {
                const res = await fetch(`http://localhost:8080/queue/cancel/${ctxId}`, {
                    method: 'POST'
                });
                const result = await res.json();
                logEvent('cancellation', 'HTTP RESP', `Http Cancel Response: Success=${result.success}`, result);
            } catch (err) {
                alert("Failed to trigger cancellation via HTTP: " + err.message);
            }
        }

        connectWS();
    </script>
</body>
</html>
"""

class CustomHTTPHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        else:
            self.send_error(404, "File Not Found")

def run_http_server(port):
    handler = CustomHTTPHandler
    # Allow address reuse to prevent "Address already in use" errors during quick runs
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), handler) as httpd:
        print(f"[HTTP] Validator UI served successfully at http://localhost:{port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            print("[HTTP] Stopping validator UI server...")
            httpd.server_close()

def main():
    # 1. Determine local virtual environment python path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    
    venv_dir = os.path.join(project_root, ".venv")
    if sys.platform == "win32":
        python_exe = os.path.join(venv_dir, "Scripts", "python.exe")
    else:
        python_exe = os.path.join(venv_dir, "bin", "python")

    if not os.path.exists(python_exe):
        print(f"Warning: Virtual environment python not found at {python_exe}. Falling back to default python.")
        python_exe = sys.executable

    # 2. Spin up Validator Web UI Server in a separate thread
    validator_port = 8085
    http_thread = threading.Thread(target=run_http_server, args=(validator_port,), daemon=True)
    http_thread.start()

    # Give HTTP server a tiny moment to bind
    time.sleep(0.5)

    # 3. Spin up Vocalis Assistant Core Daemon
    print(f"[Vocalis] Launching daemon via: {python_exe} -m vocalis.main")
    print("=" * 60)
    
    # We run the process redirecting stdout/stderr to current terminal logs
    process = None
    try:
        process = subprocess.Popen(
            [python_exe, "-m", "vocalis.main"],
            cwd=project_root,
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        
        # Keep running until keyboard interrupt
        while True:
            # Check if subprocess exited early
            ret_code = process.poll()
            if ret_code is not None:
                print(f"[Vocalis] Daemon exited early with return code {ret_code}.")
                break
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n[Vocalis] Shutdown signal received.")
    finally:
        if process and process.poll() is None:
            print("[Vocalis] Stopping Vocalis Daemon subprocess...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[Vocalis] Process did not terminate. Killing...")
                process.kill()
            print("[Vocalis] Subprocess terminated.")
        print("Goodbye!")

if __name__ == "__main__":
    main()
