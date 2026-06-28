module.exports = function(RED) {
    const WebSocket = require('ws');

    function VocalisConfigNode(n) {
        RED.nodes.createNode(this, n);
        this.host = n.host || "localhost";
        this.port = n.port || "8080";
        this.ssl = n.ssl || false;

        const node = this;

        // Determine protocols
        const wsProto = node.ssl ? "wss" : "ws";
        const httpProto = node.ssl ? "https" : "http";

        node.wsUrl = `${wsProto}://${node.host}:${node.port}/ws`;
        node.baseUrl = `${httpProto}://${node.host}:${node.port}`;

        node.ws = null;
        node.closing = false;

        function connectWS() {
            if (node.closing) return;
            node.log(`Connecting to Vocalis WebSocket: ${node.wsUrl}`);
            node.ws = new WebSocket(node.wsUrl);

            node.ws.on('open', () => {
                node.log("Connected to Vocalis WebSocket server.");
            });

            node.ws.on('message', (data) => {
                try {
                    const message = JSON.parse(data.toString());
                    node.emit('vocalis-event', message);
                } catch (e) {
                    node.error("Failed to parse Vocalis WebSocket message: " + e.message);
                }
            });

            node.ws.on('close', () => {
                node.ws = null;
                if (!node.closing) {
                    node.warn("Vocalis WebSocket connection closed. Reconnecting in 5 seconds...");
                    setTimeout(connectWS, 5000);
                }
            });

            node.ws.on('error', (err) => {
                node.error("Vocalis WebSocket error: " + err.message);
            });
        }

        connectWS();

        // Helper to send messages over WebSocket (e.g. for cancellation)
        node.sendWS = function(payload) {
            if (node.ws && node.ws.readyState === WebSocket.OPEN) {
                node.ws.send(JSON.stringify(payload));
                return true;
            }
            return false;
        };

        node.on('close', function(done) {
            node.closing = true;
            if (node.ws) {
                node.ws.close();
            }
            done();
        });
    }

    RED.nodes.registerType("vocalis-config", VocalisConfigNode);
}
