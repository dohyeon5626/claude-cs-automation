from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import Settings, save_settings


class SetupPage(QWidget):
    """First-run setup screen that collects server IP, port, and user ID."""

    setup_complete = pyqtSignal(object)  # emits Settings

    def __init__(self, current_settings: Settings, parent=None):
        super().__init__(parent)
        self._build_ui(current_settings)

    def _build_ui(self, s: Settings):
        root = QVBoxLayout(self)
        root.setContentsMargins(60, 40, 60, 40)
        root.setSpacing(24)

        title = QLabel("CS Automation 초기 설정")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #1a1a2e;")
        root.addWidget(title)

        subtitle = QLabel("서버 주소와 사용자 ID를 입력하면 바로 사용할 수 있습니다.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #666; font-size: 13px;")
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ip_input = QLineEdit(s.server_ip)
        self._ip_input.setPlaceholderText("예: 192.168.1.100")
        self._ip_input.setMinimumHeight(36)

        self._port_input = QSpinBox()
        self._port_input.setRange(1, 65535)
        self._port_input.setValue(s.server_port)
        self._port_input.setMinimumHeight(36)

        self._user_input = QLineEdit(s.user_id)
        self._user_input.setPlaceholderText("예: CS001")
        self._user_input.setMinimumHeight(36)

        form.addRow("서버 IP:", self._ip_input)
        form.addRow("서버 포트:", self._port_input)
        form.addRow("사용자 ID:", self._user_input)
        root.addLayout(form)

        root.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._save_btn = QPushButton("저장 후 연결")
        self._save_btn.setMinimumSize(140, 42)
        self._save_btn.setStyleSheet(
            "QPushButton {"
            "  background: #4361ee; color: white; border-radius: 8px;"
            "  font-size: 14px; font-weight: bold;"
            "}"
            "QPushButton:hover { background: #3a56d4; }"
            "QPushButton:pressed { background: #2d46c0; }"
        )
        self._save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self._save_btn)
        root.addLayout(btn_row)

        self.setStyleSheet("QWidget { background: #f8f9fa; }")

    def _on_save(self):
        ip = self._ip_input.text().strip()
        user_id = self._user_input.text().strip()

        if not ip:
            QMessageBox.warning(self, "입력 오류", "서버 IP를 입력해주세요.")
            self._ip_input.setFocus()
            return
        if not user_id:
            QMessageBox.warning(self, "입력 오류", "사용자 ID를 입력해주세요.")
            self._user_input.setFocus()
            return

        settings = Settings(
            server_ip=ip,
            server_port=self._port_input.value(),
            user_id=user_id,
        )
        save_settings(settings)
        self.setup_complete.emit(settings)
