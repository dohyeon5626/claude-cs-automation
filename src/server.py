import asyncio
import base64
import csv as csvmod
import html as _html
import io
import json
import logging
import os
import pty
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from aiohttp import WSMsgType, web
from openpyxl import Workbook

from .agent import ClaudeAgent, UserSession, check_claude_cli_authenticated
from .auth import Authenticator
from .config import AppConfig
from .service import Service

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent / "web"

# Hard limit on a single user query (defends against bloated/abusive prompts)
_MAX_QUERY_LEN = 4000

# CSV download caps
_DOWNLOAD_TTL_SEC = 30 * 60            # downloads expire after 30 min
_MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024  # 5MB per file
_UTF8_BOM = b"\xef\xbb\xbf"            # makes Excel open Korean text correctly

# ```csv  optional-filename.csv\n ... \n``` — same fence as standard markdown
_CSV_BLOCK_RE = re.compile(
    r"```csv(?:[ \t]+([^\n`]+?))?[ \t]*\n(.*?)\n[ \t]*```",
    re.DOTALL | re.IGNORECASE,
)
# ```xlsx [filename.xlsx]\n ... ``` — multi-sheet workbook;
# sheets inside are delimited by "## sheet: <name>" header lines.
_XLSX_BLOCK_RE = re.compile(
    r"```xlsx(?:[ \t]+([^\n`]+?))?[ \t]*\n(.*?)\n[ \t]*```",
    re.DOTALL | re.IGNORECASE,
)
_SHEET_HEADER_RE = re.compile(
    r"^[ \t]*##[ \t]*sheet[ \t]*:[ \t]*(.+?)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
# Filename sanitizer — strip path separators and anything not alnum/dash/dot
_SAFE_FILENAME_RE = re.compile(r"[^\w가-힣\-. ]+")
# Sheet-name sanitizer — openpyxl rejects these chars, max 31 chars
_BAD_SHEET_CHARS = re.compile(r"[\\/?*\[\]:]")

# Content types for served downloads
_CT_CSV = "text/csv; charset=utf-8"
_CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Claude CLI status cache — login check spawns a subprocess (slow), so
# memoize the result for 60 seconds. Invalidated on login/logout actions.
_CLAUDE_STATUS_TTL = 60.0
# Claude login subprocess timeout — OAuth typically completes in ~30s
_CLAUDE_LOGIN_TIMEOUT = 300.0  # 5 minutes


_SHELL_PATHS = frozenset({"/", "/app.js", "/style.css", "/sw.js", "/manifest.json"})


def _set_pty_size(fd: int, rows: int, cols: int):
    """Tell the kernel the new (rows, cols) of a PTY via TIOCSWINSZ ioctl."""
    try:
        import fcntl
        import struct
        import termios
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


def _create_noop_browser_dir() -> str:
    """
    Build a tempdir of stub `open`/`xdg-open`/etc. binaries that do nothing.
    Prepending this to PATH stops `claude /login` from auto-launching a
    browser on the server — the operator clicks the URL inside the xterm
    modal instead, opening it in their own browser tab.
    """
    d = tempfile.mkdtemp(prefix="cs-claude-noopen-")
    for name in ("open", "xdg-open", "wslview", "sensible-browser", "x-www-browser"):
        p = os.path.join(d, name)
        with open(p, "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(p, 0o755)
    return d


@web.middleware
async def _no_cache_for_shell(request, handler):
    """
    Tell the browser to revalidate the page shell on every request.
    Without this, aiohttp's FileResponse omits Cache-Control entirely and the
    browser caches app.js for hours — so newly shipped UI fixes look broken
    until the user does a hard refresh. Revalidation is cheap (304 on no
    change) and keeps correctness ahead of bandwidth for this internal tool.
    """
    resp = await handler(request)
    if request.path in _SHELL_PATHS:
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


def _sanitize_filename(name: str, default_ext: str = ".csv") -> str:
    """
    Normalize a download filename suggested by Claude. Strips path components,
    forbids control chars, forces the given extension if missing, and caps
    length. default_ext is appended only when the name has no .csv/.xlsx ext.
    """
    name = (name or "").strip().strip("/\\")
    if "/" in name or "\\" in name:
        name = name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = name.strip("._ ") or ""
    if not name:
        return ""
    lower = name.lower()
    if not (lower.endswith(".csv") or lower.endswith(".xlsx")):
        name += default_ext
    return name[:120]


def _build_xlsx_from_block(body: str) -> Tuple[bytes, int]:
    """
    Parse a multi-sheet block into an .xlsx workbook.

    Format:
        ## sheet: 시트이름1
        헤더1,헤더2
        값,값
        ## sheet: 시트이름2
        ...

    Returns (xlsx_bytes, sheet_count). Falls back to a single "Sheet1"
    when the body has no ## sheet: markers (so single-sheet ```xlsx blocks
    still work).
    """
    sheets: List[Tuple[str, List[str]]] = []
    current_name = None
    current_lines: List[str] = []
    for line in body.splitlines():
        m = _SHEET_HEADER_RE.match(line)
        if m:
            if current_name is not None:
                sheets.append((current_name, current_lines))
            current_name = m.group(1).strip()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line)
        # Lines before the first ## sheet: marker are ignored as preamble.

    if current_name is not None:
        sheets.append((current_name, current_lines))

    # No markers at all → whole body becomes Sheet1
    if not sheets:
        sheets = [("Sheet1", body.splitlines())]

    wb = Workbook()
    wb.remove(wb.active)  # drop the default blank sheet
    used = set()
    for raw_name, lines in sheets:
        safe = _BAD_SHEET_CHARS.sub("_", raw_name).strip()[:31] or "Sheet"
        base = safe
        i = 2
        while safe in used:
            safe = f"{base[:28]}_{i}"
            i += 1
        used.add(safe)

        ws = wb.create_sheet(title=safe)
        # Strip blank trailing lines that often appear between sheets
        while lines and not lines[-1].strip():
            lines.pop()
        for row in csvmod.reader(io.StringIO("\n".join(lines))):
            ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), len(sheets)


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
        # token -> {filename, content (bytes), expires (epoch sec)}
        # In-memory only — survives until the server restarts.
        self._downloads: Dict[str, Dict] = {}
        # Claude CLI login status: {logged_in: bool, detail: str, checked_at: float}
        self._claude_status: Dict = {"logged_in": False, "detail": "unchecked", "checked_at": 0.0}
        # Lock to serialize login/logout subprocess calls (only one can run at a time)
        self._claude_login_lock = asyncio.Lock()
        # Active `claude login` subprocess + PTY master fd, if any.
        # Used by the paste handler to write the OAuth code to the CLI.
        self._claude_login_proc = None
        self._claude_login_master_fd: Optional[int] = None

    def build_app(self) -> web.Application:
        app = web.Application(middlewares=[_no_cache_for_shell])
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
                web.get("/api/download/{token}", self._serve_download),
                web.get("/api/claude/status", self._api_claude_status),
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
                "admin": bool(getattr(user, "admin", False)),
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

    # ── CSV download (large answers from Claude) ──────────────────────────────

    def _extract_downloads(self, answer: str) -> str:
        """Convert both ```csv and ```xlsx blocks into download links."""
        # xlsx first — its body can contain csv-style rows but the fence is
        # distinct, so order is for clarity rather than correctness.
        answer = _XLSX_BLOCK_RE.sub(self._replace_xlsx, answer)
        answer = _CSV_BLOCK_RE.sub(self._replace_csv, answer)
        return answer

    def _replace_csv(self, match) -> str:
        requested_name = (match.group(1) or "").strip()
        csv_text = match.group(2)
        filename = _sanitize_filename(requested_name, default_ext=".csv") or "data.csv"
        content = _UTF8_BOM + csv_text.encode("utf-8")
        if len(content) > _MAX_DOWNLOAD_BYTES:
            size_mb = len(content) / (1024 * 1024)
            return (
                f"_⚠️ CSV가 {size_mb:.1f}MB로 다운로드 한도(5MB)를 넘어 생략했습니다. "
                "조건을 좁히거나 더 작게 집계해 주세요._"
            )
        token = self._register_download(filename, content, content_type=_CT_CSV)
        return (
            f"📎 [엑셀 다운로드: {filename}](/api/download/{token}) "
            f"_({len(csv_text.splitlines())}행, {len(content) / 1024:.1f}KB)_"
        )

    def _replace_xlsx(self, match) -> str:
        requested_name = (match.group(1) or "").strip()
        body = match.group(2)
        filename = _sanitize_filename(requested_name, default_ext=".xlsx") or "data.xlsx"
        if not filename.lower().endswith(".xlsx"):
            # User-given .csv name with multi-sheet block — bump to .xlsx
            filename = filename.rsplit(".", 1)[0] + ".xlsx"
        try:
            content, sheet_count = _build_xlsx_from_block(body)
        except Exception as e:
            logger.warning(f"xlsx build failed: {e}", exc_info=True)
            return f"_⚠️ Excel 변환에 실패했습니다: {e}_"
        if len(content) > _MAX_DOWNLOAD_BYTES:
            size_mb = len(content) / (1024 * 1024)
            return (
                f"_⚠️ Excel이 {size_mb:.1f}MB로 다운로드 한도(5MB)를 넘어 생략했습니다. "
                "조건을 좁히거나 시트 수를 줄여 주세요._"
            )
        token = self._register_download(filename, content, content_type=_CT_XLSX)
        return (
            f"📎 [엑셀 다운로드: {filename}](/api/download/{token}) "
            f"_(시트 {sheet_count}개, {len(content) / 1024:.1f}KB)_"
        )

    def _register_download(
        self, filename: str, content: bytes, *, content_type: str = _CT_CSV,
    ) -> str:
        """Store a download under a random token. Best-effort GC of expired."""
        now = time.time()
        # Lazy purge — no background thread; cheap enough on every register
        for tok in list(self._downloads):
            if self._downloads[tok]["expires"] < now:
                del self._downloads[tok]
        token = secrets.token_urlsafe(16)
        self._downloads[token] = {
            "filename": filename,
            "content": content,
            "content_type": content_type,
            "expires": now + _DOWNLOAD_TTL_SEC,
        }
        return token

    async def _serve_download(self, request):
        token = request.match_info["token"]
        item = self._downloads.get(token)
        if not item or item["expires"] < time.time():
            return web.Response(
                status=404,
                text="다운로드 링크가 만료되었거나 존재하지 않습니다.",
            )
        # RFC 5987 filename* lets browsers handle non-ASCII names correctly
        filename = item["filename"]
        ascii_fallback = re.sub(r"[^\x20-\x7e]", "_", filename) or "download.csv"
        from urllib.parse import quote
        disposition = (
            f'attachment; filename="{ascii_fallback}"; '
            f"filename*=UTF-8''{quote(filename)}"
        )
        return web.Response(
            body=item["content"],
            headers={
                "Content-Type": item.get("content_type", _CT_CSV),
                "Content-Disposition": disposition,
            },
        )

    # ── Claude CLI account management ─────────────────────────────────────────

    async def _api_claude_status(self, request):
        """REST endpoint for the header status indicator on page load."""
        # Allow anyone (even unauthenticated) so the login view could also
        # show "Claude 로그아웃됨" if we ever want — currently only used by
        # the authenticated app shell.
        status = await self._get_claude_status(force=False)
        return web.json_response(status)

    async def _get_claude_status(self, *, force: bool) -> Dict:
        """
        Cached "is Claude logged in?" check. Set force=True to bypass cache
        (used right after a login/logout to surface the new state).
        """
        now = time.time()
        if not force and (now - self._claude_status["checked_at"] < _CLAUDE_STATUS_TTL):
            return dict(self._claude_status)

        # Run the ping on the executor so we don't block the event loop
        loop = asyncio.get_running_loop()
        logged_in, detail = await loop.run_in_executor(
            None,
            check_claude_cli_authenticated,
            self._config.claude_model,
            self._config.claude_binary,
            10,  # quick timeout — UI is waiting
        )
        self._claude_status = {
            "logged_in": logged_in,
            "detail": detail,
            "checked_at": now,
        }
        return dict(self._claude_status)

    async def _ws_claude_login(self, ws, user, cols: int = 80, rows: int = 24):
        """
        Spawn the Claude CLI in a PTY and pipe it both directions to the
        browser's xterm.js, so the admin can drive /login interactively.
        """
        if not getattr(user, "admin", False):
            await ws.send_json({
                "type": "claude_login_done",
                "ok": False,
                "message": "Claude 로그인 권한이 없습니다.",
            })
            return

        if self._claude_login_lock.locked():
            await ws.send_json({
                "type": "claude_login_done",
                "ok": False,
                "message": "다른 관리자가 이미 로그인 작업을 진행 중입니다.",
            })
            return

        async with self._claude_login_lock:
            await ws.send_json({"type": "claude_login_started"})

            try:
                master_fd, slave_fd = pty.openpty()
            except Exception as e:
                await ws.send_json({
                    "type": "claude_login_done",
                    "ok": False,
                    "message": f"PTY 생성 실패: {e}",
                })
                return

            # Tell the kernel how big the terminal is BEFORE spawning so
            # Claude's ink TUI sees a sane geometry — without this it often
            # fails to lay out and silently ignores keyboard input.
            _set_pty_size(slave_fd, max(rows, 10), max(cols, 40))

            # Suppress browser auto-launch on the server so the operator
            # clicks the URL in the xterm modal (opens in THEIR browser tab)
            # instead of a tab popping up on the host machine.
            noop_dir = None
            try:
                noop_dir = _create_noop_browser_dir()
            except Exception as e:
                logger.warning(f"noop-browser dir failed: {e}")

            env = os.environ.copy()
            env.setdefault("TERM", "xterm-256color")
            env["LINES"] = str(max(rows, 10))
            env["COLUMNS"] = str(max(cols, 40))
            env["BROWSER"] = "true"  # respected by many CLIs
            if noop_dir:
                env["PATH"] = noop_dir + os.pathsep + env.get("PATH", "")

            try:
                proc = await asyncio.create_subprocess_exec(
                    self._config.claude_binary,
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    start_new_session=True,
                    env=env,
                )
            except Exception as e:
                os.close(master_fd)
                os.close(slave_fd)
                if noop_dir:
                    shutil.rmtree(noop_dir, ignore_errors=True)
                await ws.send_json({
                    "type": "claude_login_done",
                    "ok": False,
                    "message": f"실행 실패: {e}",
                })
                return
            os.close(slave_fd)

            self._claude_login_proc = proc
            self._claude_login_master_fd = master_fd

            loop = asyncio.get_running_loop()

            def on_readable():
                try:
                    data = os.read(master_fd, 4096)
                except OSError:
                    data = b""
                if not data:
                    try:
                        loop.remove_reader(master_fd)
                    except Exception:
                        pass
                    return
                # Forward raw PTY bytes to the browser's xterm.js as base64
                asyncio.create_task(ws.send_json({
                    "type": "claude_login_data",
                    "data": base64.b64encode(data).decode("ascii"),
                }))

            try:
                loop.add_reader(master_fd, on_readable)
            except Exception as e:
                logger.warning(f"add_reader failed: {e}")

            async def poll_status():
                """Auto-detect login success via the lightweight `claude -p OK` ping."""
                while True:
                    await asyncio.sleep(3)
                    if ws.closed:
                        return None
                    s = await self._get_claude_status(force=True)
                    if s["logged_in"]:
                        return s

            async def auto_send_login():
                """
                Type /login into the TUI for the user. ~1.6s gives the ink
                splash/welcome banner enough time to render and grab stdin.
                """
                await asyncio.sleep(1.6)
                if proc.returncode is None:
                    try:
                        os.write(master_fd, b"/login\r")
                    except OSError:
                        pass

            proc_task = asyncio.create_task(proc.wait())
            poll_task = asyncio.create_task(poll_status())
            auto_login_task = asyncio.create_task(auto_send_login())

            try:
                done, pending = await asyncio.wait(
                    [proc_task, poll_task],
                    timeout=_CLAUDE_LOGIN_TIMEOUT,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                auto_login_task.cancel()
                try:
                    loop.remove_reader(master_fd)
                except Exception:
                    pass

            timed_out = not done
            for t in (proc_task, poll_task):
                if not t.done():
                    t.cancel()

            # If the TUI is still running, ask it to quit first; SIGTERM as a
            # backstop so we don't leak the subprocess.
            if proc.returncode is None:
                try:
                    os.write(master_fd, b"/quit\n")
                except OSError:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2)
                except asyncio.TimeoutError:
                    pass
            if proc.returncode is None:
                try:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), timeout=3)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        proc.kill()
                        await proc.wait()
                    except ProcessLookupError:
                        pass

            try:
                os.close(master_fd)
            except OSError:
                pass

            if noop_dir:
                shutil.rmtree(noop_dir, ignore_errors=True)

            self._claude_login_proc = None
            self._claude_login_master_fd = None

            if timed_out:
                await ws.send_json({
                    "type": "claude_login_done",
                    "ok": False,
                    "message": "로그인 시간이 초과되었습니다 (5분).",
                })
                return

            status = await self._get_claude_status(force=True)
            ok = status["logged_in"]
            await ws.send_json({
                "type": "claude_login_done",
                "ok": ok,
                "message": (
                    "로그인되었습니다." if ok
                    else f"로그인을 완료하지 못했습니다. {status.get('detail', '')}"
                ),
                "status": status,
            })

    async def _ws_claude_login_input(self, user, data: str):
        """Forward a keystroke (or paste) from xterm.js into the live PTY."""
        if not getattr(user, "admin", False):
            return
        fd = getattr(self, "_claude_login_master_fd", None)
        proc = getattr(self, "_claude_login_proc", None)
        if fd is None or proc is None or proc.returncode is not None:
            return
        try:
            os.write(fd, data.encode("utf-8"))
        except OSError:
            pass

    async def _ws_claude_login_cancel(self, user):
        """User closed the modal — terminate the in-flight subprocess."""
        if not getattr(user, "admin", False):
            return
        proc = getattr(self, "_claude_login_proc", None)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass

    async def _ws_claude_login_resize(self, user, cols: int, rows: int):
        """Match the PTY size to xterm.js so the TUI relays out correctly."""
        if not getattr(user, "admin", False):
            return
        fd = getattr(self, "_claude_login_master_fd", None)
        if fd is None:
            return
        _set_pty_size(fd, max(rows, 10), max(cols, 40))

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
                    await ws.send_json({
                        "type": "auth_success",
                        "user_id": user.id,
                        "admin": bool(getattr(user, "admin", False)),
                    })
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

                elif mtype == "cancel":
                    if session and session.current_task and not session.current_task.done():
                        session.request_cancel()
                    # No in-flight query → silently ignore (idempotent)
                    continue

                elif mtype == "claude_login":
                    if not user:
                        await ws.send_json({"type": "error", "message": "먼저 로그인해 주세요."})
                        continue
                    cols = int(data.get("cols") or 80)
                    rows = int(data.get("rows") or 24)
                    # Spawn as a task so the receive loop keeps processing
                    # subsequent claude_login_input/resize/cancel messages —
                    # otherwise the user's keystrokes never reach the PTY.
                    asyncio.create_task(
                        self._ws_claude_login(ws, user, cols=cols, rows=rows)
                    )
                    continue

                elif mtype == "claude_login_input":
                    if not user:
                        continue
                    await self._ws_claude_login_input(user, str(data.get("data", "")))
                    continue

                elif mtype == "claude_login_resize":
                    if not user:
                        continue
                    cols = int(data.get("cols") or 80)
                    rows = int(data.get("rows") or 24)
                    await self._ws_claude_login_resize(user, cols, rows)
                    continue

                elif mtype == "claude_login_cancel":
                    if not user:
                        continue
                    await self._ws_claude_login_cancel(user)
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
                    if session.current_task and not session.current_task.done():
                        await ws.send_json({
                            "type": "error",
                            "message": "이전 요청이 처리 중입니다. 완료 후 다시 시도하거나 중단 버튼을 눌러 주세요.",
                        })
                        continue
                    # Bail early when Claude is logged out — no point spawning
                    # an agent task that will fail on the first CLI call.
                    status = await self._get_claude_status(force=False)
                    if not status["logged_in"]:
                        await ws.send_json({
                            "type": "error",
                            "message": "Claude 로그인이 필요합니다. 헤더의 'Claude 로그인' 버튼을 관리자가 눌러 주세요.",
                            "claude_auth_required": True,
                        })
                        continue
                    # Spawn as a task so this receive loop keeps running and
                    # can deliver subsequent cancel/select_service messages.
                    session.current_task = asyncio.create_task(
                        self._process_query(ws, session, service, message, loop)
                    )

                else:
                    await ws.send_json({"type": "error", "message": f"알 수 없는 메시지: {mtype}"})

        except Exception as e:
            logger.error(f"WebSocket error: {e}", exc_info=True)
        finally:
            # If the client vanished mid-query, signal the background work to
            # stop so we don't keep burning CLI time on an absent user.
            if session and session.current_task and not session.current_task.done():
                session.request_cancel()
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

        async def _safe_send(payload):
            # The peer may have disconnected while the executor was running.
            # Don't let "Cannot write to closing transport" mask the original
            # error or break the WS handler loop.
            if ws.closed:
                return
            try:
                await ws.send_json(payload)
            except Exception as send_err:
                logger.warning(f"WebSocket send failed: {send_err}")

        try:
            await _safe_send({"type": "status", "message": "요청 분석 중..."})
            answer = await loop.run_in_executor(
                None,
                self._agent.process_query,
                session,
                service,
                message,
                status_callback,
            )
            # Swap any ```csv/```xlsx blocks for download links before send
            answer = self._extract_downloads(answer)
            await _safe_send({"type": "response", "message": answer})
        except Exception as e:
            # agent.process_query already wrote an audit entry with queries_log;
            # no need to log again here.
            logger.error(f"Query processing error: {e}", exc_info=True)
            await _safe_send(
                {"type": "error", "message": f"처리 중 오류가 발생했습니다: {e}"}
            )
        finally:
            done.set()
            keepalive_task.cancel()
