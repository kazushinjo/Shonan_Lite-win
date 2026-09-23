"""モック8番カードに合わせた映像ソース画面。"""
from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import platform_compat
from widgets import SettingsSubScreen
from i18n import tr

# オーバーレイ文字サイズの選択肢(px、1920x1080の送信映像上での大きさ)。
_CALLSIGN_FONT_SIZES = (36, 48, 68, 96, 128, 192, 256)
_NOTE_FONT_SIZES = (16, 24, 32, 48, 64)
# コールサイン・備考の文字色の選択肢(表示名, "#RRGGBB")。
_OVERLAY_COLORS = (
    (("白", "White"), "#FFFFFF"),
    (("黄", "Yellow"), "#FFFF00"),
    (("赤", "Red"), "#FF3030"),
    (("緑", "Green"), "#00E000"),
    (("青", "Blue"), "#3080FF"),
    (("水色", "Cyan"), "#00FFFF"),
    (("橙", "Orange"), "#FF9900"),
    (("黒", "Black"), "#000000"),
)


class VideoSourceScreen(SettingsSubScreen):
    def __init__(self, main_window):
        super().__init__("映像ソース / Video Source", lambda: main_window.navigate_to("home"))
        self.main_window = main_window
        self._camera_process = None
        self._camera_buffer = bytearray()
        self.body_layout.setContentsMargins(10, 8, 10, 10)
        self.body_layout.setSpacing(6)

        card = QtWidgets.QFrame()
        card.setStyleSheet(
            "QFrame { background: #101416; border: 1px solid #34434b; border-radius: 14px; }"
            "QLabel { color: #eeeeee; background: transparent; font-size: 28px; }"
            "QComboBox { background: #191d1f; color: #eeeeee; border: 1px solid #46545b;"
            " border-radius: 6px; padding: 5px; font-size: 28px; }"
            "QLineEdit { background: #191d1f; color: #eeeeee; border: 1px solid #46545b;"
            " border-radius: 6px; padding: 4px 8px; font-size: 28px; }"
        )
        self.body_layout.addWidget(card, 1)
        outer = QtWidgets.QVBoxLayout(card)
        outer.setContentsMargins(12, 10, 12, 8)
        outer.setSpacing(6)

        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(10)
        outer.addLayout(columns, 1)

        left = QtWidgets.QFrame()
        left.setStyleSheet("QFrame { background: #191d1f; border: 1px solid #34434b; border-radius: 10px; }")
        left_layout = QtWidgets.QVBoxLayout(left)
        left_layout.setContentsMargins(10, 8, 10, 8)
        left_layout.setSpacing(2)
        title = QtWidgets.QLabel(tr("映像ソース選択", "Video Source Selection"))
        title.setStyleSheet("font-size: 29px; font-weight: bold; color: #54bce0;")
        left_layout.addWidget(title)

        self._group = QtWidgets.QButtonGroup(self)
        self._source_buttons = {}
        cameras = platform_compat.list_camera_devices() or [platform_compat.default_camera_device() or "/dev/video0"]
        settings = main_window.settings
        current_source = settings.video_source
        if settings.use_color_bar_source:
            current_source = "colorbar"
        self._add_source(left_layout, tr("カメラ", "Camera"), "camera", enabled=True,
                         checked=(current_source == "camera"))
        self._add_source(left_layout, tr("ファイル選択", "Select File"), "file", enabled=True,
                         checked=(current_source == "file"))
        self._add_source(left_layout, tr("テストパターン", "Test Pattern"), "colorbar",
                         enabled=True, checked=(current_source == "colorbar"))
        left_layout.addStretch(1)
        columns.addWidget(left, 1)

        right = QtWidgets.QFrame()
        right.setStyleSheet("QFrame { background: #191d1f; border: 1px solid #34434b; border-radius: 10px; }")
        right_layout = QtWidgets.QVBoxLayout(right)
        right_layout.setContentsMargins(10, 8, 10, 8)
        right_layout.setSpacing(4)
        preview_title = QtWidgets.QLabel(tr("プレビュー", "Preview"))
        preview_title.setStyleSheet("font-size: 29px; font-weight: bold; color: #54bce0;")
        right_layout.addWidget(preview_title)
        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setScaledContents(False)
        self.preview.setMinimumSize(300, 150)
        self.preview.setStyleSheet("background: #050607; border: 1px solid #46545b; border-radius: 6px; color: #aab7bd;")
        right_layout.addWidget(self.preview, 1)
        columns.addWidget(right, 2)

        # 映像へ焼き込むコールサイン・備考(カメラ・画像ファイルに適用、テストパターンには
        # 元々コールサインが描かれているため適用しない)。送信解像度はフルHD(1920x1080)固定のため、
        # 解像度・フレームレートの選択欄は置かない。
        overlay_row = QtWidgets.QHBoxLayout()
        overlay_row.setSpacing(10)
        overlay_row.addWidget(QtWidgets.QLabel(tr("コールサイン", "Callsign")))
        self.overlay_callsign_edit = QtWidgets.QLineEdit()
        self.overlay_callsign_edit.setMinimumHeight(48)
        self.overlay_callsign_edit.setPlaceholderText(tr("例: JA1XXX", "e.g. JA1XXX"))
        self.overlay_callsign_edit.setText(settings.overlay_callsign)
        self.overlay_callsign_edit.editingFinished.connect(self._save_overlay_callsign)
        overlay_row.addWidget(self.overlay_callsign_edit, 1)
        self.overlay_callsign_size = self._font_size_combo(_CALLSIGN_FONT_SIZES)
        self.overlay_callsign_size.activated.connect(self._save_overlay_callsign_size)
        overlay_row.addWidget(self.overlay_callsign_size)
        self.overlay_callsign_color = self._color_combo(tr("コールサインの文字色", "Callsign color"))
        self.overlay_callsign_color.activated.connect(self._save_overlay_callsign_color)
        overlay_row.addWidget(self.overlay_callsign_color)
        overlay_row.addWidget(QtWidgets.QLabel(tr("備考", "Note")))
        self.overlay_note_edit = QtWidgets.QLineEdit()
        self.overlay_note_edit.setMinimumHeight(48)
        self.overlay_note_edit.setPlaceholderText(tr("任意", "Optional"))
        self.overlay_note_edit.setText(settings.overlay_note)
        self.overlay_note_edit.editingFinished.connect(self._save_overlay_note)
        overlay_row.addWidget(self.overlay_note_edit, 2)
        self.overlay_note_size = self._font_size_combo(_NOTE_FONT_SIZES)
        self.overlay_note_size.activated.connect(self._save_overlay_note_size)
        overlay_row.addWidget(self.overlay_note_size)
        self.overlay_note_color = self._color_combo(tr("備考の文字色", "Note color"))
        self.overlay_note_color.activated.connect(self._save_overlay_note_color)
        overlay_row.addWidget(self.overlay_note_color)
        self._load_overlay_sizes()
        outer.addLayout(overlay_row)

        self._camera_device = cameras[0]
        # ★settings.camera_device(TX開始時にbackend.pyが実際に使う値)へも書き戻す。
        # これを怠ると、この画面のプレビュー用ローカル変数self._camera_deviceだけが
        # 検出済みデバイス名を持ち、settings側は既定値(Windowsは""のプレースホルダ)の
        # ままになり、送信開始時にffmpegへ空のデバイス名("-i video=")が渡って
        # "Malformed dshow input string"で即失敗する不具合があった。
        if settings.camera_device != self._camera_device:
            settings.camera_device = self._camera_device
            self.main_window.save_settings()
        # ★ここで_update_preview()を呼ぶと(video_source=="camera"のとき)
        # _start_camera_preview()が無条件に実行される。main.py _build_screens()は
        # 全画面のウィジェットを起動時に一括構築するため、ユーザーが映像ソース画面を
        # 一度も開いていなくても、アプリ起動と同時にこのプレビュー用ffmpegがバック
        # グラウンドで動き続けてしまい、後から送信画面で送信開始してもTX用ffmpegが
        # 同じDirectShowカメラを取得できず"Error during demuxing: I/O error"で
        # 即失敗する不具合があった(実機で確認済み: on_hide()は一度も表示していない
        # 画面には呼ばれないため、このプレビューは誰にも止められないまま残り続ける)。
        # 実際の表示時はon_show()が_update_preview()を呼ぶので、ここでは呼ばない。
        self.preview.setText(tr("カメラ (USB)\nプレビュー待機中", "Camera (USB)\nWaiting for preview"))

    def on_show(self) -> None:
        # プリセット読込等で設定が変わっている場合に備え、表示のたびに入力欄を読み直す。
        settings = self.main_window.settings
        self.overlay_callsign_edit.setText(settings.overlay_callsign)
        self.overlay_note_edit.setText(settings.overlay_note)
        self._load_overlay_sizes()
        # レイアウト確定後の実サイズでプレビュー枠へ描画する。
        self._update_preview()

    def on_hide(self) -> None:
        self._stop_camera_preview()

    def _add_source(self, layout, label: str, source: str, *, enabled: bool,
                    checked: bool = False) -> None:
        radio = QtWidgets.QPushButton(label)
        radio.setCheckable(True)
        radio.setMinimumHeight(30)
        radio.setChecked(checked)
        radio.setEnabled(enabled)
        radio.setStyleSheet(
            "QPushButton { background-color: #303538; color: white; border: none;"
            " border-radius: 8px; padding: 4px 10px; text-align: left;"
            " font-size: 29px; font-weight: bold; }"
            "QPushButton:checked { background-color: #1677ff; }"
            "QPushButton:pressed { background-color: #222222; }"
            "QPushButton:disabled { color: #777777; background-color: #252a2d; }"
        )
        if enabled:
            radio.toggled.connect(lambda active, s=source: active and self._select(s))
        self._group.addButton(radio)
        self._source_buttons[source] = radio
        layout.addWidget(radio)

    @staticmethod
    def _font_size_combo(sizes) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setMinimumHeight(48)
        combo.setToolTip(tr("文字サイズ", "Font size"))
        for size in sizes:
            combo.addItem(f"{size}px", size)
        return combo

    @staticmethod
    def _select_font_size(combo: QtWidgets.QComboBox, size: int) -> None:
        index = combo.findData(size)
        if index < 0:
            # 設定ファイルに選択肢外の値がある場合もその値を表示・維持する。
            combo.addItem(f"{size}px", size)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    def _load_overlay_sizes(self) -> None:
        settings = self.main_window.settings
        self._select_font_size(self.overlay_callsign_size, settings.overlay_callsign_font_size)
        self._select_font_size(self.overlay_note_size, settings.overlay_note_font_size)
        self._select_color(self.overlay_callsign_color, settings.overlay_callsign_color)
        self._select_color(self.overlay_note_color, settings.overlay_note_color)

    def _select_color(self, combo: QtWidgets.QComboBox, color: str) -> None:
        color = color.upper()
        index = combo.findData(color)
        if index < 0:
            # 設定ファイルに選択肢外の色がある場合もその色を表示・維持する。
            combo.addItem(self._color_icon(color), color, color)
            index = combo.count() - 1
        combo.setCurrentIndex(index)

    @staticmethod
    def _color_icon(color: str) -> QtGui.QIcon:
        pixmap = QtGui.QPixmap(28, 28)
        pixmap.fill(QtGui.QColor(color))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor("#888888"))
        painter.drawRect(0, 0, 27, 27)
        painter.end()
        return QtGui.QIcon(pixmap)

    def _color_combo(self, tooltip: str) -> QtWidgets.QComboBox:
        combo = QtWidgets.QComboBox()
        combo.setMinimumHeight(48)
        combo.setIconSize(QtCore.QSize(28, 28))
        combo.setToolTip(tooltip)
        for (ja, en), color in _OVERLAY_COLORS:
            combo.addItem(self._color_icon(color), tr(ja, en), color)
        return combo

    def _save_overlay_callsign_color(self, _index: int) -> None:
        self.main_window.settings.overlay_callsign_color = str(self.overlay_callsign_color.currentData())
        self.main_window.save_settings()

    def _save_overlay_note_color(self, _index: int) -> None:
        self.main_window.settings.overlay_note_color = str(self.overlay_note_color.currentData())
        self.main_window.save_settings()

    def _save_overlay_callsign_size(self, _index: int) -> None:
        self.main_window.settings.overlay_callsign_font_size = int(self.overlay_callsign_size.currentData())
        self.main_window.save_settings()

    def _save_overlay_note_size(self, _index: int) -> None:
        self.main_window.settings.overlay_note_font_size = int(self.overlay_note_size.currentData())
        self.main_window.save_settings()

    def _save_overlay_callsign(self) -> None:
        self.main_window.settings.overlay_callsign = self.overlay_callsign_edit.text().strip()
        self.main_window.save_settings()

    def _save_overlay_note(self) -> None:
        self.main_window.settings.overlay_note = self.overlay_note_edit.text().strip()
        self.main_window.save_settings()

    def _select(self, source: str) -> None:
        settings = self.main_window.settings
        if source == "camera":
            settings.video_source = "camera"
            settings.use_color_bar_source = False
        elif source == "file":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, tr("画像ファイルを選択", "Select Image File"), "",
                tr("画像ファイル (*.png *.jpg *.jpeg *.bmp)",
                   "Image files (*.png *.jpg *.jpeg *.bmp)"))
            if not path:
                file_button = self._source_buttons["file"]
                file_button.blockSignals(True)
                file_button.setChecked(False)
                file_button.blockSignals(False)
                previous = "colorbar" if settings.use_color_bar_source else settings.video_source
                previous_button = self._source_buttons.get(previous)
                if previous_button is not None:
                    previous_button.blockSignals(True)
                    previous_button.setChecked(True)
                    previous_button.blockSignals(False)
                return
            settings.video_source = "file"
            settings.video_file_path = path
            settings.use_color_bar_source = False
        elif source == "colorbar":
            settings.video_source = "colorbar"
            settings.use_color_bar_source = True
        else:
            return
        self.main_window.save_settings()
        self._update_preview()

    def _update_preview(self) -> None:
        settings = self.main_window.settings
        if settings.use_color_bar_source or settings.video_source == "colorbar":
            self._stop_camera_preview()
            image = platform_compat.app_dir() / "assets" / "test_pattern_ipad.png"
            pixmap = QtGui.QPixmap(str(image))
            self.preview.setPixmap(self._scaled_preview(pixmap))
        elif settings.video_source == "file" and settings.video_file_path:
            self._stop_camera_preview()
            pixmap = QtGui.QPixmap(settings.video_file_path)
            if pixmap.isNull():
                self.preview.setPixmap(QtGui.QPixmap())
                self.preview.setText(tr(f"ファイル選択済み\n{Path(settings.video_file_path).name}",
                              f"File selected\n{Path(settings.video_file_path).name}"))
            else:
                self.preview.setPixmap(self._scaled_preview(pixmap))
        else:
            self._start_camera_preview()
            self.preview.setPixmap(QtGui.QPixmap())
            self.preview.setText(tr("カメラ (USB)\nプレビュー待機中", "Camera (USB)\nWaiting for preview"))

    def _start_camera_preview(self) -> None:
        if self._camera_process is not None:
            return
        self._camera_buffer.clear()
        process = QtCore.QProcess(self)
        process.readyReadStandardOutput.connect(self._read_camera_frame)
        process.errorOccurred.connect(self._camera_preview_error)
        camera_args = platform_compat.camera_input_args(self._camera_device, video_size="640x480")
        process.start("ffmpeg", ["-hide_banner", "-loglevel", "error"] + camera_args +
                                  ["-f", "rawvideo", "-pix_fmt", "rgb24", "-r", "10", "-"])
        self._camera_process = process

    def _stop_camera_preview(self) -> None:
        if self._camera_process is not None:
            self._camera_process.kill()
            self._camera_process.deleteLater()
            self._camera_process = None
        self._camera_buffer.clear()

    def _read_camera_frame(self) -> None:
        if self._camera_process is None:
            return
        self._camera_buffer.extend(bytes(self._camera_process.readAllStandardOutput()))
        frame_size = 640 * 480 * 3
        while len(self._camera_buffer) >= frame_size:
            frame = bytes(self._camera_buffer[:frame_size])
            del self._camera_buffer[:frame_size]
            image = QtGui.QImage(frame, 640, 480, 640 * 3,
                                 QtGui.QImage.Format_RGB888).copy()
            self.preview.setPixmap(self._scaled_preview(QtGui.QPixmap.fromImage(image)))

    def _camera_preview_error(self, _error) -> None:
        if self.main_window.settings.video_source == "camera":
            self.preview.setText(tr("カメラ映像を取得できません", "Cannot get camera video"))

    def _scaled_preview(self, pixmap: QtGui.QPixmap) -> QtGui.QPixmap:
        if pixmap.isNull():
            return pixmap
        return pixmap.scaled(
            self.preview.size(), QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "preview"):
            self._update_preview()

    def closeEvent(self, event) -> None:
        self._stop_camera_preview()
        super().closeEvent(event)


def create(main_window) -> QtWidgets.QWidget:
    return VideoSourceScreen(main_window)
