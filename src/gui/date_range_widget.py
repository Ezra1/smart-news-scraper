"""Date range selector with presets and custom options."""

from datetime import datetime, timedelta

from PyQt6.QtWidgets import (
    QGroupBox,
    QVBoxLayout,
    QHBoxLayout,
    QRadioButton,
    QComboBox,
    QLabel,
    QDateEdit,
    QButtonGroup,
)
from PyQt6.QtCore import QDate

from src.config import ConfigManager


class DateRangeWidget(QGroupBox):
    """Date range selector with presets and custom options."""

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__("Publication dates", parent)
        self.setToolTip(
            "Restricts how far back (or which day) article search runs against the news API."
        )
        self.config_manager = config_manager
        self._init_ui()
        self.load_from_config(config_manager.config)

    def load_from_config(self, config: dict) -> None:
        """Restore widget state from a config dict (same rules as startup)."""
        self._load_from_config(config)

    def _init_ui(self):
        layout = QVBoxLayout()

        self.mode_group = QButtonGroup(self)

        preset_layout = QHBoxLayout()
        self.preset_radio = QRadioButton("Preset:")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(
            [
                "Last 24 hours",
                "Last 7 days",
                "Last 30 days",
                "Last 3 months",
                "Last 6 months",
                "Last year",
                "Last 2 years",
                "All time (no filter)",
            ]
        )
        self.preset_combo.setCurrentText("Last 7 days")
        preset_layout.addWidget(self.preset_radio)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()

        custom_layout = QHBoxLayout()
        self.custom_radio = QRadioButton("Custom range:")
        self.after_label = QLabel("After:")
        self.after_date = QDateEdit()
        self.after_date.setCalendarPopup(True)
        self.after_date.setDate(QDate.currentDate().addMonths(-1))
        self.before_label = QLabel("Before:")
        self.before_date = QDateEdit()
        self.before_date.setCalendarPopup(True)
        self.before_date.setDate(QDate.currentDate())
        custom_layout.addWidget(self.custom_radio)
        custom_layout.addWidget(self.after_label)
        custom_layout.addWidget(self.after_date)
        custom_layout.addWidget(self.before_label)
        custom_layout.addWidget(self.before_date)
        custom_layout.addStretch()

        specific_layout = QHBoxLayout()
        self.specific_radio = QRadioButton("Single day:")
        self.specific_date = QDateEdit()
        self.specific_date.setCalendarPopup(True)
        self.specific_date.setDate(QDate.currentDate())
        specific_layout.addWidget(self.specific_radio)
        specific_layout.addWidget(self.specific_date)
        specific_layout.addStretch()

        self.mode_group.addButton(self.preset_radio, 0)
        self.mode_group.addButton(self.custom_radio, 1)
        self.mode_group.addButton(self.specific_radio, 2)
        self.preset_radio.setChecked(True)

        self.preset_radio.toggled.connect(self._update_enabled_state)
        self.custom_radio.toggled.connect(self._update_enabled_state)
        self.specific_radio.toggled.connect(self._update_enabled_state)

        layout.addLayout(preset_layout)
        layout.addLayout(custom_layout)
        layout.addLayout(specific_layout)
        self.setLayout(layout)

        self._update_enabled_state()

    def _load_from_config(self, config: dict):
        mode = config.get("DATE_RANGE_MODE", "preset")
        preset = config.get("DATE_RANGE_PRESET", "Last 7 days")
        after = config.get("DATE_RANGE_AFTER", "")
        before = config.get("DATE_RANGE_BEFORE", "")
        specific = config.get("DATE_RANGE_ON", "")

        mode_map = {"preset": self.preset_radio, "custom": self.custom_radio, "specific": self.specific_radio}
        if mode in mode_map:
            mode_map[mode].setChecked(True)
        else:
            self.preset_radio.setChecked(True)

        if preset:
            self.preset_combo.setCurrentText(preset)

        if after:
            self.after_date.setDate(self._parse_date(after, fallback=QDate.currentDate().addMonths(-1)))
        if before:
            self.before_date.setDate(self._parse_date(before, fallback=QDate.currentDate()))
        if specific:
            self.specific_date.setDate(self._parse_date(specific, fallback=QDate.currentDate()))

        self._update_enabled_state()

    def _parse_date(self, date_str: str, fallback: QDate) -> QDate:
        parsed = QDate.fromString(date_str, "yyyy-MM-dd")
        return parsed if parsed.isValid() else fallback

    def _update_enabled_state(self):
        self.preset_combo.setEnabled(self.preset_radio.isChecked())
        self.after_date.setEnabled(self.custom_radio.isChecked())
        self.before_date.setEnabled(self.custom_radio.isChecked())
        self.specific_date.setEnabled(self.specific_radio.isChecked())

    def get_date_params(self) -> dict:
        params: dict = {}
        today = datetime.now()

        if self.preset_radio.isChecked():
            preset = self.preset_combo.currentText()
            if preset == "Last 24 hours":
                after = today - timedelta(days=1)
            elif preset == "Last 7 days":
                after = today - timedelta(days=7)
            elif preset == "Last 30 days":
                after = today - timedelta(days=30)
            elif preset == "Last 3 months":
                after = today - timedelta(days=90)
            elif preset == "Last 6 months":
                after = today - timedelta(days=180)
            elif preset == "Last year":
                after = today - timedelta(days=365)
            elif preset == "Last 2 years":
                after = today - timedelta(days=730)
            elif preset == "All time (no filter)":
                return {}
            else:
                after = today - timedelta(days=7)
            params["published_after"] = after.strftime("%Y-%m-%d")

        elif self.custom_radio.isChecked():
            after_qdate = self.after_date.date()
            before_qdate = self.before_date.date()
            params["published_after"] = after_qdate.toString("yyyy-MM-dd")
            params["published_before"] = before_qdate.toString("yyyy-MM-dd")

        elif self.specific_radio.isChecked():
            specific_qdate = self.specific_date.date()
            params["published_on"] = specific_qdate.toString("yyyy-MM-dd")

        return params

    def validate_selection(self) -> tuple[bool, str]:
        today = QDate.currentDate()

        if self.custom_radio.isChecked():
            if self.after_date.date() > self.before_date.date():
                return False, "The 'After' date must be on or before the 'Before' date."
            if self.before_date.date() > today:
                return False, "The 'Before' date cannot be in the future."

        if self.specific_radio.isChecked():
            if self.specific_date.date() > today:
                return False, "The specific date cannot be in the future."

        return True, ""

    def get_config_values(self) -> dict:
        mode = (
            "preset"
            if self.preset_radio.isChecked()
            else "custom"
            if self.custom_radio.isChecked()
            else "specific"
        )
        return {
            "DATE_RANGE_MODE": mode,
            "DATE_RANGE_PRESET": self.preset_combo.currentText(),
            "DATE_RANGE_AFTER": self.after_date.date().toString("yyyy-MM-dd"),
            "DATE_RANGE_BEFORE": self.before_date.date().toString("yyyy-MM-dd"),
            "DATE_RANGE_ON": self.specific_date.date().toString("yyyy-MM-dd"),
        }
