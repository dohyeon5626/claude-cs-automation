import asyncio
import json
import logging
from typing import Dict

import websockets
from websockets.server import WebSocketServerProtocol

from claude_handler import ClaudeHandler, UserSession
from config import AppConfig, ServiceConfig
from db_handler import DatabaseHandler

logger = logging.getLogger(__name__)


def _send(ws: WebSocketServerProtocol, data: dict) -> asyncio.coroutines:
    return ws.send(json.dumps(data, ensure_ascii=False))


class CSWebSocketServer:
    def __init__(self, config: AppConfig, db: DatabaseHandler, claude: ClaudeHandler):
        self._config = config
        self._db = db
        self._claude = claude
        self._sessions: Dict[WebSocketServerProtocol, UserSession] = {}
        self._service_map: Dict[str, ServiceConfig] = {
            s.id: s for s in config.services
        }

    async def handler(self, ws: WebSocketServerProtocol):
        client_addr = ws.remote_address
        logger.info(f"Client connected: {client_addr}")

        session = UserSession(user_id="")
        self._sessions[ws] = session

        try:
            await _send(ws, {"type": "auth_required", "message": "사용자 인증이 필요합니다."})
            await self._message_loop(ws, session)
        except websockets.exceptions.ConnectionClosedOK:
            logger.info(f"Client disconnected normally: {client_addr}")
        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning(f"Client connection closed with error: {client_addr} - {e}")
        except Exception as e:
            logger.error(f"Unhandled error for {client_addr}: {e}", exc_info=True)
        finally:
            self._sessions.pop(ws, None)
            logger.info(f"Session cleaned up: {client_addr}")

    async def _message_loop(self, ws: WebSocketServerProtocol, session: UserSession):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await _send(ws, {"type": "error", "message": "잘못된 메시지 형식입니다."})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "auth":
                await self._handle_auth(ws, session, msg)
            elif msg_type == "select_service":
                await self._handle_select_service(ws, session, msg)
            elif msg_type == "query":
                await self._handle_query(ws, session, msg)
            else:
                await _send(ws, {"type": "error", "message": f"알 수 없는 메시지 타입: {msg_type}"})

    async def _handle_auth(self, ws, session: UserSession, msg: dict):
        user_id = str(msg.get("user_id", "")).strip()
        if not user_id:
            await _send(ws, {"type": "error", "message": "user_id가 필요합니다."})
            return

        session.user_id = user_id
        services_payload = [
            {"id": s.id, "name": s.name, "description": s.description}
            for s in self._config.services
        ]
        await _send(
            ws,
            {
                "type": "auth_success",
                "user_id": user_id,
                "services": services_payload,
            },
        )
        logger.info(f"User authenticated: {user_id}")

    async def _handle_select_service(self, ws, session: UserSession, msg: dict):
        if not session.user_id:
            await _send(ws, {"type": "error", "message": "먼저 인증이 필요합니다."})
            return

        service_id = msg.get("service_id", "")
        service = self._service_map.get(service_id)
        if not service:
            await _send(ws, {"type": "error", "message": f"존재하지 않는 서비스: {service_id}"})
            return

        session.set_service(service.id, service.name, service.description)
        await _send(
            ws,
            {
                "type": "service_selected",
                "service_id": service.id,
                "service_name": service.name,
            },
        )
        logger.info(f"User {session.user_id} selected service: {service.name}")

    async def _handle_query(self, ws, session: UserSession, msg: dict):
        if not session.user_id:
            await _send(ws, {"type": "error", "message": "먼저 인증이 필요합니다."})
            return
        if not session.service_id:
            await _send(ws, {"type": "error", "message": "먼저 서비스를 선택해주세요."})
            return

        user_query = str(msg.get("message", "")).strip()
        if not user_query:
            await _send(ws, {"type": "error", "message": "질문 내용이 비어 있습니다."})
            return

        logger.info(f"Query from {session.user_id}: {user_query[:80]}")

        # Run blocking Claude + DB calls in a thread to avoid blocking the event loop
        try:
            await _send(ws, {"type": "status", "message": "요청을 분석하고 있습니다..."})

            is_valid, sql_or_reason = await asyncio.get_event_loop().run_in_executor(
                None, self._claude.generate_sql, session, user_query
            )

            if not is_valid:
                await _send(
                    ws,
                    {
                        "type": "rejected",
                        "message": f"## 처리 불가\n\n{sql_or_reason}",
                    },
                )
                return

            await _send(ws, {"type": "status", "message": "데이터베이스에서 조회 중입니다..."})

            rows = await asyncio.get_event_loop().run_in_executor(
                None, self._db.execute_select, sql_or_reason
            )

            await _send(ws, {"type": "status", "message": "결과를 정리하고 있습니다..."})

            formatted = await asyncio.get_event_loop().run_in_executor(
                None, self._claude.format_results, user_query, sql_or_reason, rows
            )

            await _send(ws, {"type": "response", "message": formatted})

        except ValueError as e:
            # SQL safety check failed
            await _send(ws, {"type": "error", "message": f"보안 오류: {e}"})
        except RuntimeError as e:
            await _send(ws, {"type": "error", "message": f"처리 중 오류가 발생했습니다: {e}"})
        except Exception as e:
            logger.error(f"Unexpected error handling query: {e}", exc_info=True)
            await _send(ws, {"type": "error", "message": "예기치 않은 오류가 발생했습니다."})

    async def start(self):
        host = self._config.server_host
        port = self._config.server_port
        logger.info(f"Starting WebSocket server on {host}:{port}")
        async with websockets.serve(self.handler, host, port):
            await asyncio.Future()
