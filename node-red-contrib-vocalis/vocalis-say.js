module.exports = function(RED) {
    function VocalisSayNode(config) {
        RED.nodes.createNode(this, config);
        this.server = RED.nodes.getNode(config.server);
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

            const textToSay = msg.payload || node.text;
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
