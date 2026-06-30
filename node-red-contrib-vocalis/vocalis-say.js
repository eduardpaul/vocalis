module.exports = function(RED) {
    function getValueFromPath(obj, path) {
        if (!path) return undefined;
        if (path.startsWith('msg.')) {
            path = path.slice(4);
        }
        const parts = path.split('.');
        let current = obj;
        for (const part of parts) {
            if (current === null || current === undefined) {
                return undefined;
            }
            current = current[part];
        }
        return current;
    }

    function interpolate(text, msg) {
        if (typeof text !== 'string') return '';
        return text.replace(/\{\{([^}]+)\}\}|\{([^}]+)\}/g, (match, p1, p2) => {
            const path = (p1 || p2).trim();
            const val = getValueFromPath(msg, path);
            return val !== undefined ? (typeof val === 'object' ? JSON.stringify(val) : String(val)) : match;
        });
    }

    function VocalisSayNode(config) {
        RED.nodes.createNode(this, config);
        this.server = RED.nodes.getNode(config.server);
        this.text = config.text;
        this.textType = config.textType || "str";
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

            let textToSay = "";
            if (node.text && node.text.trim() !== "") {
                try {
                    const rawVal = RED.util.evaluateNodeProperty(node.text, node.textType, node, msg);
                    if (typeof rawVal === 'string') {
                        textToSay = interpolate(rawVal, msg);
                    } else if (rawVal !== undefined && rawVal !== null) {
                        textToSay = typeof rawVal === 'object' ? JSON.stringify(rawVal) : String(rawVal);
                    }
                } catch (err) {
                    node.status({ fill: "red", shape: "ring", text: "error evaluating property" });
                    done(`Failed to evaluate text property: ${err.message}`);
                    return;
                }
            } else {
                textToSay = msg.payload;
            }

            if (!textToSay || typeof textToSay !== 'string') {
                node.status({ fill: "yellow", shape: "ring", text: "invalid payload" });
                done("Payload must be a string containing the text to speak.");
                return;
            }

            const contextId = msg.context_id || `nr_say_${Math.floor(Math.random() * 1000000)}`;

            node.status({ fill: "blue", shape: "dot", text: `saying: "${textToSay.substring(0, 15)}..."` });

            const payload = {
                context_id: contextId,
                text: textToSay,
                priority: msg.priority !== undefined ? parseInt(msg.priority) : node.priority
            };

            const url = `${node.server.baseUrl}/say`;

            const headers = { 'Content-Type': 'application/json' };
            if (node.server.apiKey) {
                headers['X-API-Key'] = node.server.apiKey;
            }

            try {
                const response = await fetch(url, {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify(payload)
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    node.status({ fill: "red", shape: "ring", text: "error" });
                    done(`Server error (${response.status}): ${errorText}`);
                    return;
                }

                const result = await response.json();
                if (result.status === "success") {
                    node.status({ fill: "green", shape: "dot", text: "finished" });
                    msg.payload = result;
                    send(msg);
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

    RED.nodes.registerType("vocalis-say", VocalisSayNode);
}
