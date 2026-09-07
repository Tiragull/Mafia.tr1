import json
import random
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Глобальное состояние нашей единственной комнаты (для простоты пока сделаем одну)
GAME_ROOM = {
    "leader": None,        # Объект WebSocket ведущего
    "players": {},         # {websocket: {"name": "Паша", "role": None}}
    "roles_pool": ["Мафия", "Мафия", "Шериф", "Доктор", "Мирный", "Мирный", "Мирный"],
    "started": False
}

# Функция для рассылки обновления списка игроков Ведущему и всем участникам
async def broadcast_player_list():
    player_names = [p_info["name"] for p_info in GAME_ROOM["players"].values()]
    
    # Подготавливаем сообщение для ведущего (он видит и имена, и роли, если игра началась)
    leader_data = {
        "type": "update_players",
        "players": [
            {"name": p_info["name"], "role": p_info["role"]} 
            for p_info in GAME_ROOM["players"].values()
        ]
    }
    
    # Сообщение для обычных игроков (они видят просто список тех, кто в комнате)
    player_data = {
        "type": "update_players",
        "players": player_names
    }
    
    # Отправляем ведущему
    if GAME_ROOM["leader"]:
        await GAME_ROOM["leader"].send_text(json.dumps(leader_data))
        
    # Отправляем всем игрокам
    for ws in GAME_ROOM["players"].keys():
        await ws.send_text(json.dumps(player_data))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    current_role_in_room = None # 'leader' или 'player'
    
    try:
        while True:
            # Ждем текстовое сообщение от клиента (в формате JSON)
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 1. Сценарий: Подключается Ведущий
            if message["action"] == "init_leader":
                GAME_ROOM["leader"] = websocket
                current_role_in_room = "leader"
                print("Ведущий подключился к комнате!")
                await broadcast_player_list()
                
            # 2. Сценарий: Подключается Игрок
            elif message["action"] == "join_player":
                player_name = message["name"]
                GAME_ROOM["players"][websocket] = {"name": player_name, "role": None}
                current_role_in_room = "player"
                print(f"Игрок {player_name} вошел в игру!")
                await broadcast_player_list()
                
            # 3. Сценарий: Ведущий нажимает кнопку "Раздать роли"
            elif message["action"] == "start_distribution" and current_role_in_room == "leader":
                if not GAME_ROOM["players"]:
                    print("Ошибка: Нет подключенных игроков!")
                    continue
                
                # Получаем кастомный список ролей от Ведущего
                chosen_roles = message.get("roles", [])
                
                # Сколько реальных игроков сейчас в комнате
                num_players = len(GAME_ROOM["players"])
                
                # Если Ведущий вообще забыл выбрать карты, создаем базовый набор
                if not chosen_roles:
                    chosen_roles = ["Мафия", "Шериф", "Доктор", "Мирный", "Мирный"]
                
                # ПЕРЕМЕШИВАЕМ И КОРРЕКТИРУЕМ СПИСОК ПОД КОЛИЧЕСТВО ИГРОКОВ:
                random.shuffle(chosen_roles)
                
                # Если карт набрали меньше, чем игроков — докидываем Мирных жителей
                while len(chosen_roles) < num_players:
                    chosen_roles.append("Мирный")
                
                # Если карт набрали больше, чем игроков — просто отрезаем лишние хвосты
                chosen_roles = chosen_roles[:num_players]
                
                # Еще раз перемешиваем финальный точный пул
                random.shuffle(chosen_roles)
                GAME_ROOM["roles_pool"] = chosen_roles.copy()
                
                # Раздаем роли каждому подключенному игроку
                for i, ws in enumerate(GAME_ROOM["players"].keys()):
                    role = chosen_roles[i]
                    GAME_ROOM["players"][ws]["role"] = role
                    
                    # Мгновенно отправляем игроку ЕГО роль и ВЕСЬ пул карт раунда
                    await ws.send_text(json.dumps({
                        "type": "your_role",
                        "role": role,
                        "all_roles": chosen_roles
                    }))
                
                GAME_ROOM["started"] = True
                print(f"Роли успешно распределены под {num_players} игроков! Пул: {chosen_roles}")
                await broadcast_player_list()
            
            elif message["action"] == "reset_game" and current_role_in_room == "leader":
                GAME_ROOM["started"] = False
                
                # Обнуляем роли у всех игроков в памяти сервера
                for ws in GAME_ROOM["players"].keys():
                    GAME_ROOM["players"][ws]["role"] = None
                    
                    # Отправляем каждому игроку команду вернуться в лобби ожидания
                    await ws.send_text(json.dumps({
                        "type": "game_reseted"
                    }))
                
                print("Игра сброшена Ведущим. Все игроки вернулись в лобби.")
                # Обновляем экран Ведущего, чтобы у него тоже стёрлись старые роли в списке
                await broadcast_player_list()
                
                # Получаем кастомный список ролей, который Ведущий набрал на экране
                chosen_roles = message.get("roles", [])
                
                if not chosen_roles:
                    print("Ошибка: Ведущий не выбрал ни одной роли!")
                    continue
                
                # Перемешиваем присланные роли
                random.shuffle(chosen_roles)
                
                # Сохраняем текущий активный пул ролей игры в комнату (чтобы игроки могли построить колесо)
                GAME_ROOM["roles_pool"] = chosen_roles.copy()
                
                # Раздаем роли каждому подключенному игроку
                for i, ws in enumerate(GAME_ROOM["players"].keys()):
                    # Если ролей не хватает на всех зашедших, выдаем "Мирный"
                    role = chosen_roles[i] if i < len(chosen_roles) else "Мирный"
                    GAME_ROOM["players"][ws]["role"] = role
                    
                    # Отправляем игроку его личную роль И весь пул ролей для отрисовки секторов колеса
                    await ws.send_text(json.dumps({
                        "type": "your_role",
                        "role": role,
                        "all_roles": chosen_roles # Передаем весь список для колеса!
                    }))
                
                GAME_ROOM["started"] = True
                print(f"Роли успешно распределены! Текущий пул: {chosen_roles}")
                await broadcast_player_list()
                
                # Перемешиваем роли
                shuffled_roles = GAME_ROOM["roles_pool"].copy()
                random.shuffle(shuffled_roles)
                
                # Раздаем роли каждому подключенному websocket-игроку
                for i, ws in enumerate(GAME_ROOM["players"].keys()):
                    # Если игроков меньше, чем ролей в пуле, берем по индексу. 
                    # Если больше — выдаем "Мирный" (защита от нехватки)
                    role = shuffled_roles[i] if i < len(shuffled_roles) else "Мирный"
                    GAME_ROOM["players"][ws]["role"] = role
                    
                    # Мгновенно отправляем игроку на телефон ЕГО ЛИЧНУЮ роль
                    await ws.send_text(json.dumps({
                        "type": "your_role",
                        "role": role
                    }))
                
                GAME_ROOM["started"] = True
                print("Роли успешно распределены сервером!")
                # Обновляем экран Ведущего, чтобы он увидел, кому какая роль досталась
                await broadcast_player_list()

    except WebSocketDisconnect:
        # Если кто-то закрыл вкладку или пропал интернет — удаляем его из памяти
        if current_role_in_room == "leader":
            GAME_ROOM["leader"] = None
            print("Ведущий отключился.")
        elif current_role_in_room == "player" and websocket in GAME_ROOM["players"]:
            name = GAME_ROOM["players"][websocket]["name"]
            del GAME_ROOM["players"][websocket]
            print(f"Игрок {name} покинул комнату.")
            await broadcast_player_list()

# Точка входа для отдачи интерфейса (настроим на следующем шаге)
@app.get("/")
async def get():
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())