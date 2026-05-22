from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from config import Settings, save_settings


class SettingsDialog(QDialog):
    """Settings dialog for changing server IP, port, and user ID."""

    def __init__(self, current: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumWidth(360)
        self.setModal(True)
        self._current = current
        self._build_ui(current)

    def _build_ui(self, s: Settings):
        root = QVBoxLayout(self)
        root.setSpacing(16)

        note = QLabel("설정 변경 후 서버 재연결이 필요할 수 있습니다.")
        note.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(note)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._ip = QLineEdit(s.server_ip)
        self._ip.setPlaceholderText("예: 192.168.1.100")
        self._ip.setMinimumHeight(34)

        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(s.server_port)
        self._port.setMinimumHeight(34)

        self._user_id = QLineEdit(s.user_id)
        self._user_id.setPlaceholderText("예: CS001")
        self._user_id.setMinimumHeight(34)

        form.addRow("서버 IP:", self._ip)
        form.addRow("서버 포트:", self._port)
        form.addRow("사용자 ID:", self._user_id)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_save(self):
        ip = self._ip.text().strip()
        user_id = self._user_id.text().strip()

        if not ip:
            QMessageBox.warning(self, "입력 오류", "서버 IP를 입력해주세요.")
            return
        if not user_id:
            QMessageBox.warning(self, "입력 오류", "사용자 ID를 입력해주세요.")
            return

        new_settings = Settings(
            server_ip=ip,
            server_port=self._port.value(),
            user_id=user_id,
        )
        save_settings(new_settings)
        self._result_settings = new_settings
        self.accept()

    def get_new_settings(self) -> Settings:
        return self._result_settings
