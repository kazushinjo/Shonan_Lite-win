"""モック8番カードに合わせた映像ソース画面。"""
from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import platform_compat
from widgets import SettingsSubScreen
from i18n import tr


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

        settings_row = QtWidgets.QHBoxLayout()
        settings_row.setSpacing(10)
        settings_row.addWidget(QtWidgets.QLabel(tr("解像度", "Resolution")))
        self.resolution = QtWidgets.QComboBox()
        self.resolution.addItems(("1920x1080", "1280x720", "640x480"))
        self.resolution.setCurrentText("1920x1080")
        settings_row.addWidget(self.resolution, 1)
        settings_row.addWidget(QtWidgets.QLabel(tr("フレームレート", "Frame rate")))
        self.framerate = QtWidgets.QComboBox()
        self.framerate.addItems(("30 fps", "25 fps", "15 fps"))
        self.framerate.setCurrentText("30 fps")
        settings_row.addWidget(self.framerate, 1)
        outer.addLayout(settings_row)

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

    def _select(self, source: str) -> None:
        settings = self.main_window.settings
        if source == "camera":
            settings.video_source = "camera"
            settings.use_color_bar_source = False
        elif source == "file":
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, tr("映像ファイルを選択", "Select Video File"), "",
                tr("映像ファイル (*.ts *.mp4 *.mkv *.mov *.avi);;すべてのファイル (*)",
                   "Video files (*.ts *.mp4 *.mkv *.mov *.avi);;All files (*)"))
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
