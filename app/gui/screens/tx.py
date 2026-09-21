"""Mac版を参考にしたPi5送信画面。送信開始まではTXプロセスを起動しない。

レイアウトはモック(shonan-16screens-mock-v4.png)の送信カードを踏襲: 左に映像
プレビュー、右に送信ステータス(周波数/シンボルレート/変調方式/FEC、及び
出力/パケット数/フレーム数)、下段に開始/停止ボタンを並べる。
配色は既存のダークテーマを維持する。
"""
from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import platform_compat
from widgets import SettingsSubScreen, dpi_scaled_pixmap, error_dialog
from i18n import tr


class TxScreen(SettingsSubScreen):
    def __init__(self, main_window):
        super().__init__("送信 / Transmit", lambda: main_window.navigate_to("home"))
        self.header_bar.hide()
        self.main_window = main_window
        self.controller = main_window.tx_controller
        self._camera_buffer = bytearray()
        self._camera_process = None
        self._tx_start_pending = False
        self._rx_restart_pending = False

        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.body_layout.setContentsMargins(10, 8, 10, 16)
        self.body_layout.setSpacing(6)

        # --- 上段: プレビュー + 送信ステータスカード ---
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(8)
        self.body_layout.addLayout(top_row, 1)

        self.preview_label = QtWidgets.QLabel()
        self.preview_label.setAlignment(QtCore.Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: black; border-radius: 10px; color: #999999;")
        # ★大きいプレビュー画像(例: iPadテストパターン1920x1080)をセットすると
        # QLabelのsizeHintがそのpixmap基準になり、右のステータスカードごと
        # 画面外へ押し出されて欠ける(実機800x480でスクロールバー無効のため
        # はみ出し分がそのまま消える)。ラベル自体のサイズはレイアウト側の
        # 割り当てに任せ、pixmapの内容でサイズ要求しないようにする。
        self.preview_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        top_row.addWidget(self.preview_label, 1)

        self.status_card = QtWidgets.QFrame()
        # ★Pi5実機(800x480)向けにfixedWidth(270)で調整されていたが、Windowsの
        # フォント描画では同じ日本語ラベル(「シンボルレート」等)がより横幅を
        # 取り、テキストが右端で切れる(rx.pyの左ペインと同じ問題)。
        # setMinimumWidthにして、実際のラベル幅に応じてカードが広がれるように
        # する(Pi5実機では元どおり270pxのまま収まる想定)。
        self.status_card.setMinimumWidth(270)
        self.status_card.setStyleSheet(
            "QFrame { background-color: #191d1f; border-radius: 12px; }"
            "QLabel { color: white; background: transparent; }"
        )
        top_row.addWidget(self.status_card)
        status_layout = QtWidgets.QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(14, 10, 14, 10)
        status_layout.setSpacing(8)

        status_header = QtWidgets.QHBoxLayout()
        self.status_dot = QtWidgets.QLabel()
        self.status_dot.setFixedSize(12, 12)
        status_header.addWidget(self.status_dot)
        self.status_label = QtWidgets.QLabel(tr("送信停止中", "TX Stopped"))
        self.status_label.setStyleSheet("font-size: 29px; font-weight: bold;")
        status_header.addWidget(self.status_label)
        status_header.addStretch(1)
        self.on_air_badge = QtWidgets.QLabel("ON AIR")
        self.on_air_badge.setStyleSheet(
            "background-color: #d02020; color: white; font-size: 29px;"
            " font-weight: bold; border-radius: 8px; padding: 2px 8px;")
        self.on_air_badge.hide()
        status_header.addWidget(self.on_air_badge)
        status_layout.addLayout(status_header)

        fields_grid = QtWidgets.QGridLayout()
        fields_grid.setHorizontalSpacing(16)
        fields_grid.setVerticalSpacing(6)
        fields_grid.setColumnStretch(0, 1)
        fields_grid.setColumnStretch(1, 1)
        self.freq_value = self._add_field(fields_grid, 0, 0, tr("周波数", "Freq."))
        self.symbol_value = self._add_field(fields_grid, 0, 1, tr("シンボルレート", "Sym. Rate"))
        self.modulation_value = self._add_field(fields_grid, 1, 0, tr("変調方式", "Mod."))
        self.fec_value = self._add_field(fields_grid, 1, 1, "FEC")
        status_layout.addLayout(fields_grid)

        divider = QtWidgets.QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #303538;")
        status_layout.addWidget(divider)

        stats_grid = QtWidgets.QGridLayout()
        stats_grid.setHorizontalSpacing(16)
        stats_grid.setVerticalSpacing(6)
        stats_grid.setColumnStretch(0, 1)
        stats_grid.setColumnStretch(1, 1)
        self.power_value = self._add_field(stats_grid, 0, 0, tr("出力減衰", "Atten."))
        self.packets_value = self._add_field(stats_grid, 0, 1, tr("パケット数", "Packets"))
        self.frames_value = self._add_field(stats_grid, 1, 0, tr("フレーム数", "Frames"))
        status_layout.addLayout(stats_grid)
        status_layout.addStretch(1)

        # --- 下段: ボタン行 ---
        self.panel = QtWidgets.QFrame()
        self.panel.setFixedHeight(68)
        self.panel.setStyleSheet(
            "QFrame { background: transparent; color: white; }"
            "QLabel { color: white; background: transparent; }"
        )
        self.body_layout.addWidget(self.panel)
        panel_layout = QtWidgets.QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(6)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.start_stop_btn = QtWidgets.QPushButton(tr("送信開始", "Start TX"))
        self.start_stop_btn.setMinimumSize(120, 40)
        self.start_stop_btn.clicked.connect(self._on_start_stop)
        button_row.addWidget(self.start_stop_btn)
        self.receive_screen_btn = self._secondary_button(tr("受信画面へ", "Go to RX"))
        self.receive_screen_btn.clicked.connect(self._on_receive_screen)
        button_row.addWidget(self.receive_screen_btn)
        self.settings_btn = self._secondary_button(tr("設定", "Settings"))
        self.settings_btn.clicked.connect(self._on_settings)
        button_row.addWidget(self.settings_btn)
        self.home_btn = self._secondary_button(tr("ホームへ戻る", "Back to Home"))
        self.home_btn.clicked.connect(self._on_home)
        button_row.addWidget(self.home_btn)
        button_row.addStretch(1)
        panel_layout.addLayout(button_row)

        self.controller.status_updated.connect(self._on_status)
        self.controller.preview_frame.connect(self._on_tx_preview_frame)
        self.controller.error.connect(self._on_error)
        self.controller.stopped.connect(self._on_stopped)
        self.controller.log_line.connect(self._on_log)

    @staticmethod
    def _add_field(grid: QtWidgets.QGridLayout, row: int, col: int, label: str) -> QtWidgets.QLabel:
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(1)
        caption = QtWidgets.QLabel(label)
        caption.setStyleSheet("color: #9aa0a6; font-size: 28px;")
        box.addWidget(caption)
        value = QtWidgets.QLabel("---")
        value.setStyleSheet("color: white; font-size: 29px; font-weight: bold;")
        box.addWidget(value)
        grid.addLayout(box, row, col)
        return value

    @staticmethod
    def _secondary_button(text: str) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setMinimumSize(100, 40)
        button.setStyleSheet(
            "QPushButton { background-color: #303538; color: white; border: none;"
            " border-radius: 8px; padding: 4px 10px; font-size: 29px; font-weight: bold; }"
            "QPushButton:pressed { background-color: #222222; }"
        )
        return button

    def on_show(self) -> None:
        settings = self.main_window.settings
        lo_hz = settings.effective_lo_hz()
        self.freq_value.setText(f"{lo_hz / 1000:.0f} kHz" if lo_hz else tr("未設定", "Not Set"))
        self.symbol_value.setText(f"{settings.symbol_rate_msps * 1000:.0f} kS/s")
        self.modulation_value.setText(settings.modulation_scheme)
        self.fec_value.setText(settings.fec_rate)
        self.power_value.setText(f"{settings.tx_power_db:.0f} dB")
        self.packets_value.setText("0")
        self.frames_value.setText("0")
        self.update_navigation_buttons()
        self._sync_button_state()
        if self.controller.is_running() and not settings.use_color_bar_source:
            self.preview_label.setText(tr("送信中\n選択した映像ソースを送信に使用中",
                                            "Transmitting\nUsing the selected video source"))
        else:
            # 送信画面表示中にカメラを先取りすると、送信開始時のffmpegと
            # /dev/video0が競合する。送信停止後だけプレビューを再開する。
            self.preview_label.setText(tr("送信開始前", "Before TX start"))

    def _start_preview(self) -> None:
        self._stop_preview()
        settings = self.main_window.settings
        if settings.use_color_bar_source or settings.video_source == "colorbar":
            self.preview_label.setPixmap(self._colorbar_pixmap())
            return
        if settings.video_source == "file" and settings.video_file_path:
            pixmap = QtGui.QPixmap(settings.video_file_path)
            if not pixmap.isNull():
                self.preview_label.setPixmap(dpi_scaled_pixmap(pixmap, self.preview_label))
            else:
                self.preview_label.setText(tr("ファイル映像を送信に使用中", "Using file video for TX"))
            return
        device = self.main_window.settings.camera_device
        process = QtCore.QProcess(self)
        process.readyReadStandardOutput.connect(self._read_camera_frame)
        process.errorOccurred.connect(self._on_preview_error)
        camera_args = platform_compat.camera_input_args(device, video_size="640x480")
        process.start("ffmpeg", ["-hide_banner", "-loglevel", "error"] + camera_args +
                                  ["-f", "rawvideo", "-pix_fmt", "rgb24", "-r", "10", "-"])
        self._camera_process = process

    def _on_preview_error(self, _err) -> None:
        # 送信開始時に停止した旧プレビューFFmpegから、遅れてエラー通知が
        # 届くことがある。送信中は送信用FFmpegから分岐された映像を表示するため、
        # その通知でプレビューをエラーメッセージに上書きしない。
        if self.controller.is_running():
            return
        if self.main_window.settings.use_color_bar_source:
            self.preview_label.setPixmap(self._colorbar_pixmap())
        else:
            self.preview_label.setText(tr(
                "カメラ映像を取得できません\n送信中はC920を送信処理が使用します",
                "Cannot get camera video\nThe camera is in use by TX while transmitting"))

    def _stop_preview(self) -> None:
        if self._camera_process is not None:
            process = self._camera_process
            process.terminate()
            if not process.waitForFinished(1000):
                process.kill()
                process.waitForFinished(1000)
            process.deleteLater()
            self._camera_process = None
        self._camera_buffer.clear()

        # Qtの終了通知より先に次のTX起動が走った場合に備え、対象デバイスを
        # 使用中の残存ffmpegだけを終了させる。別デバイスやRXプロセスには触れない。
        # ★Windowsにはfuser相当の汎用コマンドが無いが、上でQProcessを確実に
        # terminate/killしているため追加処理は不要(platform_compat参照)。
        platform_compat.release_camera_device(self.main_window.settings.camera_device)

    def _read_camera_frame(self) -> None:
        if self._camera_process is None:
            return
        self._camera_buffer.extend(bytes(self._camera_process.readAllStandardOutput()))
        frame_size = 640 * 480 * 3
        if len(self._camera_buffer) < frame_size:
            return
        frame = bytes(self._camera_buffer[:frame_size])
        del self._camera_buffer[:frame_size]
        image = QtGui.QImage(frame, 640, 480, 640 * 3, QtGui.QImage.Format_RGB888).copy()
        self.preview_label.setPixmap(dpi_scaled_pixmap(QtGui.QPixmap.fromImage(image), self.preview_label))

    def _on_tx_preview_frame(self, frame: bytes, width: int, height: int) -> None:
        """送信FFmpegから分岐されたC920映像を表示する。"""
        image = QtGui.QImage(frame, width, height, width * 3,
                             QtGui.QImage.Format_RGB888).copy()
        self.preview_label.setPixmap(dpi_scaled_pixmap(QtGui.QPixmap.fromImage(image), self.preview_label))

    def _colorbar_pixmap(self) -> QtGui.QPixmap:
        ipad_pattern = platform_compat.app_dir() / "assets" / "test_pattern_ipad.png"
        pixmap = QtGui.QPixmap(str(ipad_pattern))
        if not pixmap.isNull():
            return dpi_scaled_pixmap(pixmap, self.preview_label)

        # 画像が未配備の開発環境用フォールバック。
        image = QtGui.QImage(800, 480, QtGui.QImage.Format_RGB32)
        image.fill(QtCore.Qt.black)
        painter = QtGui.QPainter(image)
        colors = [QtCore.Qt.white, QtCore.Qt.yellow, QtCore.Qt.cyan, QtCore.Qt.green,
                  QtCore.Qt.magenta, QtCore.Qt.red, QtCore.Qt.blue]
        width = image.width() // len(colors)
        for index, color in enumerate(colors):
            painter.fillRect(index * width, 0, width, 330, color)
        grays = [QtCore.Qt.black, QtCore.Qt.darkGray, QtCore.Qt.gray, QtCore.Qt.lightGray, QtCore.Qt.white]
        gray_width = image.width() // len(grays)
        for index, color in enumerate(grays):
            painter.fillRect(index * gray_width, 330, gray_width, 150, color)
        painter.end()
        return QtGui.QPixmap.fromImage(image)

    def update_navigation_buttons(self) -> None:
        self.receive_screen_btn.setVisible(self.main_window.settings.use_on_device_demod)

    def _sync_button_state(self) -> None:
        running = self.controller.is_running()
        self.status_dot.setStyleSheet(
            f"background-color: {'#20c020' if running else '#5a5a5a'}; border-radius: 6px;")
        self.on_air_badge.setVisible(running)
        if running:
            self.status_label.setText(tr("送信中", "Transmitting"))
            self.start_stop_btn.setText(tr("送信停止", "Stop TX"))
            self.start_stop_btn.setStyleSheet(
                "QPushButton { background-color: #d02020; color: white; border: none;"
                " border-radius: 8px; padding: 4px 10px; font-size: 29px; font-weight: bold; }"
                "QPushButton:pressed { background-color: #901010; }")
        else:
            self.status_label.setText(tr("送信停止中", "TX Stopped"))
            self.start_stop_btn.setText(tr("送信開始", "Start TX"))
            self.start_stop_btn.setStyleSheet(
                "QPushButton { background-color: #1677ff; color: white; border: none;"
                " border-radius: 8px; padding: 4px 10px; font-size: 29px; font-weight: bold; }"
                "QPushButton:pressed { background-color: #0b55c7; }")

    def _on_start_stop(self) -> None:
        if self.controller.is_running():
            self.controller.stop()
        else:
            settings = self.main_window.settings
            # ★オンデバイス復調がOFFの場合、TX/RXは同一Pluto+を排他利用する前提の
            # ためTXとRXの同時起動を許可しない(ONの場合のみ、上のsimultaneous_tx_rx_test
            # 分岐でRXを一旦止めてから同時運用する)。
            if not settings.use_on_device_demod and self.main_window.rx_controller.is_running():
                error_dialog(
                    self, tr("送信を開始できません", "Cannot Start TX"),
                    tr("受信が実行中です。オンデバイス復調がOFFの場合、送信と受信は"
                       "同時に実行できません。先に受信を停止してください。",
                       "RX is running. With on-device demodulation OFF, TX and RX cannot "
                       "run at the same time. Stop RX first."))
                return
            if self.main_window.settings.simultaneous_tx_rx_test and self.main_window.rx_controller.is_running():
                self._rx_restart_pending = True
                self.main_window.rx_controller.stop()
                self.start_stop_btn.setEnabled(False)
            # 送信ffmpegがC920を開けるよう、画面プレビューのffmpegを先に止める。
            # 同じ/dev/video0を2プロセスで開くと送信側が「Device or resource busy」
            # になり、ビットレートが0のまま開始失敗する。
            self._stop_preview()
            self._tx_start_pending = True
            # QProcess.kill()は終了通知がイベントループ経由で届くため、
            # 直後にTXを起動するとカメラデバイスがまだ解放されていないことがある。
            QtCore.QTimer.singleShot(300, self._start_tx_after_preview_stop)
        self._sync_button_state()

    def _start_tx_after_preview_stop(self) -> None:
        if not self._tx_start_pending:
            return
        if self._rx_restart_pending and self.main_window.rx_controller.is_running():
            QtCore.QTimer.singleShot(100, self._start_tx_after_preview_stop)
            return
        self._tx_start_pending = False
        if not self.controller.is_running():
            self.controller.start(self.main_window.settings)
        if self._rx_restart_pending:
            self._rx_restart_pending = False
            QtCore.QTimer.singleShot(300, self._restart_rx_after_tx_start)

    def _restart_rx_after_tx_start(self) -> None:
        if self.main_window.settings.simultaneous_tx_rx_test and not self.main_window.rx_controller.is_running():
            self.main_window.rx_controller.start(self.main_window.settings)
        self.start_stop_btn.setEnabled(True)
        self._sync_button_state()

    def _on_receive_screen(self) -> None:
        self.main_window.navigate_to("rx")

    def _on_settings(self) -> None:
        self.main_window.navigate_to("settings")

    def _on_home(self) -> None:
        self.main_window.navigate_to("home")

    def _on_status(self, status: dict) -> None:
        try:
            packets = int(Path("/sys/class/net/eth0/statistics/tx_packets").read_text())
        except (OSError, ValueError):
            packets = status.get("packets", 0)
        self._sync_button_state()
        self.packets_value.setText(str(packets))
        self.frames_value.setText(str(status.get("frames", 0)))

    def _on_error(self, message: str) -> None:
        error_dialog(self, tr("送信エラー", "TX Error"), message)
        if self.isVisible():
            self._start_preview()
        self._sync_button_state()

    def _on_stopped(self) -> None:
        self._sync_button_state()
        self.packets_value.setText("0")
        self.frames_value.setText("0")
        if self.isVisible():
            self._start_preview()

    def _on_log(self, _line: str) -> None:
        pass

    def hideEvent(self, event) -> None:
        self._stop_preview()
        super().hideEvent(event)


def create(main_window) -> QtWidgets.QWidget:
    return TxScreen(main_window)
