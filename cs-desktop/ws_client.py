import asyncio
import json
import threading
from typing import Callable, Optional

import websockets


class WebSocketClient:
    """
    Runs an asyncio event loop in a background thread.
    Communicates with the PyQt6 UI via callbacks (called from the asyncio thread;
    callers should use Qt signals to re-dispatch to the main thread if needed).
    """

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._ws: Optional[websockets.ClientConnection] = None
        self._send_queue: asyncio.Queue = asyncio.Queue()

        # Callbacks set by the UI layer
        self.on_message: Optional[Callable[[dict], None]] = None
        self.on_connected: Optional[Callable[[], None]] = None
        self.on_disconnected: Optional[Callable[[str], None]] = None

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # ── Public API (called from Qt main thread) ──────────────────────────────

    def connect(self, url: str):
        asyncio.run_coroutine_threadsafe(self._connect(url), self._loop)

    def send(self, data: dict):
        asyncio.run_coroutine_threadsafe(
            self._send_queue.put(json.dumps(data, ensure_ascii=False)),
            self._loop,
        )

    def disconnect(self):
        asyncio.run_coroutine_threadsafe(self._disconnect(), self._loop)

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    # ── Internal asyncio coroutines ───────────────────────────────────────────

    async def _connect(self, url: str):
        try:
            self._ws = await websockets.connect(url, open_timeout=10)
            if self.on_connected:
                self.on_connected()
            await asyncio.gather(self._recv_loop(), self._send_loop())
        except Exception as e:
            self._ws = None
            if self.on_disconnected:
                self.on_disconnected(str(e))

    async def _recv_loop(self):
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if self.on_message:
                    self.on_message(msg)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._ws = None
            # Drain send queue
            while not self._send_queue.empty():
                try:
                    self._send_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            if self.on_disconnected:
                self.on_disconnected("연결이 종료되었습니다.")

    async def _send_loop(self):
        while self._ws and not self._ws.closed:
            try:
                raw = await asyncio.wait_for(self._send_queue.get(), timeout=1.0)
                await self._ws.send(raw)
            except asyncio.TimeoutError:
                continue
            except websockets.exceptions.ConnectionClosed:
                break

    async def _disconnect(self):
        if self._ws and not self._ws.closed:
            await self._ws.close()
