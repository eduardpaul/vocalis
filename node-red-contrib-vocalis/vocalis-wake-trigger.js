module.exports = function(RED) {
    function VocalisWakeTriggerNode(config) {
        RED.nodes.createNode(this, config);
        this.server = RED.nodes.getNode(config.server);

        const node = this;

        if (node.server) {
            node.status({ fill: "blue", shape: "ring", text: "connecting..." });

            const eventHandler = (message) => {
                if (message.event === "wake_detected") {
                    node.status({ fill: "green", shape: "dot", text: "wake word heard" });
                    
                    const msg = {
                        topic: "vocalis/wake",
                        payload: {
                            event: "wake_detected",
                            model: message.model,
                            score: message.score,
                            timestamp: message.timestamp
                        }
                    };
                    node.send([msg, null]);
                    
                    setTimeout(() => {
                        node.status({ fill: "green", shape: "ring", text: "standby" });
                    }, 3000);
                } else if (message.event === "ask_result") {
                    node.status({ fill: "green", shape: "dot", text: "command captured" });
                    
                    const msg = {
                        topic: "vocalis/command",
                        status: message.status,
                        transcription: message.transcription,
                        speaker: message.speaker,
                        context_id: message.context_id,
                        payload: {
                            event: "command_received",
                            status: message.status,
                            transcription: message.transcription,
                            speaker: message.speaker,
                            context_id: message.context_id
                        }
                    };
                    node.send([null, msg]);
                    
                    setTimeout(() => {
                        node.status({ fill: "green", shape: "ring", text: "standby" });
                    }, 3000);
                } else if (message.event === "state_change") {
                    const state = message.new_state;
                    if (state === "IDLE") {
                        node.status({ fill: "green", shape: "ring", text: "standby" });
                    } else if (state === "SPEAKING") {
                        node.status({ fill: "blue", shape: "dot", text: "speaking" });
                    } else if (state === "LISTENING") {
                        node.status({ fill: "yellow", shape: "dot", text: "listening" });
                    } else if (state === "PROCESSING") {
                        node.status({ fill: "purple", shape: "dot", text: "processing" });
                    } else if (state === "CHALLENGING") {
                        node.status({ fill: "red", shape: "dot", text: "verifying..." });
                    }
                }
            };

            node.server.on('vocalis-event', eventHandler);

            node.status({ fill: "green", shape: "ring", text: "standby" });

            node.on('close', function() {
                if (node.server) {
                    node.server.removeListener('vocalis-event', eventHandler);
                }
            });
        } else {
            node.status({ fill: "red", shape: "ring", text: "missing config" });
        }
    }

    RED.nodes.registerType("vocalis-wake-trigger", VocalisWakeTriggerNode);
}
