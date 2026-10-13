"""Koyu / açık tema renkleri ve Qt stil sayfası."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_text: str
    success: str
    warning: str
    danger: str
    info: str
    sidebar: str
    sidebar_text: str
    sidebar_active: str
    selection: str
    video_bg: str


DARK = Palette(
    name="dark",
    bg="#0F141A",
    surface="#171D25",
    surface_alt="#1F2731",
    border="#2A3441",
    text="#E7ECF2",
    muted="#8D9AAB",
    accent="#3B82F6",
    accent_hover="#5B9BFF",
    accent_text="#FFFFFF",
    success="#22C55E",
    warning="#F59E0B",
    danger="#EF4444",
    info="#38BDF8",
    sidebar="#0B1015",
    sidebar_text="#AEB9C7",
    sidebar_active="#1C2633",
    selection="#24406B",
    video_bg="#05080B",
)

LIGHT = Palette(
    name="light",
    bg="#F3F5F8",
    surface="#FFFFFF",
    surface_alt="#F7F9FB",
    border="#DDE3EA",
    text="#17202B",
    muted="#66768A",
    accent="#2563EB",
    accent_hover="#3B82F6",
    accent_text="#FFFFFF",
    success="#16A34A",
    warning="#D97706",
    danger="#DC2626",
    info="#0284C7",
    sidebar="#111821",
    sidebar_text="#B5C0CD",
    sidebar_active="#1F2B3A",
    selection="#D4E3FD",
    video_bg="#0B0F14",
)

_current: Palette = DARK


def current() -> Palette:
    return _current


def stylesheet(p: Palette) -> str:
    return f"""
    QWidget {{
        color: {p.text};
        font-size: 10pt;
    }}
    QMainWindow, QDialog, #PageRoot {{
        background: {p.bg};
    }}
    QToolTip {{
        background: {p.surface_alt};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 4px 6px;
    }}

    /* ---------- kenar menü ---------- */
    #Sidebar {{
        background: {p.sidebar};
    }}
    #SidebarTitle {{
        color: #FFFFFF;
        font-size: 13pt;
        font-weight: 700;
    }}
    #SidebarSubtitle {{
        color: {p.sidebar_text};
        font-size: 8.5pt;
    }}
    #NavButton {{
        background: transparent;
        color: {p.sidebar_text};
        border: none;
        border-radius: 8px;
        padding: 10px 14px;
        text-align: left;
        font-size: 10.5pt;
    }}
    #NavButton:hover {{
        background: {p.sidebar_active};
        color: #FFFFFF;
    }}
    #NavButton:checked {{
        background: {p.sidebar_active};
        color: #FFFFFF;
        font-weight: 600;
        border-left: 3px solid {p.accent};
    }}
    #SidebarFooter {{
        color: {p.sidebar_text};
        font-size: 8.5pt;
    }}

    /* ---------- başlıklar ---------- */
    #PageTitle {{
        font-size: 17pt;
        font-weight: 700;
    }}
    #PageSubtitle, #Muted {{
        color: {p.muted};
    }}
    #SectionTitle {{
        font-size: 11.5pt;
        font-weight: 600;
    }}

    /* ---------- kartlar ---------- */
    #Card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    #CardTitle {{
        color: {p.muted};
        font-size: 9pt;
        font-weight: 600;
        letter-spacing: 0.5px;
    }}
    #CardValue {{
        font-size: 21pt;
        font-weight: 700;
    }}
    #CardHint {{
        color: {p.muted};
        font-size: 9pt;
    }}

    /* ---------- düğmeler ---------- */
    QPushButton {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{
        border-color: {p.accent};
    }}
    QPushButton:pressed {{
        background: {p.border};
    }}
    QPushButton:disabled {{
        color: {p.muted};
        border-color: {p.border};
    }}
    QPushButton:checked {{
        background: {p.selection};
        border-color: {p.accent};
        font-weight: 600;
    }}
    QPushButton[variant="primary"] {{
        background: {p.accent};
        border-color: {p.accent};
        color: {p.accent_text};
        font-weight: 600;
    }}
    QPushButton[variant="primary"]:hover {{
        background: {p.accent_hover};
    }}
    QPushButton[variant="danger"] {{
        background: transparent;
        border-color: {p.danger};
        color: {p.danger};
    }}
    QPushButton[variant="danger"]:hover {{
        background: {p.danger};
        color: #FFFFFF;
    }}
    QPushButton[variant="success"] {{
        background: {p.success};
        border-color: {p.success};
        color: #FFFFFF;
        font-weight: 600;
    }}

    /* ---------- form alanları ---------- */
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit,
    QPlainTextEdit, QTextEdit {{
        background: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 7px;
        padding: 5px 8px;
        selection-background-color: {p.accent};
        selection-color: #FFFFFF;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QDateEdit:focus, QPlainTextEdit:focus {{
        border-color: {p.accent};
    }}
    QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
        width: 0px;
        border: none;
    }}
    QComboBox::drop-down, QDateEdit::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {p.surface};
        border: 1px solid {p.border};
        selection-background-color: {p.selection};
        selection-color: {p.text};
        outline: none;
    }}
    QCheckBox {{
        spacing: 8px;
    }}
    QGroupBox {{
        border: 1px solid {p.border};
        border-radius: 10px;
        margin-top: 14px;
        padding: 12px 10px 10px 10px;
        background: {p.surface};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {p.muted};
        font-weight: 600;
    }}

    /* ---------- tablolar ve listeler ---------- */
    QTableView, QListView, QTreeView {{
        background: {p.surface};
        alternate-background-color: {p.surface_alt};
        border: 1px solid {p.border};
        border-radius: 10px;
        gridline-color: transparent;
        selection-background-color: {p.selection};
        selection-color: {p.text};
        outline: none;
    }}
    QTableView::item {{
        padding: 4px 6px;
        border: none;
    }}
    QHeaderView::section {{
        background: {p.surface};
        color: {p.muted};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 8px 6px;
        font-weight: 600;
    }}
    QTableCornerButton::section {{
        background: {p.surface};
        border: none;
    }}

    /* ---------- sekmeler ---------- */
    QTabWidget::pane {{
        border: none;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {p.muted};
        padding: 8px 16px;
        border-bottom: 2px solid transparent;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        color: {p.text};
        border-bottom: 2px solid {p.accent};
    }}
    QTabBar::tab:hover {{
        color: {p.text};
    }}

    /* ---------- kaydırma çubukları ---------- */
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle {{
        background: {p.border};
        border-radius: 4px;
        min-height: 30px;
        min-width: 30px;
    }}
    QScrollBar::handle:hover {{
        background: {p.muted};
    }}
    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {{
        background: none;
        border: none;
        width: 0;
        height: 0;
    }}

    QProgressBar {{
        background: {p.surface_alt};
        border: none;
        border-radius: 4px;
        height: 8px;
        text-align: center;
        color: transparent;
    }}
    QProgressBar::chunk {{
        border-radius: 4px;
        background: {p.accent};
    }}
    QProgressBar[level="warning"]::chunk {{
        background: {p.warning};
    }}
    QProgressBar[level="danger"]::chunk {{
        background: {p.danger};
    }}

    QStatusBar {{
        background: {p.surface};
        border-top: 1px solid {p.border};
        color: {p.muted};
    }}
    QStatusBar::item {{
        border: none;
    }}
    QMenu {{
        background: {p.surface};
        border: 1px solid {p.border};
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 18px;
        border-radius: 5px;
    }}
    QMenu::item:selected {{
        background: {p.selection};
    }}
    """


def apply_theme(app: QApplication, name: str = "dark") -> Palette:
    global _current
    palette = LIGHT if name == "light" else DARK
    _current = palette
    app.setStyle("Fusion")

    qpal = QPalette()
    roles = {
        QPalette.ColorRole.Window: palette.bg,
        QPalette.ColorRole.WindowText: palette.text,
        QPalette.ColorRole.Base: palette.surface,
        QPalette.ColorRole.AlternateBase: palette.surface_alt,
        QPalette.ColorRole.Text: palette.text,
        QPalette.ColorRole.Button: palette.surface_alt,
        QPalette.ColorRole.ButtonText: palette.text,
        QPalette.ColorRole.Highlight: palette.accent,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: palette.surface_alt,
        QPalette.ColorRole.ToolTipText: palette.text,
        QPalette.ColorRole.PlaceholderText: palette.muted,
        QPalette.ColorRole.Link: palette.accent,
    }
    for role, color in roles.items():
        qpal.setColor(role, QColor(color))
    qpal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(palette.muted))
    qpal.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(palette.muted)
    )
    app.setPalette(qpal)

    font = app.font()
    if font.pointSizeF() < 9.5:
        font.setPointSizeF(10)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(stylesheet(palette))
    return palette
