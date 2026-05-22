import asyncio
import json
import logging
from pathlib import Path

from aiohttp import WSMsgType, web

from auth import Authenticator
from claude_handler import ClaudeHandler, UserSession
from config import AppConfig

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent / "web"


class WebServer:
    """aiohttp application: serves the web page, the REST API, and the WebSocket."""

    def __init__(self, config: AppConfig, claude: ClaudeHandler, auth: Authenticator):
        self._config = config
        self._claude = claude
        self._auth = auth
        self._services = {s.id: s for s in config.services}

    def build_app(self) -> web.Application:
        app = web.Application()
        app.add_routes(
            [
                web.get("/", self._serve_index),
                web.get("/style.css", self._serve_css),
                web.get("/app.js", self._serve_js),
                web.get("/favicon.ico", self._favicon),
                web.post("/api/login", self._api_login),
                web.post("/api/query", self._api_query),
                web.get("/ws", self._handle_ws),
            ]
        )
        return app

    # ── Static files ──────────────────────────────────────────────────────────

    async def _serve_index(self, request):
        return web.FileResponse(_WEB_DIR / "index.html")

    async def _serve_css(self, request):
        return web.FileResponse(_WEB_DIR / "style.css")

    async def _serve_js(self, request):
        return web.FileResponse(_WEB_DIR / "app.js")

    async def _favicon(self, request):
        return web.Response(status=204)

    # ── REST: login ───────────────────────────────────────────────────────────

    async def _api_login(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "잘못된 요청 형식입니다."}, status=400)

        token = self._auth.login(
            str(data.get("user_id", "")).strip(),
            str(data.get("password", "")),
        )
        if not token:
            return web.json_response(
                {"error": "아이디 또는 비밀번호가 올바르지 않습니다."}, status=401
            )

        user = self._auth.user_for_token(token)
        services = [
            {"id": s.id, "name": s.name, "description": s.description}
            for s in self._auth.allowed_services(user)
        ]
        logger.info(f"Login success: {user.id}")
        return web.json_response(
            {
                "token": token,
                "user_id": user.id,
                "user_name": user.name,
                "services": services,
            }
        )

    # ── REST: query (programmatic API) ────────────────────────────────────────

    async def _api_query(self, request):
        token = self._extract_token(request)
        user = self._auth.user_for_token(token)
        if not user:
            return web.json_response({"error": "인증이 필요합니다."}, status=401)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "잘못된 요청 형식입니다."}, status=400)

        service_id = str(data.get("service_id", ""))
        message = str(data.get("message", "")).strip()
        service = self._services.get(service_id)

        if not service or not self._auth.can_access(user, service_id):
            return web.json_response({"error": "접근할 수 없는 서비스입니다."}, status=403)
        if not message:
            return web.json_response({"error": "질문 내용이 비어 있습니다."}, status=400)

        session = UserSession(user_id=user.id)
        session.set_service(service.id, service.name, service.description)

        loop = asyncio.get_running_loop()
        try:
            answer = await loop.run_in_executor(
                None, self._claude.process_query, session, message, lambda s: None
            )
        except Exception as e:
            logger.error(f"API query error: {e}", exc_info=True)
            return web.json_response({"error": f"처리 중 오류: {e}"}, status=500)

        return web.json_response({"answer": answer})

    @staticmethod
    def _extract_token(request) -> str:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        return request.query.get("token", "")

    # ── WebSocket: interactive chat ───────────────────────────────────────────

    async def _handle_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        loop = asyncio.get_running_loop()

        user = None
        session = None
        logger.info("WebSocket client connected")

        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "잘못된 메시지 형식입니다."})
                    continue

                mtype = data.get("type", "")

                if mtype == "auth":
                    user = self._auth.user_for_token(data.get("token", ""))
                    if not user:
                        await ws.send_json(
                            {"type": "auth_error", "message": "인증에 실패했습니다. 다시 로그인해 주세요."}
                        )
                        await ws.close()
                        break
                    session = UserSession(user_id=user.id)
                    await ws.send_json({"type": "auth_success", "user_id": user.id})
                    logger.info(f"WebSocket authenticated: {user.id}")

                elif mtype == "select_service":
                    if not user or not session:
                        await ws.send_json({"type": "error", "message": "먼저 로그인해 주세요."})
                        continue
                    service = self._services.get(data.get("service_id", ""))
                    if not service or not self._auth.can_access(user, service.id):
                        await ws.send_json({"type": "error", "message": "접근할 수 없는 서비스입니다."})
                        continue
                    session.set_service(service.id, service.name, service.description)
                    await ws.send_json(
                        {
                            "type": "service_selected",
                            "service_id": service.id,
                            "service_name": service.name,
                        }
                    )
                    logger.info(f"{user.id} selected service: {service.name}")

                elif mtype == "query":
                    if not user or not session:
                        await ws.send_json({"type": "error", "message": "먼저 로그인해 주세요."})
                        continue
                    if not session.service_id:
                        await ws.send_json({"type": "error", "message": "먼저 서비스를 선택해 주세요."})
                        continue
                    message = str(data.get("message", "")).strip()
                    if not message:
                        await ws.send_json({"type": "error", "message": "질문 내용이 비어 있습니다."})
                        continue
                    await self._process_query(ws, session, message, loop)

                else:
                    await ws.send_json({"type": "error", "message": f"알 수 없는 메시지: {mtype}"})

        except Exception as e:
            logger.error(f"WebSocket error: {e}", exc_info=True)
        finally:
            logger.info(
                f"WebSocket disconnected: {user.id if user else 'unauthenticated'}"
            )

        return ws

    async def _process_query(self, ws, session: UserSession, message: str, loop):
        logger.info(f"Query from {session.user_id}: {message[:80]}")

        def status_callback(text: str):
            # Called from the executor thread; re-dispatch onto the event loop
            asyncio.run_coroutine_threadsafe(
                ws.send_json({"type": "status", "message": text}), loop
            )

        try:
            await ws.send_json({"type": "status", "message": "요청을 분석하고 있습니다..."})
            answer = await loop.run_in_executor(
                None, self._claude.process_query, session, message, status_callback
            )
            await ws.send_json({"type": "response", "message": answer})
        except Exception as e:
            logger.error(f"Query processing error: {e}", exc_info=True)
            await ws.send_json(
                {"type": "error", "message": f"처리 중 오류가 발생했습니다: {e}"}
            )
