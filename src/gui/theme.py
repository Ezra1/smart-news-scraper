"""Central palette and spacing for the analyst-style desktop UI."""

COLORS = {
    "bg": "#1A1A1A",
    "bg_elevated": "#222222",
    "bg_card": "#242424",
    "border_subtle": "#333333",
    "border_focus": "#50587A",
    "text": "#E6E6E6",
    "text_secondary": "#A8A8A8",
    "accent": "#7077A1",
    "accent_muted": "#424769",
    "success": "#5CB85C",
    "warning": "#E8A54B",
    "error": "#E05555",
    "sidebar_bg": "#1E1E22",
}

SPACING = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
}


def app_stylesheet() -> str:
    """Global QSS: restrained, hierarchy-first."""
    c = COLORS
    return f"""
        QMainWindow, QWidget {{
            background-color: {c["bg"]};
            color: {c["text"]};
        }}
        QWidget {{ font-family: 'Segoe UI', 'Ubuntu', 'Arial', sans-serif; font-size: 13px; }}
        QFrame#card {{
            background-color: {c["bg_card"]};
            border: 1px solid {c["border_subtle"]};
            border-radius: 6px;
        }}
        QLabel#sectionTitle {{
            font-size: 15px;
            font-weight: 600;
            color: {c["text"]};
        }}
        QLabel#muted {{
            color: {c["text_secondary"]};
            font-size: 12px;
        }}
        QLabel#subsectionTitle {{
            font-size: 13px;
            font-weight: 600;
            color: {c["text"]};
            margin-top: 2px;
        }}
        QPushButton#linkToggle {{
            background: transparent;
            border: none;
            color: {c["accent"]};
            text-align: left;
            padding: 6px 0;
            font-weight: 500;
        }}
        QPushButton#linkToggle:hover {{
            color: #8B92B8;
        }}
        QLabel#badge {{
            padding: 2px 8px;
            border-radius: 4px;
            background-color: {c["bg_elevated"]};
            border: 1px solid {c["border_subtle"]};
            font-size: 11px;
        }}
        QListWidget#sidebar {{
            background-color: {c["sidebar_bg"]};
            border: none;
            padding: 8px 0;
        }}
        QListWidget#sidebar::item {{
            padding: 12px 16px;
            margin: 2px 6px;
            border-radius: 4px;
        }}
        QListWidget#sidebar::item:selected {{
            background-color: {c["accent_muted"]};
            color: {c["text"]};
        }}
        QListWidget#sidebar::item:hover {{
            background-color: {c["bg_elevated"]};
        }}
        QPushButton {{
            background-color: {c["accent_muted"]};
            color: {c["text"]};
            border: none;
            border-radius: 4px;
            padding: 8px 16px;
            font-weight: 500;
            min-width: 88px;
        }}
        QPushButton:hover {{ background-color: {c["accent"]}; }}
        QPushButton:disabled {{ background-color: #3A3A3A; color: #777777; }}
        QPushButton#primary {{ background-color: {c["accent"]}; font-weight: 600; }}
        QPushButton#primary:hover {{ background-color: #8B92B8; }}
        QLineEdit, QTextEdit, QPlainTextEdit {{
            padding: 8px;
            border: 1px solid {c["border_subtle"]};
            border-radius: 4px;
            background-color: {c["bg_elevated"]};
            selection-background-color: {c["accent"]};
        }}
        QGroupBox {{
            font-weight: 600;
            border: 1px solid {c["border_subtle"]};
            border-radius: 6px;
            margin-top: 14px;
            padding-top: 18px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 6px;
            color: {c["text_secondary"]};
        }}
        QProgressBar {{
            border: none;
            border-radius: 3px;
            background-color: {c["bg_elevated"]};
            min-height: 14px;
            max-height: 24px;
            text-align: center;
            font-size: 11px;
        }}
        QProgressBar::chunk {{ background-color: {c["accent"]}; border-radius: 3px; }}
        QScrollArea {{ border: none; }}
        QTableWidget {{
            gridline-color: {c["border_subtle"]};
            background-color: {c["bg_elevated"]};
            alternate-background-color: {c["bg"]};
        }}
        QHeaderView::section {{
            background-color: {c["bg_card"]};
            padding: 8px;
            border: none;
            font-weight: 600;
            font-size: 12px;
        }}
        QStatusBar {{ background-color: {c["sidebar_bg"]}; border-top: 1px solid {c["border_subtle"]}; }}
    """
