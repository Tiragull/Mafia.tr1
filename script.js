function initWebSocket(roleType, name = "") {
    // Если сокет уже был открыт — закрываем его перед созданием нового
    if (ws) {
        ws.close();
    }

    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log("Успешное WebSocket подключение как " + roleType);
        if (roleType === "leader") {
            ws.send(jsonMessage("init_leader"));
        } else {
            ws.send(jsonMessage("join_player", { name: name }));
        }
    };

    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        console.log("Получено сообщение от сервера:", msg);

        if (msg.type === "update_players") {
            updatePlayersUI(msg.players);
        }

        if (msg.type === "your_role") {
            myRole = msg.role;
            showWheelScreen();
        }
    };

    ws.onerror = (error) => {
        console.error("Ошибка WebSocket:", error);
    };

    ws.onclose = () => {
        console.log("WebSocket соединение закрыто");
    };
}