import markdown
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 14px;
    background: #f8f9fa;
    margin: 0;
    padding: 0;
}
.msg { margin: 8px 12px; }
.user-bubble {
    background: #4361ee;
    color: white;
    border-radius: 12px 12px 4px 12px;
    padding: 10px 14px;
    display: inline-block;
    max-width: 75%;
    float: right;
    clear: both;
    margin-bottom: 4px;
}
.bot-bubble {
    background: white;
    color: #1a1a2e;
    border-radius: 12px 12px 12px 4px;
    padding: 10px 14px;
    display: block;
    clear: both;
    border: 1px solid #dee2e6;
    margin-bottom: 4px;
}
.bot-bubble table {
    border-collapse: collapse;
    width: 100%;
    margin: 8px 0;
}
.bot-bubble th, .bot-bubble td {
    border: 1px solid #dee2e6;
    padding: 6px 10px;
    text-align: left;
}
.bot-bubble th { background: #f1f3f5; font-weight: bold; }
.bot-bubble code {
    background: #f1f3f5;
    padding: 2px 5px;
    border-radius: 4px;
    font-family: monospace;
}
.bot-bubble pre {
    background: #f1f3f5;
    padding: 10px;
    border-radius: 6px;
    overflow-x: auto;
}
.status-line {
    color: #888;
    font-size: 12px;
    text-align: center;
    clear: both;
    padding: 4px 0;
}
.error-line {
    color: #d62828;
    font-size: 13px;
    background: #fff0f0;
    border: 1px solid #f7a7a7;
    border-radius: 8px;
    padding: 8px 12px;
    clear: both;
    margin: 4px 12px;
}
.label {
    font-size: 11px;
    color: #888;
    clear: both;
    padding: 2px 14px;
}
.label-right { text-align: right; }
"""

_HTML_TEMPLATE = f"""
<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>{_CSS}</style>
</head><body id="body"></body></html>
"""


class EnterSendTextEdit(QTextEdit):
    """QTextEdit that sends on Enter and inserts newline on Shift+Enter."""

    enter_pressed = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent):
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            self.enter_pressed.emit()
        else:
            super().keyPressEvent(event)


class ChatPage(QWidget):
    """Main chat interface for querying the CS server."""

    query_submitted = pyqtSignal(str)
    service_change_requested = pyqtSignal()
    settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._md = markdown.Markdown(extensions=["tables", "fenced_code"])
        self._messages_html = ""
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("background: #4361ee;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 16, 0)

        self._service_label = QLabel("CS Agent")
        self._service_label.setStyleSheet(
            "color: white; font-size: 15px; font-weight: bold;"
        )
        h_layout.addWidget(self._service_label)
        h_layout.addStretch()

        for text, slot in [("서비스 변경", self.service_change_requested), ("설정", self.settings_requested)]:
            btn = QPushButton(text)
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                "QPushButton { background: rgba(255,255,255,0.2); color: white;"
                " border-radius: 6px; padding: 0 12px; font-size: 13px; }"
                "QPushButton:hover { background: rgba(255,255,255,0.3); }"
            )
            btn.clicked.connect(slot)
            h_layout.addWidget(btn)

        root.addWidget(header)

        # Chat display
        self._chat = QTextBrowser()
        self._chat.setOpenExternalLinks(False)
        self._chat.setStyleSheet(
            "QTextBrowser { background: #f8f9fa; border: none; }"
        )
        self._chat.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._chat.setHtml(_HTML_TEMPLATE)
        root.addWidget(self._chat)

        # Status bar
        self._status_bar = QLabel("")
        self._status_bar.setFixedHeight(22)
        self._status_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_bar.setStyleSheet(
            "background: #e9ecef; color: #666; font-size: 12px;"
        )
        root.addWidget(self._status_bar)

        # Input area
        input_container = QWidget()
        input_container.setStyleSheet("background: white; border-top: 1px solid #dee2e6;")
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(12, 8, 12, 8)
        input_layout.setSpacing(8)

        self._input = EnterSendTextEdit()
        self._input.setPlaceholderText("질문을 입력하세요... (Enter: 전송, Shift+Enter: 줄바꿈)")
        self._input.setFixedHeight(72)
        self._input.setStyleSheet(
            "QTextEdit {"
            "  border: 1px solid #dee2e6; border-radius: 8px;"
            "  padding: 8px; font-size: 14px;"
            "}"
            "QTextEdit:focus { border-color: #4361ee; }"
        )
        self._input.enter_pressed.connect(self._on_send)

        self._send_btn = QPushButton("전송")
        self._send_btn.setFixedSize(64, 72)
        self._send_btn.setStyleSheet(
            "QPushButton {"
            "  background: #4361ee; color: white; border-radius: 8px;"
            "  font-size: 14px; font-weight: bold;"
            "}"
            "QPushButton:disabled { background: #adb5bd; }"
            "QPushButton:hover:!disabled { background: #3a56d4; }"
        )
        self._send_btn.clicked.connect(self._on_send)

        input_layout.addWidget(self._input)
        input_layout.addWidget(self._send_btn)
        root.addWidget(input_container)

    def set_service(self, service_id: str, service_name: str):
        self._service_label.setText(f"CS Agent — {service_name}")
        self._messages_html = ""
        self._chat.setHtml(_HTML_TEMPLATE)

    def set_status(self, text: str):
        self._status_bar.setText(text)

    def set_sending(self, sending: bool):
        self._send_btn.setEnabled(not sending)
        self._input.setEnabled(not sending)

    def append_user_message(self, text: str):
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._append_html(
            f'<div class="label label-right">나</div>'
            f'<div class="msg"><div class="user-bubble">{escaped}</div></div>'
            f'<div style="clear:both;"></div>'
        )

    def append_bot_message(self, md_text: str):
        self._md.reset()
        html_body = self._md.convert(md_text)
        self._append_html(
            f'<div class="label">CS Agent</div>'
            f'<div class="msg"><div class="bot-bubble">{html_body}</div></div>'
            f'<div style="clear:both;"></div>'
        )

    def append_error(self, text: str):
        escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self._append_html(f'<div class="error-line">오류: {escaped}</div>')

    def append_status_line(self, text: str):
        self._append_html(f'<div class="status-line">{text}</div>')

    def _append_html(self, fragment: str):
        self._messages_html += fragment
        full = (
            f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<style>{_CSS}</style></head><body>"
            f"{self._messages_html}"
            f"</body></html>"
        )
        self._chat.setHtml(full)
        self._chat.verticalScrollBar().setValue(
            self._chat.verticalScrollBar().maximum()
        )

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self.query_submitted.emit(text)
