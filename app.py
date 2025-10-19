from flask import Flask, request
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import random
import string
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'durak_secret_key_2025')

# CORS
CORS(app, resources={
    r"/*": {
        "origins": "*",
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type"]
    }
})

# Socket.IO с совместимыми настройками
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25,
    max_http_buffer_size=1000000,
    transports=['websocket', 'polling']
)

# Дані гри
game_rooms = {}

# Карти
SUITS = ['hearts', 'diamonds', 'clubs', 'spades']
VALUES = ['6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

def generate_room_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

def create_deck():
    deck = []
    for suit in SUITS:
        for value in VALUES:
            deck.append({'suit': suit, 'value': value})
    random.shuffle(deck)
    return deck

def card_value(card, trump_suit):
    value_order = {'6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    base_value = value_order[card['value']]
    if card['suit'] == trump_suit:
        return base_value + 100
    return base_value

def can_beat(attack_card, defense_card, trump_suit):
    if defense_card['suit'] == attack_card['suit']:
        return card_value(defense_card, trump_suit) > card_value(attack_card, trump_suit)
    elif defense_card['suit'] == trump_suit:
        return True
    return False

@app.route('/')
def index():
    return {
        'status': 'Дурак сервер працює!',
        'version': '2.0',
        'active_rooms': len(game_rooms)
    }

@app.route('/health')
def health():
    return {
        'status': 'ok',
        'rooms': len(game_rooms),
        'total_players': sum(len(room.get('players', [])) for room in game_rooms.values())
    }

@socketio.on('connect')
def handle_connect():
    print(f'✅ Клієнт підключився: {request.sid}')
    return True

@socketio.on('disconnect')
def handle_disconnect():
    print(f'❌ Клієнт відключився: {request.sid}')
    
    # Видалення гравця з кімнат
    for room_code, room_data in list(game_rooms.items()):
        players = room_data.get('players', [])
        player_found = None
        
        for player in players:
            if player['sid'] == request.sid:
                player_found = player
                players.remove(player)
                break
        
        if player_found:
            socketio.emit('player_left', {
                'player_name': player_found['name'],
                'players': [{'name': p['name'], 'card_count': len(p.get('hand', []))} for p in players]
            }, room=room_code)
            
            if len(players) == 0:
                del game_rooms[room_code]
                print(f'🗑️ Кімната {room_code} видалена (пуста)')

@socketio.on('create_room')
def handle_create_room(data):
    try:
        room_code = generate_room_code()
        player_name = data.get('player_name', 'Гравець')
        
        game_rooms[room_code] = {
            'host': request.sid,
            'players': [{
                'sid': request.sid,
                'name': player_name,
                'hand': [],
                'connected': True
            }],
            'game_started': False,
            'deck': [],
            'trump_suit': '',
            'table_cards': [],
            'current_turn': 0,
            'attacker_index': 0,
            'defender_index': 1
        }
        
        join_room(room_code)
        emit('room_created', {'room_code': room_code})
        print(f'🎮 Кімната створена: {room_code} | Хост: {player_name}')
        
    except Exception as e:
        print(f'Помилка створення кімнати: {e}')
        emit('error', {'message': 'Помилка створення кімнати'})

@socketio.on('join_room')
def handle_join_room(data):
    try:
        room_code = data.get('room_code', '').upper()
        player_name = data.get('player_name', 'Гравець')
        
        if room_code not in game_rooms:
            emit('error', {'message': 'Кімнату не знайдено'})
            return
        
        room = game_rooms[room_code]
        
        if len(room['players']) >= 5:
            emit('error', {'message': 'Кімната повна (максимум 5 гравців)'})
            return
        
        if room['game_started']:
            emit('error', {'message': 'Гра вже почалася'})
            return
        
        player = {
            'sid': request.sid,
            'name': player_name,
            'hand': [],
            'connected': True
        }
        
        room['players'].append(player)
        join_room(room_code)
        
        emit('room_joined', {
            'room_code': room_code,
            'players': [{'name': p['name'], 'card_count': 0} for p in room['players']]
        })
        
        socketio.emit('player_joined', {
            'player_name': player_name,
            'players': [{'name': p['name'], 'card_count': 0} for p in room['players']]
        }, room=room_code, skip_sid=request.sid)
        
        print(f'👤 {player_name} приєднався до {room_code}')
        
    except Exception as e:
        print(f'Помилка приєднання до кімнати: {e}')
        emit('error', {'message': 'Помилка приєднання'})

@socketio.on('leave_room')
def handle_leave_room(data):
    try:
        room_code = data.get('room_code')
        
        if room_code in game_rooms:
            room = game_rooms[room_code]
            player_name = None
            
            for player in room['players']:
                if player['sid'] == request.sid:
                    player_name = player['name']
                    room['players'].remove(player)
                    break
            
            leave_room(room_code)
            
            if player_name:
                socketio.emit('player_left', {
                    'player_name': player_name,
                    'players': [{'name': p['name'], 'card_count': len(p.get('hand', []))} for p in room['players']]
                }, room=room_code)
            
            if len(room['players']) == 0:
                del game_rooms[room_code]
                print(f'🗑️ Кімната {room_code} видалена')
                
    except Exception as e:
        print(f'Помилка виходу з кімнати: {e}')

@socketio.on('start_game')
def handle_start_game(data):
    try:
        room_code = data.get('room_code')
        
        if room_code not in game_rooms:
            emit('error', {'message': 'Кімнату не знайдено'})
            return
        
        room = game_rooms[room_code]
        
        if request.sid != room['host']:
            emit('error', {'message': 'Тільки хост може почати гру'})
            return
        
        if len(room['players']) < 2:
            emit('error', {'message': 'Потрібно мінімум 2 гравці'})
            return
        
        # Ініціалізація гри
        room['deck'] = create_deck()
        room['trump_suit'] = room['deck'][-1]['suit']
        room['game_started'] = True
        room['table_cards'] = []
        room['current_turn'] = 0
        room['attacker_index'] = 0
        room['defender_index'] = 1
        
        # Роздача карт
        for player in room['players']:
            player['hand'] = []
            for _ in range(6):
                if room['deck']:
                    player['hand'].append(room['deck'].pop(0))
        
        # Відправка даних кожному гравцю
        for player in room['players']:
            socketio.emit('game_started', {
                'hand': player['hand'],
                'trump_suit': room['trump_suit'],
                'deck_count': len(room['deck']),
                'current_turn': room['players'][room['current_turn']]['name'],
                'players': [{'name': p['name'], 'card_count': len(p['hand'])} for p in room['players']]
            }, to=player['sid'])
        
        print(f'🎲 Гра почалася в кімнаті {room_code}')
        
    except Exception as e:
        print(f'Помилка старту гри: {e}')
        emit('error', {'message': 'Помилка запуску гри'})

@socketio.on('play_card')
def handle_play_card(data):
    try:
        room_code = data.get('room_code')
        action = data.get('action')
        cards = data.get('cards', [])
        
        if room_code not in game_rooms:
            return
        
        room = game_rooms[room_code]
        player_index = None
        
        for i, player in enumerate(room['players']):
            if player['sid'] == request.sid:
                player_index = i
                break
        
        if player_index is None:
            return
        
        current_player = room['players'][player_index]
        
        # Обробка дій
        if action == 'throw':
            for card in cards:
                for hand_card in current_player['hand']:
                    if hand_card['value'] == card['value'] and hand_card['suit'] == card['suit']:
                        current_player['hand'].remove(hand_card)
                        room['table_cards'].append({'attack': card, 'defense': None})
                        break
            
            socketio.emit('card_played', {
                'player': current_player['name'],
                'action': 'throw'
            }, room=room_code)
        
        elif action == 'take':
            # Гравець бере всі карти зі столу
            for pair in room['table_cards']:
                current_player['hand'].append(pair['attack'])
                if pair['defense']:
                    current_player['hand'].append(pair['defense'])
            
            room['table_cards'] = []
            
            socketio.emit('chat_message', {
                'player': 'Система',
                'message': f'{current_player["name"]} взяв карти'
            }, room=room_code)
        
        elif action == 'pass':
            # Перехід ходу
            room['table_cards'] = []
            room['current_turn'] = (room['current_turn'] + 1) % len(room['players'])
        
        # Дороздача карт
        for player in room['players']:
            while len(player['hand']) < 6 and room['deck']:
                player['hand'].append(room['deck'].pop(0))
        
        # Перевірка закінчення гри
        winner = None
        for player in room['players']:
            if len(player['hand']) == 0 and len(room['deck']) == 0:
                winner = player['name']
                break
        
        if winner:
            socketio.emit('game_over', {'winner': winner}, room=room_code)
            room['game_started'] = False
            return
        
        # Відправка оновленого стану
        for player in room['players']:
            socketio.emit('game_state_update', {
                'hand': player['hand'],
                'table_cards': room['table_cards'],
                'deck_count': len(room['deck']),
                'current_turn': room['players'][room['current_turn']]['name'],
                'players': [{'name': p['name'], 'card_count': len(p['hand'])} for p in room['players']]
            }, to=player['sid'])
            
    except Exception as e:
        print(f'Помилка гри: {e}')

@socketio.on('chat_message')
def handle_chat_message(data):
    try:
        room_code = data.get('room_code')
        message = data.get('message', '')
        
        if room_code in game_rooms:
            player_name = None
            for player in game_rooms[room_code]['players']:
                if player['sid'] == request.sid:
                    player_name = player['name']
                    break
            
            if player_name:
                socketio.emit('chat_message', {
                    'player': player_name,
                    'message': message
                }, room=room_code)
                
    except Exception as e:
        print(f'Помилка чату: {e}')

@socketio.on('random_event')
def handle_random_event(data):
    try:
        room_code = data.get('room_code')
        event_type = data.get('event')
        
        if room_code not in game_rooms:
            return
        
        room = game_rooms[room_code]
        
        if event_type == 'trump_change':
            room['trump_suit'] = random.choice(SUITS)
            socketio.emit('special_event', {
                'event': 'trump_change',
                'message': f'Новий козир: {room["trump_suit"]}'
            }, room=room_code)
        
        elif event_type == 'drunk_dealer':
            for player in room['players']:
                if room['deck']:
                    player['hand'].append(room['deck'].pop(0))
            
            socketio.emit('special_event', {
                'event': 'drunk_dealer',
                'message': 'П\'яний дилер роздав карти!'
            }, room=room_code)
        
        elif event_type == 'matrix_error':
            for player in room['players']:
                random.shuffle(player['hand'])
            
            socketio.emit('special_event', {
                'event': 'matrix_error',
                'message': 'Карти перемішано!'
            }, room=room_code)
        
        elif event_type == 'light_flicker':
            if room['players']:
                random_player = random.choice(room['players'])
                if random_player['hand']:
                    random_player['hand'].pop(random.randint(0, len(random_player['hand']) - 1))
            
            socketio.emit('special_event', {
                'event': 'light_flicker',
                'message': 'Хтось втратив карту!'
            }, room=room_code)
            
    except Exception as e:
        print(f'Помилка спецподії: {e}')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'🎴 Дурак сервер запущено на порті {port}')
    print(f'📊 Режим: {"Production" if not app.debug else "Development"}')
    socketio.run(
        app,
        host='0.0.0.0',
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )
