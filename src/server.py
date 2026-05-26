import asyncio
import html as _html
import json
import logging
from pathlib import Path
from typing import Dict

from aiohttp import WSMsgType, web

from . import audit
from .agent import ClaudeAgent, UserSession
from .auth import Authenticator
from .config import AppConfig
from .service import Service

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent / "web"

# Hard limit on a single user query (defends against bloated/abusive prompts)
_MAX_QUERY_LEN = 4000


def _serve_local_file(configured: str):
    """Return a FileResponse for a configured local path, or 404."""
    path_str = (configured or "").strip()
    if not path_str or path_str.startswith(("http://", "https://")):
        return web.Response(status=404)
    path = Path(path_str)
    if not path.is_absolute():
        path = path.resolve()
    if not path.exists() or not path.is_file():
        return web.Response(status=404)
    return web.FileResponse(path)


class WebServer:
    """aiohttp application: serves the web page, the REST API, and the WebSocket."""

    def __init__(
        self,
        config: AppConfig,
        agent: ClaudeAgent,
        auth: Authenticator,
        services: Dict[str, Service],
    ):
        self._config = config
        self._agent = agent
        self._auth = auth
        self._services = services

    def build_app(self) -> web.Application:
        app = web.Application()
        app.add_routes(
            [
                web.get("/", self._serve_index),
                web.get("/style.css", self._serve_css),
                web.get("/app.js", self._serve_js),
                web.get("/logo", self._serve_logo),
                web.get("/service/{sid}/logo", self._serve_service_logo),
                web.get("/favicon.ico", self._favicon),
                web.get("/manifest.json", self._serve_manifest),
                web.get("/sw.js", self._serve_sw),
                web.post("/api/login", self._api_login),
                web.post("/api/query", self._api_query),
                web.get("/ws", self._handle_ws),
            ]
        )
        return app

    # ── Brand / logo rendering ────────────────────────────────────────────────

    def _logo_html(self, size_classes: str) -> str:
        """
        Return HTML for the brand mark. Either an <img> when brand.logo is set,
        or a gradient square containing the first character of brand.name.
        """
        logo = self._config.brand_logo
        if logo:
            src = logo if logo.startswith(("http://", "https://")) else "/logo"
            return (
                f'<img src="{_html.escape(src)}" alt="" '
                f'class="{size_classes} rounded-lg object-cover shadow-sm shrink-0">'
            )
        initial = _html.escape((self._config.brand_name.strip()[:1] or "?").upper())
        return (
            f'<div class="{size_classes} rounded-lg bg-gradient-to-br '
            f'from-violet-500 to-indigo-600 flex items-center justify-center '
            f'shadow-sm shrink-0">'
            f'<span class="text-white font-bold text-xs tracking-tight">{initial}</span>'
            f"</div>"
        )

    def _service_logo_url(self, svc_cfg) -> str:
        """URL the browser should use to fetch this service's logo. Empty if none."""
        logo = (svc_cfg.logo or "").strip()
        if not logo:
            return ""
        if logo.startswith(("http://", "https://")):
            return logo
        return f"/service/{svc_cfg.id}/logo"

    async def _serve_logo(self, request):
        """
        Serve the brand logo. Resolution order:
          - http(s)://… → 302 redirect to the configured URL
          - local path  → serve the file
          - empty       → fall back to a generated SVG with the brand initial
                          (keeps favicon, apple-touch-icon, and PWA icons
                          working out of the box even with no logo set)
        """
        logo = (self._config.brand_logo or "").strip()
        if logo and logo.startswith(("http://", "https://")):
            raise web.HTTPFound(logo)
        if logo:
            return _serve_local_file(logo)

        initial = _html.escape((self._config.brand_name.strip()[:1] or "?").upper())
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">'
            '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0%" stop-color="#8b5cf6"/>'
            '<stop offset="100%" stop-color="#4f46e5"/>'
            '</linearGradient></defs>'
            '<rect width="192" height="192" rx="36" fill="url(#g)"/>'
            f'<text x="96" y="128" font-family="system-ui, -apple-system, sans-serif" '
            f'font-size="100" font-weight="700" text-anchor="middle" fill="white">'
            f'{initial}</text>'
            '</svg>'
        )
        return web.Response(text=svg, content_type="image/svg+xml")

    async def _serve_service_logo(self, request):
        """Serve a service's local logo file."""
        sid = request.match_info["sid"]
        svc = self._services.get(sid)
        if not svc:
            return web.Response(status=404)
        return _serve_local_file(svc.config.logo)

    # ── Static files ──────────────────────────────────────────────────────────

    async def _serve_index(self, request):
        # Render the brand placeholders from config.yml on each request
        template = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
        rendered = (
            template
            .replace("{{BRAND_NAME}}", _html.escape(self._config.brand_name))
            .replace("{{BRAND_LOGO_LG}}", self._logo_html("w-9 h-9"))
            .replace("{{BRAND_LOGO_SM}}", self._logo_html("w-8 h-8"))
        )
        return web.Response(text=rendered, content_type="text/html")

    async def _serve_css(self, request):
        return web.FileResponse(_WEB_DIR / "style.css")

    async def _serve_js(self, request):
        return web.FileResponse(_WEB_DIR / "app.js")

    async def _favicon(self, request):
        # /logo always returns a usable image (logo or generated fallback)
        return await self._serve_logo(request)

    async def _serve_manifest(self, request):
        """PWA manifest — dynamically built from the current brand config."""
        name = self._config.brand_name
        manifest = {
            "name": name,
            "short_name": name,
            "description": f"{name} — CS 데이터 조회",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#0f172a",
            "icons": [
                {"src": "/logo", "sizes": "any",       "type": "image/svg+xml"},
                {"src": "/logo", "sizes": "192x192",   "type": "image/png"},
                {"src": "/logo", "sizes": "512x512",   "type": "image/png"},
            ],
        }
        return web.json_response(manifest, content_type="application/manifest+json")

    async def _serve_sw(self, request):
        """Minimal service worker — required for PWA install eligibility."""
        js = (
            "self.addEventListener('install', e => self.skipWaiting());\n"
            "self.addEventListener('activate', e => self.clients.claim());\n"
            "self.addEventListener('fetch', () => {});\n"
        )
        return web.Response(text=js, content_type="application/javascript")

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
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "logo_url": self._service_logo_url(s),
            }
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
        if len(message) > _MAX_QUERY_LEN:
            return web.json_response(
                {"error": f"질문이 너무 깁니다 (최대 {_MAX_QUERY_LEN}자)."},
                status=400,
            )

        session = UserSession(user_id=user.id)
        session.select_service(service_id)
        loop = asyncio.get_running_loop()
        try:
            answer = await loop.run_in_executor(
                None,
                self._agent.process_query,
                session,
                service,
                message,
                lambda s: None,
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
        # heartbeat sends a WS ping every 30s. receive_timeout=None disables
        # aiohttp's auto-derived 60s idle close — `async for msg in ws` blocks
        # during `_process_query`, so client pong frames aren't consumed and
        # long queries (>60s) would otherwise look idle and get killed.
        ws = web.WebSocketResponse(heartbeat=30, receive_timeout=None)
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
                    session.select_service(service.id)
                    await ws.send_json(
                        {
                            "type": "service_selected",
                            "service_id": service.id,
                            "service_name": service.name,
                        }
                    )
                    logger.info(f"{user.id} selected service: {service.name}")

                elif mtype == "pong":
                    # Reply to our application-level keepalive; nothing to do.
                    continue

                elif mtype == "query":
                    if not user or not session:
                        await ws.send_json({"type": "error", "message": "먼저 로그인해 주세요."})
                        continue
                    service = self._services.get(session.service_id or "")
                    if not service:
                        await ws.send_json({"type": "error", "message": "먼저 서비스를 선택해 주세요."})
                        continue
                    message = str(data.get("message", "")).strip()
                    if not message:
                        await ws.send_json({"type": "error", "message": "질문 내용이 비어 있습니다."})
                        continue
                    if len(message) > _MAX_QUERY_LEN:
                        await ws.send_json({
                            "type": "error",
                            "message": f"질문이 너무 깁니다 (최대 {_MAX_QUERY_LEN}자).",
                        })
                        continue
                    await self._process_query(ws, session, service, message, loop)

                else:
                    await ws.send_json({"type": "error", "message": f"알 수 없는 메시지: {mtype}"})

        except Exception as e:
            logger.error(f"WebSocket error: {e}", exc_info=True)
        finally:
            logger.info(
                f"WebSocket disconnected: {user.id if user else 'unauthenticated'}"
            )

        return ws

    async def _process_query(self, ws, session, service, message, loop):
        logger.info(f"Query from {session.user_id} ({service.id}): {message[:80]}")

        def status_callback(text: str):
            # Called from the executor thread; re-dispatch onto the event loop
            asyncio.run_coroutine_threadsafe(
                ws.send_json({"type": "status", "message": text}), loop
            )

        # Application-level keepalive: send a small JSON ping every 20s while
        # the executor runs. WS protocol pings alone aren't enough — some
        # intermediaries (proxies/firewalls) drop the socket if no app-layer
        # traffic flows for a while, which surfaces as
        # "Cannot write to closing transport" when we try to send the answer.
        done = asyncio.Event()

        async def _keepalive():
            while not done.is_set():
                try:
                    await asyncio.wait_for(done.wait(), timeout=20)
                    return  # done was set — query finished, stop pinging
                except asyncio.TimeoutError:
                    if ws.closed:
                        return
                    try:
                        await ws.send_json({"type": "ping"})
                    except Exception:
                        return

        keepalive_task = asyncio.ensure_future(_keepalive())

        try:
            await ws.send_json({"type": "status", "message": "요청 분석 중..."})
            answer = await loop.run_in_executor(
                None,
                self._agent.process_query,
                session,
                service,
                message,
                status_callback,
            )
            await ws.send_json({"type": "response", "message": answer})
        except Exception as e:
            logger.error(f"Query processing error: {e}", exc_info=True)
            audit.log_query_event({
                "ts": audit.now_iso(),
                "user": session.user_id,
                "service": service.id,
                "question": message,
                "answered": False,
                "reason": "error",
                "error": str(e),
            })
            await ws.send_json(
                {"type": "error", "message": f"처리 중 오류가 발생했습니다: {e}"}
            )
        finally:
            done.set()
            keepalive_task.cancel()
