from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ServicePage(QWidget):
    """Service selection screen shown after successful authentication."""

    service_selected = pyqtSignal(str, str)  # service_id, service_name
    settings_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._services: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 30, 40, 30)
        root.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("서비스 선택")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #1a1a2e;")
        header.addWidget(title)
        header.addStretch()

        settings_btn = QPushButton("설정")
        settings_btn.setFixedSize(60, 32)
        settings_btn.setStyleSheet(
            "QPushButton { background: #e9ecef; border-radius: 6px; font-size: 13px; }"
            "QPushButton:hover { background: #dee2e6; }"
        )
        settings_btn.clicked.connect(self.settings_requested)
        header.addWidget(settings_btn)
        root.addLayout(header)

        self._status_label = QLabel("서버에서 서비스 목록을 가져오는 중...")
        self._status_label.setStyleSheet("color: #888; font-size: 13px;")
        root.addWidget(self._status_label)

        self._list = QListWidget()
        self._list.setSpacing(4)
        self._list.setStyleSheet(
            "QListWidget {"
            "  border: 1px solid #dee2e6; border-radius: 8px; background: white;"
            "  font-size: 14px;"
            "}"
            "QListWidget::item { padding: 14px 16px; border-bottom: 1px solid #f1f3f5; }"
            "QListWidget::item:selected {"
            "  background: #e7f0ff; color: #1a1a2e;"
            "}"
            "QListWidget::item:hover { background: #f8f9fa; }"
        )
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        root.addWidget(self._list)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._select_btn = QPushButton("선택")
        self._select_btn.setMinimumSize(120, 40)
        self._select_btn.setEnabled(False)
        self._select_btn.setStyleSheet(
            "QPushButton {"
            "  background: #4361ee; color: white; border-radius: 8px;"
            "  font-size: 14px; font-weight: bold;"
            "}"
            "QPushButton:disabled { background: #adb5bd; }"
            "QPushButton:hover:!disabled { background: #3a56d4; }"
        )
        self._select_btn.clicked.connect(self._on_select)
        btn_row.addWidget(self._select_btn)
        root.addLayout(btn_row)

        self._list.itemSelectionChanged.connect(
            lambda: self._select_btn.setEnabled(bool(self._list.selectedItems()))
        )

        self.setStyleSheet("QWidget { background: #f8f9fa; }")

    def populate(self, services: list[dict]):
        self._services = services
        self._list.clear()
        for s in services:
            item = QListWidgetItem(f"  {s['name']}\n  {s.get('description', '')}")
            item.setData(Qt.ItemDataRole.UserRole, s)
            self._list.addItem(item)

        count = len(services)
        self._status_label.setText(f"총 {count}개의 서비스 — 담당 서비스를 선택하세요.")
        self._status_label.setStyleSheet("color: #495057; font-size: 13px;")

    def _on_item_double_clicked(self, item: QListWidgetItem):
        self._emit_selection(item)

    def _on_select(self):
        items = self._list.selectedItems()
        if items:
            self._emit_selection(items[0])

    def _emit_selection(self, item: QListWidgetItem):
        data = item.data(Qt.ItemDataRole.UserRole)
        self.service_selected.emit(data["id"], data["name"])
