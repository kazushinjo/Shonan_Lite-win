"""Help画面。モック準拠の章一覧+本文レイアウト。

Pi5実機とWindows版でアプリの挙動(起動時Pluto再起動の有無・Langstone等の
カード表示・TX/RX排他制御・受信復調の前提)が異なるため、章データは
platform_compat.IS_WINDOWSで切り替える(manual_content.py / manual_content_win.py)。
"""
from __future__ import annotations

import os

from PyQt5 import QtCore, QtGui, QtWidgets
import platform_compat
from manual_content import MANUAL_SCREENSHOTS, MANUAL_SECTIONS
from manual_content_win import MANUAL_SCREENSHOTS_WIN, MANUAL_SECTIONS_WIN
from manual_content_win_en import MANUAL_SCREENSHOTS_WIN_EN, MANUAL_SECTIONS_WIN_EN
from widgets import SettingsSubScreen
from i18n import is_english, tr

# Windows版操作説明書(docs/build_operation_manual_win.pyで生成)。
_WIN_MANUAL_DOCX = "shonan_lite_win_operation_manual.docx"
_WIN_MANUAL_DOCX_EN = "shonan_lite_win_operation_manual_en.docx"


class ManualScreen(SettingsSubScreen):
    def __init__(self, main_window):
        super().__init__("ヘルプ / Help", lambda: main_window.navigate_to("home"))
        # Windows版のみ英語の章データを持つ(Pi5実機版manual_content.pyは日本語のみ)。
        if platform_compat.IS_WINDOWS and is_english():
            self.sections = MANUAL_SECTIONS_WIN_EN
            self.screenshots = MANUAL_SCREENSHOTS_WIN_EN
        else:
            self.sections = MANUAL_SECTIONS_WIN if platform_compat.IS_WINDOWS else MANUAL_SECTIONS
            self.screenshots = MANUAL_SCREENSHOTS_WIN if platform_compat.IS_WINDOWS else MANUAL_SCREENSHOTS
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.body_layout.setContentsMargins(14, 10, 14, 10)

        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(12)
        self.body_layout.addLayout(columns, 1)

        nav_card = QtWidgets.QFrame()
        nav_card.setFixedWidth(300)
        nav_card.setStyleSheet("QFrame { background: #191d1f; border-radius: 12px; } QLabel { color: white; font-size: 22px; font-weight: bold; } QListWidget { background: #191d1f; color: white; border: none; font-size: 22px; } QListWidget::item { padding: 8px 6px; border-radius: 5px; } QListWidget::item:selected { background: #0c9bc0; }")
        nav_layout = QtWidgets.QVBoxLayout(nav_card)
        nav_layout.setContentsMargins(10, 10, 10, 10)
        nav_layout.setSpacing(6)
        nav_layout.addWidget(QtWidgets.QLabel(tr("ヘルプ項目", "Help Topics")))
        self.section_list = QtWidgets.QListWidget()
        self.section_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # 長い章タイトルは1行に省略表示(...)する。選択すると右側の内容ペインの
        # 見出しに全文が表示されるため、ナビ側での省略表示で情報は失われない。
        for title, _items in self.sections:
            item = QtWidgets.QListWidgetItem(title)
            item.setToolTip(title)
            self.section_list.addItem(item)
        self.section_list.currentRowChanged.connect(self._show_section)
        nav_layout.addWidget(self.section_list, 1)
        columns.addWidget(nav_card)

        content_card = QtWidgets.QFrame()
        content_card.setStyleSheet("QFrame { background: #191d1f; border-radius: 12px; } QLabel { color: white; background: transparent; }")
        content_layout = QtWidgets.QVBoxLayout(content_card)
        content_layout.setContentsMargins(16, 12, 16, 12)
        content_layout.setSpacing(8)
        self.content_title = QtWidgets.QLabel()
        self.content_title.setStyleSheet("font-size: 26px; font-weight: bold; color: white;")
        content_layout.addWidget(self.content_title)
        self.content_text = QtWidgets.QTextBrowser()
        self.content_text.setOpenExternalLinks(True)
        self.content_text.setStyleSheet("QTextBrowser { background: #101416; color: #d9e1e4; border: 1px solid #30383c; border-radius: 6px; padding: 8px; font-size: 22px; }")
        content_layout.addWidget(self.content_text, 1)
        self.manual_button = QtWidgets.QPushButton(
            tr("操作説明書(Word)を開く", "Open Operation Manual (Word)") if platform_compat.IS_WINDOWS
            else tr("PDFマニュアルを開く", "Open PDF Manual"))
        self.manual_button.setStyleSheet("font-size: 22px;")
        self.manual_button.setFixedHeight(46)
        self.manual_button.clicked.connect(self._open_manual)
        content_layout.addWidget(self.manual_button)
        columns.addWidget(content_card, 1)
        self.section_list.setCurrentRow(0)

    def _show_section(self, index: int) -> None:
        if not 0 <= index < len(self.sections):
            return
        title, items = self.sections[index]
        self.content_title.setText(title)
        html = []
        image_name = self.screenshots.get(title)
        if image_name:
            # 一部の章は複数スクリーンショット(リスト)を持つため、単一パス名と
            # どちらでも扱えるようにする。
            image_names = image_name if isinstance(image_name, list) else [image_name]
            image_dir = platform_compat.app_dir() / "docs" / "images"
            existing = [name for name in image_names if (image_dir / name).exists()]
            if existing:
                html.append(f'<p style="color:#8fb3ff;">{tr("実機画面", "Screen")}：{title}</p>')
                for name in existing:
                    html.append(f'<p><img src="{(image_dir / name).as_uri()}" width="560"></p>')
        for subtitle, text in items:
            html.append(f'<p style="color:#8fb3ff; font-weight:bold;">{subtitle}</p>')
            html.append(f'<p>{text.replace(chr(10), "<br>")}</p>')
        self.content_text.setHtml("".join(html))

    def _open_manual(self) -> None:
        if not platform_compat.IS_WINDOWS:
            self._show_section(self.section_list.currentRow())
            return
        # ★docs/build_operation_manual_win.pyが生成するWord操作説明書を、
        # ビルド成果物(app_dir()/docs)から探して開く。凍結ビルドではdocs一式が
        # bundleに含まれるため、その場所も検索する。
        docx_name = _WIN_MANUAL_DOCX_EN if is_english() else _WIN_MANUAL_DOCX
        manual_path = platform_compat.app_dir() / "docs" / docx_name
        if not manual_path.exists():
            from widgets import error_dialog
            error_dialog(
                self, tr("操作説明書が見つかりません", "Operation Manual Not Found"),
                tr(f"{docx_name} が見つかりません。ヘルプ画面の内容をご確認ください。",
                   f"{docx_name} was not found. Please refer to the contents of the Help screen."))
            return
        try:
            os.startfile(str(manual_path))  # noqa: S606 (Windows専用API)
        except OSError as exc:
            from widgets import error_dialog
            error_dialog(self, tr("操作説明書を開けません", "Cannot Open Operation Manual"), str(exc))


def create(main_window) -> QtWidgets.QWidget:
    return ManualScreen(main_window)
