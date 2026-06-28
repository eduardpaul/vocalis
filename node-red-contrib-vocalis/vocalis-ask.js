module.exports = function(RED) {
    function VocalisAskNode(config) {
        RED.nodes.createNode(this, config);
        this.server = RED.nodes.getNode(config.server);
        this.promptText = config.promptText;
        this.bargeIn = config.bargeIn !== false;
        this.requireSpeakerId = !!config.requireSpeakerId;
        this.outputFormat = config.outputFormat || "both";
        this.vadTimeout = parseFloat(config.vadTimeout) || 10.0;
        this.priority = parseInt(config.priority) || 0;

        const node = this;

        node.on('input', async function(msg, send, done) {
            send = send || function() { node.send.apply(node, arguments); };
            done = done || function(err) { if (err) { node.error(err, msg); } };

            if (!node.server) {
                node.status({ fill: "red", shape: "ring", text: "missing config" });
                done("Missing Vocalis configuration");
                return;
            }

            const prompt = msg.payload || node.promptText;
            if (!prompt || typeof prompt !== 'string') {
                node.status({ fill: "yellow", shape: "ring", text: "invalid payload" });
                done("Payload must be a string containing the TTS prompt text.");
                return;
            }

            const contextId = msg.context_id || `nr_ask_${Math.floor(Math.random() * 1000000)}`;

            node.status({ fill: "blue", shape: "dot", text: `asking: "${prompt.substring(0, 15)}..."` });

            const payload = {
                context_id: contextId,
                tts_text: prompt,
                barge_in: node.bargeIn,
                require_speaker_id: node.requireSpeakerId,
                output_format: node.outputFormat,
                vad_timeout_seconds: node.vadTimeout,
                priority: msg.priority !== undefined ? parseInt(msg.priority) : node.priority
            };

            const url = `${node.server.baseUrl}/ask`;

            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    node.status({ fill: "red", shape: "ring", text: "error" });
                    done(`Server error (${response.status}): ${errorText}`);
                    return;
                }

                const result = await response.json();
                
                msg.status = result.status;
                msg.transcription = result.transcription;
                msg.speaker = result.speaker;
                msg.audio_wav_base64 = result.audio_wav_base64;
                msg.payload = result;

                if (result.status === "success") {
                    node.status({ fill: "green", shape: "dot", text: `success: "${result.transcription || ''}"` });
                    send([msg, null]);
                    done();
                } else if (result.status === "silence_timeout") {
                    node.status({ fill: "yellow", shape: "ring", text: "silence timeout" });
                    send([null, msg]);
                    done();
                } else if (result.status === "verification_failed") {
                    node.status({ fill: "red", shape: "ring", text: "auth failed" });
                    send([null, msg]);
                    done();
                } else {
                    node.status({ fill: "red", shape: "ring", text: result.status });
                    done(`Vocalis engine reported failure: ${result.error_message}`);
                }
            } catch (err) {
                node.status({ fill: "red", shape: "ring", text: "connection error" });
                done(`HTTP request failed: ${err.message}`);
            }
        });
    }

    RED.nodes.registerType("vocalis-ask", VocalisAskNode);
}
