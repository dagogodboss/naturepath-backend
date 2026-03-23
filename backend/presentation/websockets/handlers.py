"""
WebSocket Handler for Real-time Availability Updates
"""
import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates"""
    
    def __init__(self):
        # Map of practitioner_id:date -> set of connections
        self.availability_connections: Dict[str, Set[WebSocket]] = {}
        # Map of user_id -> connection
        self.user_connections: Dict[str, WebSocket] = {}
    
    async def connect_availability(
        self, 
        websocket: WebSocket, 
        practitioner_id: str, 
        date: str
    ):
        """Connect to availability updates for a specific practitioner and date"""
        await websocket.accept()
        key = f"{practitioner_id}:{date}"
        
        if key not in self.availability_connections:
            self.availability_connections[key] = set()
        
        self.availability_connections[key].add(websocket)
        logger.info(f"WebSocket connected for availability: {key}")
    
    async def disconnect_availability(
        self, 
        websocket: WebSocket, 
        practitioner_id: str, 
        date: str
    ):
        """Disconnect from availability updates"""
        key = f"{practitioner_id}:{date}"
        if key in self.availability_connections:
            self.availability_connections[key].discard(websocket)
            if not self.availability_connections[key]:
                del self.availability_connections[key]
        logger.info(f"WebSocket disconnected for availability: {key}")
    
    async def connect_user(self, websocket: WebSocket, user_id: str):
        """Connect user for personal notifications"""
        await websocket.accept()
        self.user_connections[user_id] = websocket
        logger.info(f"WebSocket connected for user: {user_id}")
    
    async def disconnect_user(self, user_id: str):
        """Disconnect user"""
        if user_id in self.user_connections:
            del self.user_connections[user_id]
        logger.info(f"WebSocket disconnected for user: {user_id}")
    
    async def broadcast_availability_update(
        self, 
        practitioner_id: str, 
        date: str, 
        slots: list
    ):
        """Broadcast availability update to all connected clients"""
        key = f"{practitioner_id}:{date}"
        if key in self.availability_connections:
            message = json.dumps({
                "type": "availability_update",
                "practitioner_id": practitioner_id,
                "date": date,
                "slots": slots,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            disconnected = set()
            for websocket in self.availability_connections[key]:
                try:
                    await websocket.send_text(message)
                except Exception as e:
                    logger.warning(f"Failed to send to websocket: {e}")
                    disconnected.add(websocket)
            
            # Clean up disconnected
            for ws in disconnected:
                self.availability_connections[key].discard(ws)
    
    async def send_user_notification(
        self, 
        user_id: str, 
        notification_type: str, 
        data: dict
    ):
        """Send notification to a specific user"""
        if user_id in self.user_connections:
            message = json.dumps({
                "type": notification_type,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            try:
                await self.user_connections[user_id].send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send notification to user {user_id}: {e}")
                await self.disconnect_user(user_id)
    
    async def broadcast_slot_locked(
        self, 
        practitioner_id: str, 
        date: str, 
        slot_id: str
    ):
        """Broadcast when a slot gets locked"""
        key = f"{practitioner_id}:{date}"
        if key in self.availability_connections:
            message = json.dumps({
                "type": "slot_locked",
                "practitioner_id": practitioner_id,
                "date": date,
                "slot_id": slot_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            for websocket in self.availability_connections[key].copy():
                try:
                    await websocket.send_text(message)
                except Exception:
                    self.availability_connections[key].discard(websocket)
    
    async def broadcast_slot_released(
        self, 
        practitioner_id: str, 
        date: str, 
        slot_id: str
    ):
        """Broadcast when a slot gets released"""
        key = f"{practitioner_id}:{date}"
        if key in self.availability_connections:
            message = json.dumps({
                "type": "slot_released",
                "practitioner_id": practitioner_id,
                "date": date,
                "slot_id": slot_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            
            for websocket in self.availability_connections[key].copy():
                try:
                    await websocket.send_text(message)
                except Exception:
                    self.availability_connections[key].discard(websocket)


# Global connection manager
manager = ConnectionManager()


async def availability_websocket_handler(
    websocket: WebSocket,
    practitioner_id: str,
    date: str
):
    """WebSocket endpoint for real-time availability updates"""
    await manager.connect_availability(websocket, practitioner_id, date)
    
    try:
        while True:
            # Keep connection alive and handle messages
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            
    except WebSocketDisconnect:
        await manager.disconnect_availability(websocket, practitioner_id, date)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect_availability(websocket, practitioner_id, date)


async def user_notification_websocket_handler(
    websocket: WebSocket,
    user_id: str
):
    """WebSocket endpoint for user notifications"""
    await manager.connect_user(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
            
    except WebSocketDisconnect:
        await manager.disconnect_user(user_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await manager.disconnect_user(user_id)


def get_connection_manager() -> ConnectionManager:
    """Get the global connection manager"""
    return manager
