"""設定画面。Mac版Shonan_Liteの設定画面に合わせ、表示言語・オンデバイス復調状態
などをまとめて表示する。バンドプロファイルは周波数画面(screens/frequency.py)側に
専用の選択UIがあるためここでは扱わない。Pluto接続先(自動検出含む)は出力設定画面
(screens/streamoutput.py)側で扱う。
"""
from __future__ import annotations

from settings_store import normalize_ptt_controller_host
from i18n import bilingual, set_language, tr
import subprocess

from PyQt5 import QtCore, QtWidgets

from widgets import SettingsSubScreen, confirm_dialog, error_dialog


class SettingsScreen(SettingsSubScreen):
    def __init__(self, main_window):
        super().__init__("設定 / Config", lambda: main_window.navigate_to("home"))
        self.main_window = main_window

        # Mac版設定画面を参考にした中央パネル。800x480のPi5画面では、
        # スクロール可能なダークパネルとしてタッチ操作に合わせる。
        content_layout = self.body_layout
        content_layout.setContentsMargins(14, 8, 14, 14)
        content_layout.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        panel = QtWidgets.QFrame()
        panel.setObjectName("settingsPanel")
        panel.setMinimumWidth(1120)
        panel.setMaximumWidth(1220)
        panel.setStyleSheet(
            "QFrame#settingsPanel { background-color: #252a2d;"
            " border: 1px solid #4b5357; border-radius: 18px; }"
            "QFrame#settingsPanel QLabel { color: #eeeeee; background-color: transparent; font-size: 24px; }"
            "QFrame#settingsPanel QComboBox, QLineEdit, QDateTimeEdit {"
            " background-color: #303538; color: #eeeeee; font-size: 24px;"
            " border: 1px solid #42494d; border-radius: 8px; padding: 8px; }"
            "QFrame#settingsPanel QCheckBox { color: #eeeeee; font-size: 21px; }"
            "QFrame#settingsPanel QPushButton { border-radius: 8px; font-size: 24px; }"
        )
        content_layout.addWidget(panel)
        self.body_layout = QtWidgets.QVBoxLayout(panel)
        self.body_layout.setContentsMargins(20, 14, 20, 14)
        self.body_layout.setSpacing(10)

        heading = QtWidgets.QLabel(tr("設定", "Settings"))
        heading.setStyleSheet("font-size: 29px; font-weight: bold; color: white;")
        self.body_layout.addWidget(heading)

        self.body_layout.addWidget(self._section_label(tr("表示言語", "Display Language")))
        lang_layout = QtWidgets.QHBoxLayout()
        lang_layout.setSpacing(0)
        lang_group = QtWidgets.QButtonGroup(self)
        self.ja_lang_btn = self._segment_button("日本語", main_window.settings.language == "JAPANESE")
        self.en_lang_btn = self._segment_button("English", main_window.settings.language == "ENGLISH")
        lang_group.addButton(self.ja_lang_btn)
        lang_group.addButton(self.en_lang_btn)
        self.ja_lang_btn.clicked.connect(lambda: self._set_language("JAPANESE"))
        self.en_lang_btn.clicked.connect(lambda: self._set_language("ENGLISH"))
        lang_layout.addWidget(self.ja_lang_btn)
        lang_layout.addWidget(self.en_lang_btn)
        lang_layout.addStretch(1)
        self.body_layout.addLayout(lang_layout)

        self.body_layout.addWidget(self._section_label(tr("PA_Power/PTTコントローラ (ESP32)", "PA_Power/PTT Controller (ESP32)")))
        self.ptt_controller_ip_edit = QtWidgets.QLineEdit()
        self.ptt_controller_ip_edit.setMinimumHeight(48)
        self.ptt_controller_ip_edit.setPlaceholderText(tr("未使用の場合は空欄のまま", "Leave empty if not used"))
        self.ptt_controller_ip_edit.editingFinished.connect(self._save_ptt_controller_ip)
        self.body_layout.addWidget(self.ptt_controller_ip_edit)
        self.body_layout.addWidget(self._note_label(
            tr("hardware/W5500_PA_PTT_Control のESP32+W5500ボードのIPアドレス。"
               "送信開始/終了に連動してPTTを、アプリ起動/終了に連動して12V電源を自動切替します。"
               "空欄なら連携しません。",
               "IP address of the ESP32 + W5500 board (hardware/W5500_PA_PTT_Control). "
               "PTT follows TX start/stop, and the 12 V power is switched automatically at app start/exit. "
               "Leave empty to disable the link.")
        ))

        self.body_layout.addWidget(self._section_label(tr("オンデバイス復調", "On-device Demodulation")))
        self.on_device_checkbox = QtWidgets.QCheckBox(tr("オンデバイス復調 (GNU Radio)", "On-device demodulation (GNU Radio)"))
        self.on_device_checkbox.toggled.connect(self._on_on_device_toggled)
        self.body_layout.addWidget(self.on_device_checkbox)
        self.body_layout.addWidget(self._note_label(
            tr("ONのとき、送信画面に「受信画面へ」ボタンを表示します。",
               "When ON, the TX screen shows the \"Go to RX\" button.")
        ))

        self.body_layout.addWidget(self._section_label(bilingual("受信診断 / RX Diagnostics")))
        self.iio_preflight_checkbox = QtWidgets.QCheckBox(
            tr("IIOプリフライト試験を実施する", "Run the IIO preflight test"))
        self.iio_preflight_checkbox.setMinimumHeight(48)
        self.iio_preflight_checkbox.toggled.connect(
            self._on_iio_preflight_toggled)
        self.body_layout.addWidget(self.iio_preflight_checkbox)

        # ★このPi5にはRTCバッテリがなく、ネットワーク接続がない現場運用では起動のたびに
        # 日時がリセットされる。オーバーレイ(コールサイン+日時焼き込み、映像ソース画面参照)
        # の日時を正しくするため、手動で日時を設定できるようにする。
        self.body_layout.addWidget(self._section_label(bilingual("システム日時 / System Date & Time")))
        self.datetime_edit = QtWidgets.QDateTimeEdit()
        self.datetime_edit.setMinimumHeight(48)
        self.datetime_edit.setCalendarPopup(True)
        self.datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
        self.body_layout.addWidget(self.datetime_edit)
        self.set_datetime_btn = QtWidgets.QPushButton(bilingual("この日時を設定 / Set"))
        self.set_datetime_btn.setMinimumHeight(48)
        self.set_datetime_btn.clicked.connect(self._on_set_datetime)
        self.body_layout.addWidget(self.set_datetime_btn)
        settings = self.main_window.settings
        self.ptt_controller_ip_edit.setText(settings.ptt_controller_host)
        self.on_device_checkbox.blockSignals(True)
        self.on_device_checkbox.setChecked(settings.use_on_device_demod)
        self.on_device_checkbox.blockSignals(False)
        self.iio_preflight_checkbox.blockSignals(True)
        self.iio_preflight_checkbox.setChecked(settings.iio_preflight_enabled)
        self.iio_preflight_checkbox.blockSignals(False)
        self.datetime_edit.setDateTime(QtCore.QDateTime.currentDateTime())

    @staticmethod
    def _section_label(text: str) -> QtWidgets.QLabel:
        # ★項目名(セクション見出し)だけを本文より一回り大きくする(本文は24px、
        # 入力欄は22px、チェックボックスは21px)。
        label = QtWidgets.QLabel(text)
        label.setStyleSheet("font-size: 34px; font-weight: bold; color: #f2f2f2; padding-top: 8px;")
        return label

    @staticmethod
    def _note_label(text: str) -> QtWidgets.QLabel:
        # ★補足説明の長文がパネル幅を超えて右にはみ出し、途中で切れて見えなくなる
        # 不具合が実機で確認された。折り返し(wordWrap)を有効にし、パネル幅の中で
        # 複数行に収める。
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _segment_button(text: str, checked: bool) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(text)
        button.setCheckable(True)
        button.setChecked(checked)
        button.setFixedSize(130, 48)
        button.setStyleSheet(
            "QPushButton { background-color: #303538; color: #eeeeee; border: none;"
            " min-height: 32px; padding: 3px 8px; font-size: 29px; font-weight: bold; }"
            "QPushButton:checked { background-color: #1677ff; color: white; }"
            "QPushButton:pressed { background-color: #0b55c7; }"
        )
        return button

    def _set_language(self, lang: str) -> None:
        self.main_window.settings.language = lang
        set_language(lang)
        self.main_window.save_settings()
        self.main_window.rebuild_language()

    def _save_ptt_controller_ip(self) -> None:
        value = self.ptt_controller_ip_edit.text().strip()
        try:
            host = normalize_ptt_controller_host(value)
        except ValueError as exc:
            self.ptt_controller_ip_edit.setText(self.main_window.settings.ptt_controller_host)
            error_dialog(self, tr("PTTコントローラ接続先エラー", "PTT Controller Destination Error"), str(exc))
            return
        self.main_window.settings.ptt_controller_host = host
        self.main_window.save_settings()

    def _on_on_device_toggled(self, checked: bool) -> None:
        if checked:
            # ★1台のPluto+でTX/RXを同時に行う(開発・検証用モード)ため、外部アッテネータ
            # なしでは自局の送信信号がそのまま受信機に飛び込み、Pluto+を破損しかねない。
            # 誤ってONにしないよう、確認ダイアログでリスクを明示する。
            ok = confirm_dialog(
                self, tr("オンデバイス復調", "On-device Demodulation"),
                tr("この機能は開発時に使うモードです。1台のPlutoで同時に送受信を行うため、"
                   "<span style=\"color:#ff4444; font-weight:bold;\">"
                   "外部にアッテネータを入れなければPlutoが壊れます。</span>\n"
                   "このまま実行しますか？",
                   "This mode is for development. Because one Pluto transmits and receives at the same time, "
                   "<span style=\"color:#ff4444; font-weight:bold;\">"
                   "the Pluto will be damaged unless you insert an external attenuator.</span>\n"
                   "Do you want to continue?")
            )
            if not ok:
                self.on_device_checkbox.blockSignals(True)
                self.on_device_checkbox.setChecked(False)
                self.on_device_checkbox.blockSignals(False)
                return
        self.main_window.settings.use_on_device_demod = checked
        self.main_window.settings.simultaneous_tx_rx_test = checked
        self.main_window.save_settings()
        tx_screen = self.main_window._screens.get("tx")
        if tx_screen is not None and hasattr(tx_screen, "update_navigation_buttons"):
            tx_screen.update_navigation_buttons()

    def _on_iio_preflight_toggled(self, checked: bool) -> None:
        self.main_window.settings.iio_preflight_enabled = checked
        self.main_window.save_settings()

    def _on_set_datetime(self) -> None:
        # ★手動設定してもNTPが有効なままだとsystemdが直後に上書きしてしまうため、
        # 先にNTP同期を止めてからtimedatectlで反映する(RTCバッテリなし・現場運用で
        # ネットワーク未接続の機体を想定)。
        value = self.datetime_edit.dateTime().toString("yyyy-MM-dd HH:mm:ss")
        try:
            subprocess.run(
                ["sudo", "-n", "timedatectl", "set-ntp", "false"],
                check=True, capture_output=True, text=True, timeout=5)
            subprocess.run(
                ["sudo", "-n", "timedatectl", "set-time", value],
                check=True, capture_output=True, text=True, timeout=5)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
            message = exc.stderr if isinstance(exc, subprocess.CalledProcessError) else str(exc)
            error_dialog(self, tr("日時設定エラー", "Date/Time Error"),
                         tr(f"日時の設定に失敗しました:\n{message}", f"Failed to set the date and time:\n{message}"))


def create(main_window) -> QtWidgets.QWidget:
    return SettingsScreen(main_window)
