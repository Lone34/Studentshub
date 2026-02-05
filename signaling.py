"""
WebRTC Signaling Server using Flask-SocketIO
Handles real-time peer connection establishment for video tutoring sessions
"""
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask import request

# Initialize SocketIO (will be attached to app in app.py)
socketio = SocketIO(cors_allowed_origins="*")

# Store connected users per room
room_users = {}

def init_socketio(app):
    """Initialize SocketIO with the Flask app"""
    socketio.init_app(app, async_mode='eventlet')
    return socketio


# ============================================
# SOCKET EVENT HANDLERS
# ============================================

@socketio.on('connect')
def handle_connect():
    """Handle new connection"""
    print(f"[Socket] Client connected: {request.sid}")
    emit('connected', {'sid': request.sid})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle disconnection"""
    print(f"[Socket] Client disconnected: {request.sid}")
    
    # Find and clean up rooms this user was in
    for room_id, users in list(room_users.items()):
        if request.sid in users:
            users.remove(request.sid)
            # Notify others in room that user left
            emit('user_left', {'sid': request.sid}, room=room_id)
            
            if len(users) == 0:
                del room_users[room_id]


@socketio.on('join_room')
def handle_join_room(data):
    """Join a video room"""
    room_id = data.get('room_id')
    user_type = data.get('user_type', 'unknown')  # 'student' or 'tutor'
    user_name = data.get('user_name', 'Anonymous')
    
    if not room_id:
        emit('error', {'message': 'Room ID required'})
        return
    
    # Join the room
    join_room(room_id)
    
    # Track user in room
    if room_id not in room_users:
        room_users[room_id] = []
    
    room_users[room_id].append(request.sid)
    
    print(f"[Socket] {user_name} ({user_type}) joined room {room_id}")
    
    # Notify user they joined successfully
    emit('room_joined', {
        'room_id': room_id,
        'users_in_room': len(room_users[room_id])
    })
    
    # Notify others in room that someone joined
    emit('user_joined', {
        'sid': request.sid,
        'user_type': user_type,
        'user_name': user_name
    }, room=room_id, include_self=False)


@socketio.on('leave_room')
def handle_leave_room(data):
    """Leave a video room"""
    room_id = data.get('room_id')
    
    if room_id:
        leave_room(room_id)
        
        if room_id in room_users and request.sid in room_users[room_id]:
            room_users[room_id].remove(request.sid)
        
        emit('user_left', {'sid': request.sid}, room=room_id)
        print(f"[Socket] Client {request.sid} left room {room_id}")


# ============================================
# WEBRTC SIGNALING
# ============================================

@socketio.on('offer')
def handle_offer(data):
    """Relay WebRTC offer to other peer"""
    room_id = data.get('room_id')
    offer = data.get('offer')
    
    if room_id and offer:
        emit('offer', {
            'offer': offer,
            'from': request.sid
        }, room=room_id, include_self=False)
        print(f"[Socket] Offer relayed in room {room_id}")


@socketio.on('answer')
def handle_answer(data):
    """Relay WebRTC answer to other peer"""
    room_id = data.get('room_id')
    answer = data.get('answer')
    
    if room_id and answer:
        emit('answer', {
            'answer': answer,
            'from': request.sid
        }, room=room_id, include_self=False)
        print(f"[Socket] Answer relayed in room {room_id}")


@socketio.on('ice_candidate')
def handle_ice_candidate(data):
    """Relay ICE candidate to other peer"""
    room_id = data.get('room_id')
    candidate = data.get('candidate')
    
    if room_id and candidate:
        emit('ice_candidate', {
            'candidate': candidate,
            'from': request.sid
        }, room=room_id, include_self=False)


# ============================================
# CHAT MESSAGES
# ============================================

@socketio.on('chat_message')
def handle_chat_message(data):
    """Relay chat message to room"""
    room_id = data.get('room_id')
    message = data.get('message')
    sender_name = data.get('sender_name', 'Anonymous')
    
    if room_id and message:
        emit('chat_message', {
            'message': message,
            'sender_name': sender_name,
            'from': request.sid
        }, room=room_id)
        print(f"[Socket] Chat message in room {room_id}: {message[:50]}...")


# ============================================
# SESSION CONTROL
# ============================================

@socketio.on('session_start')
def handle_session_start(data):
    """Notify room that session has started"""
    room_id = data.get('room_id')
    
    if room_id:
        emit('session_started', {
            'started_by': request.sid
        }, room=room_id)
        print(f"[Socket] Session started in room {room_id}")


@socketio.on('session_end')
def handle_session_end(data):
    """Notify room that session has ended"""
    room_id = data.get('room_id')
    
    if room_id:
        emit('session_ended', {
            'ended_by': request.sid
        }, room=room_id)
        print(f"[Socket] Session ended in room {room_id}")
