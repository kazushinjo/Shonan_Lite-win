"""Mac版を参考にしたPi5受信画面。既存のGNU Radio RX処理を操作する。

レイアウトはモック(shonan-16screens-mock-v4.png)の受信カードを踏襲: 左に受信
ステータス(周波数/シンボルレート/変調方式/FEC、及び状態/ビットレート/パケット/
エラー)、右に受信映像、下段に音量・開始/停止ボタンを並べる。
配色は既存のダークテーマを維持する。受信映像タップでの全画面切り替えは
従来どおり維持する。
"""
from __future__ import annotations

import time

from PyQt5 import QtCore, QtGui, QtWidgets

from widgets import SettingsSubScreen, dpi_scaled_pixmap, error_dialog
from i18n import tr


class RxScreen(SettingsSubScreen):
    def __init__(self, main_window):
        super().__init__("受信 / Receive", lambda: main_window.navigate_to("home"))
        self.header_bar.hide()
        self.main_window = main_window
        self.controller = main_window.rx_controller
        self._last_rate_packets = None
        self._last_rate_time = None
        self._bitrate_mbps = 0.0
        self._video_fullscreen = False
        # Android/iPad版のRFループバック同時試験に相当。設定でONの場合、受信開始と
        # 同時に同じPluto+へ実際のカメラ映像を送出するTXも自動的に開始し、受信停止
        # (エラーによる停止を含む)と同時にそのTXも停止する。
        self._tx_started_alongside_rx = False

        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.body_layout.setContentsMargins(10, 8, 10, 32)
        self.body_layout.setSpacing(6)

        # --- 上段: 受信ステータスカード + 受信映像 ---
        top_row = QtWidgets.QHBoxLayout()
        top_row.setSpacing(8)
        self.body_layout.addLayout(top_row, 1)

        self.status_card = QtWidgets.QFrame()
        # ★Pi5実機(800x480)向けにfixedWidth(270)で調整されていたが、Windowsの
        # フォント描画では同じ280x29pxの日本語ラベル(「シンボルレート」等)が
        # より横幅を取り、テキストが右端で切れる。setMinimumWidthにして、
        # 実際のラベル幅に応じてカードが広がれるようにする(Pi5実機では
        # 元どおり270pxのまま収まる想定)。
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
        self.status_label = QtWidgets.QLabel(tr("受信停止中", "RX Stopped"))
        self.status_label.setStyleSheet("font-size: 29px; font-weight: bold;")
        status_header.addWidget(self.status_label)
        status_header.addStretch(1)
        self.lock_badge = QtWidgets.QLabel("LOCK")
        self.lock_badge.setStyleSheet(
            "background-color: #20a040; color: white; font-size: 29px;"
            " font-weight: bold; border-radius: 8px; padding: 2px 8px;")
        self.lock_badge.hide()
        status_header.addWidget(self.lock_badge)
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
        self.state_value = self._add_field(stats_grid, 0, 0, tr("状態", "State"))
        self.bitrate_value = self._add_field(stats_grid, 0, 1, tr("ビットレート", "Bitrate"))
        self.packets_value = self._add_field(stats_grid, 1, 0, tr("パケット/秒", "Pkts/s"))
        self.errors_value = self._add_field(stats_grid, 1, 1, tr("エラー", "Errors"))
        status_layout.addLayout(stats_grid)
        status_layout.addStretch(1)

        self.video_label = QtWidgets.QLabel()
        self.video_label.setAlignment(QtCore.Qt.AlignCenter)
        self.video_label.setStyleSheet("background-color: black; border-radius: 10px;")
        # ★TX画面と同じ理由: 映像pixmapのサイズでQLabelのsizeHintが肥大化し、
        # 左のステータスカードごと画面外へ押し出されないようにする。
        self.video_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.video_label.mousePressEvent = self._on_video_tap
        top_row.addWidget(self.video_label, 1)

        # --- 下段: 音量 + ボタン行 ---
        self.panel = QtWidgets.QFrame()
        self.panel.setFixedHeight(116)
        self.panel.setStyleSheet(
            "QFrame { background: transparent; color: white; }"
            "QLabel { color: white; background: transparent; }"
            "QSlider::groove:horizontal { height: 8px; background: #303437; border-radius: 4px; }"
            "QSlider::handle:horizontal { width: 20px; margin: -6px 0;"
            " background: #dddddd; border-radius: 10px; }"
            "QSlider::sub-page:horizontal { background: #1677ff; border-radius: 4px; }"
        )
        self.body_layout.addWidget(self.panel)
        panel_layout = QtWidgets.QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(6)

        volume_row = QtWidgets.QHBoxLayout()
        volume_label = QtWidgets.QLabel(tr("音量", "Volume"))
        volume_label.setFixedWidth(60)
        volume_row.addWidget(volume_label)
        self.volume_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_row.addWidget(self.volume_slider, 1)
        panel_layout.addLayout(volume_row)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch(1)
        self.start_stop_btn = QtWidgets.QPushButton(tr("受信開始", "Start RX"))
        self.start_stop_btn.setMinimumSize(120, 40)
        self.start_stop_btn.clicked.connect(self._on_start_stop)
        button_row.addWidget(self.start_stop_btn)
        self.tx_screen_btn = self._secondary_button(tr("送信画面へ", "Go to TX"))
        self.tx_screen_btn.clicked.connect(lambda: self.main_window.navigate_to("tx"))
        button_row.addWidget(self.tx_screen_btn)
        self.settings_btn = self._secondary_button(tr("設定", "Settings"))
        self.settings_btn.clicked.connect(lambda: self.main_window.navigate_to("settings"))
        button_row.addWidget(self.settings_btn)
        self.home_btn = self._secondary_button(tr("ホームへ戻る", "Back to Home"))
        self.home_btn.clicked.connect(lambda: self.main_window.navigate_to("home"))
        button_row.addWidget(self.home_btn)
        button_row.addStretch(1)
        panel_layout.addLayout(button_row)

        self.controller.status_updated.connect(self._on_status)
        self.controller.error.connect(self._on_error)
        self.controller.stopped.connect(self._on_stopped)
        self.controller.video_frame.connect(self._on_video_frame)

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

    def update_navigation_buttons(self) -> None:
        # ★オンデバイス復調がOFFの場合、TX/RXは同一Pluto+を排他利用する前提のため
        # 送信画面への遷移ボタンは不要(tx.py側の受信画面への遷移ボタンと対になる)。
        self.tx_screen_btn.setVisible(self.main_window.settings.use_on_device_demod)

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
        # 画面を再表示したとき、前回のスクロール位置が残って上部の
        # ステータスカードが隠れないよう、必ず先頭へ戻す。
        self.scroll_area.verticalScrollBar().setValue(0)
        settings = self.main_window.settings
        lo_hz = settings.effective_lo_hz()
        self.freq_value.setText(f"{lo_hz / 1000:.0f} kHz" if lo_hz else tr("未設定", "Not Set"))
        self.symbol_value.setText(f"{settings.symbol_rate_msps * 1000:.0f} kS/s")
        self.modulation_value.setText(settings.modulation_scheme)
        self.fec_value.setText(settings.fec_rate)
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(round(settings.rx_volume * 100))
        self.volume_slider.blockSignals(False)
        self.update_navigation_buttons()
        self._sync_button_state()
        self._set_video_fullscreen(False)
        self._last_rate_packets = None
        self._last_rate_time = None
        self._bitrate_mbps = 0.0
        self._set_stats(False, 0, 0)

    def _on_volume_changed(self, value: int) -> None:
        self.main_window.settings.rx_volume = value / 100.0
        self.main_window.save_settings()
        self.controller.set_volume(value)

    def _sync_button_state(self, locked: bool = False) -> None:
        running = self.controller.is_running()
        self.status_dot.setStyleSheet(
            f"background-color: {'#20c020' if running else '#5a5a5a'}; border-radius: 6px;")
        self.lock_badge.setVisible(locked)
        if running:
            self.status_label.setText(tr("受信中", "Receiving"))
            self.start_stop_btn.setText(tr("受信停止", "Stop RX"))
            self.start_stop_btn.setStyleSheet(
                "QPushButton { background-color: #d02020; color: white; border: none;"
                " border-radius: 8px; padding: 4px 10px; font-size: 29px; font-weight: bold; }"
                "QPushButton:pressed { background-color: #901010; }")
        else:
            self.status_label.setText(tr("受信停止中", "RX Stopped"))
            self.start_stop_btn.setText(tr("受信開始", "Start RX"))
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
            # ためTXとRXの同時起動を許可しない(tx.py側の同時起動制限と対になる)。
            if not settings.use_on_device_demod and self.main_window.tx_controller.is_running():
                error_dialog(
                    self, tr("受信を開始できません", "Cannot Start RX"),
                    tr("送信が実行中です。オンデバイス復調がOFFの場合、送信と受信は"
                       "同時に実行できません。先に送信を停止してください。",
                       "TX is running. With on-device demodulation OFF, TX and RX cannot "
                       "run at the same time. Stop TX first."))
                return
            self.controller.start(settings)
        self._sync_button_state()

    def _on_status(self, status: dict) -> None:
        locked = status["locked"]
        packets = status.get("packets", 0)
        now = time.monotonic()
        if self._last_rate_packets is not None and self._last_rate_time is not None:
            elapsed = now - self._last_rate_time
            packet_delta = packets - self._last_rate_packets
            if elapsed > 0 and packet_delta >= 0:
                # MPEG-TSは188バイト/パケット。直近ステータス間の実測値。
                self._bitrate_mbps = packet_delta * 188 * 8 / elapsed / 1_000_000
        self._last_rate_packets = packets
        self._last_rate_time = now
        self._sync_button_state(locked)
        self._set_stats(locked, packets, status.get("errors", 0))

    def _set_stats(self, locked: bool, packets: int, errors: int) -> None:
        self.state_value.setText(tr("接続中", "Lock") if locked else tr("切断中", "No Lock"))
        error_text = str(errors) if errors < 1_000_000 else "999999+"
        self.bitrate_value.setText(f"{self._bitrate_mbps:.2f} Mbps")
        self.packets_value.setText(str(packets))
        self.errors_value.setText(error_text)

    def _on_error(self, message: str) -> None:
        error_dialog(self, tr("受信エラー", "RX Error"), message)
        self._sync_button_state()

    def _on_stopped(self) -> None:
        if self._tx_started_alongside_rx:
            self._tx_started_alongside_rx = False
            self.main_window.tx_controller.stop()
        self.video_label.clear()
        self._sync_button_state()
        self._set_stats(False, 0, 0)
        self._last_rate_packets = None
        self._last_rate_time = None
        self._bitrate_mbps = 0.0

    def _on_video_frame(self, data: bytes, width: int, height: int) -> None:
        image = QtGui.QImage(data, width, height, width * 3, QtGui.QImage.Format_RGB888).copy()
        pixmap = dpi_scaled_pixmap(QtGui.QPixmap.fromImage(image), self.video_label)
        self.video_label.setPixmap(pixmap)

    def _on_video_tap(self, _event) -> None:
        self._set_video_fullscreen(not self._video_fullscreen)

    def _set_video_fullscreen(self, enabled: bool) -> None:
        self._video_fullscreen = enabled
        self.status_card.setVisible(not enabled)
        self.panel.setVisible(not enabled)


def create(main_window) -> QtWidgets.QWidget:
    return RxScreen(main_window)
