import sys

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config import Settings, load_settings, save_settings
from ui.chat_page import ChatPage
from ui.service_page import ServicePage
from ui.settings_dialog import SettingsDialog
from ui.setup_page import SetupPage
from ws_client import WebSocketClient

# ── Page indices in QStackedWidget ───────────────────────────────────────────
PAGE_SETUP = 0
PAGE_CONNECTING = 1
PAGE_SERVICE = 2
PAGE_CHAT = 3


class SignalBridge(QObject):
    """Bridges asyncio callbacks → Qt signals safely across threads."""

    message = pyqtSignal(dict)
    connected = pyqtSignal()
    disconnected = pyqtSignal(str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CS Automation")
        self.setMinimumSize(800, 600)

        self._settings = load_settings()
        self._ws = WebSocketClient()
        self._bridge = SignalBridge()

        self._ws.on_message = lambda msg: self._bridge.message.emit(msg)
        self._ws.on_connected = lambda: self._bridge.connected.emit()
        self._ws.on_disconnected = lambda reason: self._bridge.disconnected.emit(reason)

        self._bridge.message.connect(self._on_message)
        self._bridge.connected.connect(self._on_connected)
        self._bridge.disconnected.connect(self._on_disconnected)

        self._build_ui()

        if self._settings.is_configured():
            self._start_connection()
        else:
            self._stack.setCurrentIndex(PAGE_SETUP)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        # Page 0: Setup
        self._setup_page = SetupPage(self._settings)
        self._setup_page.setup_complete.connect(self._on_setup_complete)
        self._stack.addWidget(self._setup_page)

        # Page 1: Connecting
        connecting_widget = QWidget()
        connecting_widget.setStyleSheet("background: #f8f9fa;")
        cl = QVBoxLayout(connecting_widget)
        self._connecting_label = QLabel("서버에 연결 중...")
        self._connecting_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._connecting_label.setStyleSheet("font-size: 16px; color: #666;")
        cl.addStretch()
        cl.addWidget(self._connecting_label)
        cl.addStretch()
        self._stack.addWidget(connecting_widget)

        # Page 2: Service selection
        self._service_page = ServicePage()
        self._service_page.service_selected.connect(self._on_service_selected)
        self._service_page.settings_requested.connect(self._open_settings)
        self._stack.addWidget(self._service_page)

        # Page 3: Chat
        self._chat_page = ChatPage()
        self._chat_page.query_submitted.connect(self._on_query)
        self._chat_page.service_change_requested.connect(
            lambda: self._stack.setCurrentIndex(PAGE_SERVICE)
        )
        self._chat_page.settings_requested.connect(self._open_settings)
        self._stack.addWidget(self._chat_page)

    # ── Connection management ─────────────────────────────────────────────────

    def _start_connection(self):
        self._connecting_label.setText(
            f"서버에 연결 중...\n{self._settings.ws_url}"
        )
        self._stack.setCurrentIndex(PAGE_CONNECTING)
        self._ws.connect(self._settings.ws_url)

    @pyqtSlot(object)
    def _on_setup_complete(self, settings: Settings):
        self._settings = settings
        self._start_connection()

    @pyqtSlot()
    def _on_connected(self):
        self._ws.send({"type": "auth", "user_id": self._settings.user_id})

    @pyqtSlot(str)
    def _on_disconnected(self, reason: str):
        current = self._stack.currentIndex()
        if current == PAGE_CHAT:
            self._chat_page.append_error(f"연결이 끊어졌습니다: {reason}")
            self._chat_page.set_status("연결 끊김")
            self._chat_page.set_sending(False)
        elif current in (PAGE_CONNECTING, PAGE_SERVICE):
            QMessageBox.warning(
                self,
                "연결 실패",
                f"서버에 연결할 수 없습니다.\n{reason}\n\n설정을 확인해주세요.",
            )
            self._stack.setCurrentIndex(PAGE_SETUP)

    # ── Message routing ───────────────────────────────────────────────────────

    @pyqtSlot(dict)
    def _on_message(self, msg: dict):
        t = msg.get("type", "")

        if t == "auth_success":
            services = msg.get("services", [])
            self._service_page.populate(services)
            self._stack.setCurrentIndex(PAGE_SERVICE)

        elif t == "service_selected":
            sid = msg.get("service_id", "")
            sname = msg.get("service_name", "")
            self._chat_page.set_service(sid, sname)
            self._chat_page.set_status(f"서비스: {sname}")
            self._stack.setCurrentIndex(PAGE_CHAT)

        elif t == "status":
            self._chat_page.set_status(msg.get("message", ""))

        elif t == "response":
            self._chat_page.set_sending(False)
            self._chat_page.set_status("")
            self._chat_page.append_bot_message(msg.get("message", ""))

        elif t == "rejected":
            self._chat_page.set_sending(False)
            self._chat_page.set_status("")
            self._chat_page.append_bot_message(msg.get("message", ""))

        elif t == "error":
            self._chat_page.set_sending(False)
            self._chat_page.set_status("")
            self._chat_page.append_error(msg.get("message", "알 수 없는 오류"))

        elif t == "auth_required":
            pass  # handled automatically on_connected

    # ── User actions ──────────────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_service_selected(self, service_id: str, service_name: str):
        self._ws.send({"type": "select_service", "service_id": service_id})

    @pyqtSlot(str)
    def _on_query(self, text: str):
        self._chat_page.append_user_message(text)
        self._chat_page.set_sending(True)
        self._chat_page.set_status("처리 중...")
        self._ws.send({"type": "query", "message": text})

    def _open_settings(self):
        dialog = SettingsDialog(self._settings, parent=self)
        if dialog.exec():
            new_settings = dialog.get_new_settings()
            changed = (
                new_settings.server_ip != self._settings.server_ip
                or new_settings.server_port != self._settings.server_port
                or new_settings.user_id != self._settings.user_id
            )
            self._settings = new_settings
            if changed:
                self._ws.disconnect()
                self._start_connection()

    def closeEvent(self, event):
        self._ws.disconnect()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName("CS Automation")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
