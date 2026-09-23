#!/usr/bin/env python3
"""shonan-pi5 タッチGUI エントリポイント。

「Homeがハブ、各画面はHomeから直接遷移・Homeへ直接戻る」フラットな1階層ナビゲーションを
QStackedWidgetで再現する。

起動: QT_QPA_PLATFORM=eglfs python3 main.py
(X11/Wayland不要。Pi5のDSI接続LCD/EGLFSへ直接描画する)
"""
from __future__ import annotations

import http.client
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import platform_compat

# ★QApplication構築前に設定する必要がある(QPAプラットフォーム統合が起動時に読む)。
# ソースからビルドしたOpenWnn(日本語)対応版qtvirtualkeyboardを使う
# (docs/qtvirtualkeyboard_ja_build.md参照)。Windowsはこのビルド成果物が存在せず、
# 物理キーボード+OS標準IMEで日本語入力できるため設定しない。
if not platform_compat.IS_WINDOWS:
    os.environ.setdefault("QT_IM_MODULE", "qtvirtualkeyboard")

from PyQt5 import QtCore, QtNetwork, QtQuickWidgets, QtWidgets

import settings_store
from i18n import set_language, tr
from backend import (
    PTT_CHANNEL_POWER, RxController, TxController, _push_pluto_settings,
    _send_ptt_channel_state,
)

# 電源投入(アプリ起動)からMCU1(ESP32)のGPIO26(12V電源チャンネル)をONにするまでの遅延。
MCU1_GPIO26_ON_DELAY_MS = 5_000
# プログラム終了時、MCU1のGPIO26をOFFにしてから実際に終了するまでの遅延。
MCU1_GPIO26_OFF_DELAY_SEC = 3

SCREEN_ROUTES = [
    "home", "tx", "rx", "frequency", "rssi", "symbolrate", "fec", "modulation",
    "videosource", "streamoutput", "rxgain", "txpower", "manual", "settings",
    "testequipment", "presets",
]


class MainWindow(QtWidgets.QMainWindow):
    restart_finished = QtCore.pyqtSignal(bool, str)
    CONTROL_SOCKET = "/tmp/shonan-pi5-gui.sock"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Shonan for RasPI5")

        self.settings = settings_store.load()
        set_language(self.settings.language)
        # ★オンデバイス復調は前回終了時の値を引き継がず、常に起動時はOFFにする
        # (受信ソフトが不安定な状態のまま次回起動しても送受信同時実行に入らないよう、
        # 毎回明示的に選び直させるための安全側デフォルト)。
        self.settings.use_on_device_demod = False
        self.settings.simultaneous_tx_rx_test = self.settings.use_on_device_demod
        settings_store.save(self.settings)
        self.tx_controller = TxController(self)
        self.rx_controller = RxController(self)

        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)
        self.stack.hide()
        self._control_server = QtNetwork.QLocalServer(self)
        QtNetwork.QLocalServer.removeServer(self.CONTROL_SOCKET)
        self._control_server.newConnection.connect(self._on_control_connection)
        self._control_server.listen(self.CONTROL_SOCKET)

        self._screens = {}
        self._restart_dialog = None
        self._app_restarting = False
        self._restart_title = "アプリ再起動"
        self._build_screens()
        self._startup_restart_pending = False
        # 起動直後にPluto+を再起動する(「アプリ再起動」ボタンと同じ処理)。
        # 完了後(または対象ホーム未設定でスキップした場合)に、続けて短いRX DMA
        # 確認を行う。Pluto+再起動中に並行してiio-preflightを走らせると、再起動
        # 直後の未接続状態を誤って失敗と報告してしまうため、直列に実行する。
        QtCore.QTimer.singleShot(0, self._startup_reboot_pluto)
        # 電源投入(アプリ起動)からMCU1_GPIO26_ON_DELAY_MS後にMCU1(ESP32)のGPIO26
        # (12V電源チャンネル)をONにする。Pi5本体のGPIOは使用しない。
        QtCore.QTimer.singleShot(MCU1_GPIO26_ON_DELAY_MS, self._power_on_mcu1_gpio26)

        self._build_keyboard_panel()

    def _power_on_mcu1_gpio26(self) -> None:
        host = self.settings.ptt_controller_host
        if not host:
            return
        try:
            _send_ptt_channel_state(host, PTT_CHANNEL_POWER, "on")
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            print(f"[MCU1] GPIO26 ON通知に失敗しました: {exc}", flush=True)

    def _build_keyboard_panel(self) -> None:
        """テキスト入力欄(コールサイン・備考等)フォーカス時に画面下部へ表示する
        オンスクリーンキーボード。eglfs(コンポジタなし直描画)はトップレベル
        ウィンドウを1つしか扱えないため、Qt Virtual KeyboardのInputPanel.qmlを
        別ウィンドウとしてではなくQQuickWidgetとしてこのQMainWindowに埋め込む
        (docs/qtvirtualkeyboard_ja_build.md参照)。
        """
        self.keyboard_panel = QtQuickWidgets.QQuickWidget(self)
        self.keyboard_panel.setResizeMode(
            QtQuickWidgets.QQuickWidget.SizeRootObjectToView)
        self.keyboard_panel.setSource(
            QtCore.QUrl.fromLocalFile(
                str(platform_compat.app_dir() / "gui" / "qml"
                    / "InputPanelWrapper.qml")))
        # ★Windowsのpip版PyQt5には(Pi5でソースビルドしているOpenWnn対応版と異なり)
        # QtQuick.VirtualKeyboard QMLモジュールが含まれない場合がある。読み込み失敗時は
        # オンスクリーンキーボード機能自体を諦め、物理キーボード/OS標準IMEでの入力に
        # 委ねる(この機能が無くてもテキスト入力欄自体は通常のQLineEditとして動作する)。
        if platform_compat.IS_WINDOWS and self.keyboard_panel.status() == QtQuickWidgets.QQuickWidget.Error:
            self.keyboard_panel.deleteLater()
            self.keyboard_panel = None
            return
        # ★キーボードのキーをタップするとQQuickWidget自体がQtのウィジェットフォーカスを
        # 奪ってしまい、入力対象のQLineEditとの紐付けが切れて文字が入力できなくなる
        # 不具合があった(実機で確認)。NoFocusにしてタップしてもフォーカスを奪わない
        # ようにする(キー入力自体はQt Virtual Keyboard内部のInputContext経由で
        # フォーカスを移動せずに送られるため、これで問題なく動作する)。
        self.keyboard_panel.setFocusPolicy(QtCore.Qt.NoFocus)
        self.keyboard_panel.hide()
        self._active_scroll_area = None
        self._keyboard_spacer = None
        # ★実機の実タッチでは、キーボード初期表示時にフォーカスが一瞬ぶれて
        # (フィールド→None/他ウィジェット→キーボード自身、のように)
        # focusChangedが連続発火することがあり、即座にhideすると
        # スクロール位置がリセットされてしまう不具合があった。
        # 短いディレイを挟み、その間に入力欄へフォーカスが戻ればhideを取り消す。
        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(200)
        self._hide_timer.timeout.connect(self._hide_keyboard_panel)
        QtWidgets.QApplication.instance().focusChanged.connect(
            self._on_focus_changed)

    def _on_focus_changed(self, _old, new) -> None:
        # ★NumericKeypadDialog(周波数入力等)はQLineEditを一時的に別のトップレベル
        # ウィンドウへ移動して使う。そのフィールドがフォーカスを得た場合もこの
        # ハンドラが反応してしまうと、_scroll_field_above_keyboardが既にMainWindow
        # 配下から外れたウィジェットに対してmapTo()を呼びクラッシュする(実機で確認)。
        # このMainWindow自身のウィジェットツリー内でのフォーカス移動のみを扱う。
        if isinstance(new, (QtWidgets.QLineEdit, QtWidgets.QPlainTextEdit)) and new.window() is self:
            self._hide_timer.stop()
            self._show_keyboard_panel(new)
        elif new is not self.keyboard_panel:
            self._hide_timer.start()

    def _show_keyboard_panel(self, focused_widget: QtWidgets.QWidget) -> None:
        height = min(260, self.height() // 2)
        keyboard_top = self.height() - height
        self.keyboard_panel.setGeometry(0, keyboard_top, self.width(), height)
        self.keyboard_panel.show()
        self.keyboard_panel.raise_()
        self._scroll_field_above_keyboard(focused_widget, height)

    def _scroll_field_above_keyboard(
            self, field: QtWidgets.QWidget, keyboard_height: int) -> None:
        """フォーカスした入力欄がキーボードで隠れないようにする。単純に
        QScrollAreaをスクロールするだけでは、入力欄より下のコンテンツが
        足りずキーボード分の高さを確保できないことがあった(実機で確認、
        スクロール可能範囲がキーボードの高さより小さかった)。
        スクロール末尾に一時的な余白(スペーサー)を足してスクロール可能範囲
        自体を広げてから、絶対位置でスクロールする(「現在値+差分」方式だと
        フォーカスの連続発火で値がずれることがあったため)。"""
        scroll_area = None
        widget = field.parentWidget()
        while widget is not None:
            if isinstance(widget, QtWidgets.QScrollArea):
                scroll_area = widget
                break
            widget = widget.parentWidget()
        if scroll_area is None:
            return
        content_widget = scroll_area.widget()
        body_layout = content_widget.layout()
        if self._active_scroll_area is None:
            self._active_scroll_area = scroll_area
            # ★keyboard_heightちょうどだと、キーボードの上端ぎりぎりまで
            # 引き上げたい場合にスクロール可能範囲が足りずクランプされることが
            # あった(実機で確認)。余裕を持たせて多めに確保する。
            self._keyboard_spacer = QtWidgets.QSpacerItem(
                0, keyboard_height + 150, QtWidgets.QSizePolicy.Minimum,
                QtWidgets.QSizePolicy.Fixed)
            body_layout.addItem(self._keyboard_spacer)
            # ★スペーサーを足しただけではQScrollAreaのスクロール範囲(maximum)が
            # 実機で即座に再計算されず、singleShot(0)後でも古い値のまま
            # クランプされてしまう不具合を確認した。レイアウトとコンテンツ
            # ウィジェットのリサイズを強制的に確定させる。
            body_layout.activate()
            content_widget.resize(content_widget.sizeHint())
            content_widget.updateGeometry()

        def apply_scroll() -> None:
            # ★QApplication自体のクリック時自動フォーカス処理は、フィールド側の
            # mousePressEvent上書き(例: frequency.pyのNumericKeypadDialog起動)より
            # 先に働くことがある。その場合ここがスケジュールされた直後に、同じ
            # クリック処理の中でフィールドが別のトップレベルウィンドウ(ダイアログ等)
            # へ再親化されてしまい、発火時にはfield.mapTo(content_widget, ...)が
            # 既にcontent_widgetの子孫でなくなったウィジェットを指してクラッシュする
            # (実機で確認)。発火時点でまだMainWindow配下にあるか再検証する。
            if field.window() is not self:
                return
            # ★キーボードのすぐ上ぎりぎりではなく、タイトルバーの下あたりまで
            # 入力欄を引き上げる(キーボードに隠れるとの指摘を受けて余裕を持たせた)。
            target_top = 50
            field_y_in_content = field.mapTo(content_widget, QtCore.QPoint(0, 0)).y()
            bar = scroll_area.verticalScrollBar()
            new_value = max(0, min(bar.maximum(), field_y_in_content - target_top))
            bar.setValue(new_value)

        QtCore.QTimer.singleShot(50, apply_scroll)

    def _hide_keyboard_panel(self) -> None:
        self.keyboard_panel.hide()
        if self._active_scroll_area is not None:
            body_layout = self._active_scroll_area.widget().layout()
            body_layout.removeItem(self._keyboard_spacer)
            self._active_scroll_area.verticalScrollBar().setValue(0)
            self._active_scroll_area = None
            self._keyboard_spacer = None

    def _build_screens(self) -> None:
        # 各screens.*モジュールは create(main_window) -> QWidget を提供する規約にする。
        from screens import (
            rssi, fec, frequency, home, manual, modulation, rx, rxgain,
            settings as settings_screen, streamoutput, symbolrate,
            testequipment, tx, txpower, videosource, presets,
        )

        self._screen_modules = {
            "home": home, "tx": tx, "rx": rx, "frequency": frequency, "rssi": rssi,
            "symbolrate": symbolrate, "fec": fec, "modulation": modulation,
            "videosource": videosource, "streamoutput": streamoutput,
            "rxgain": rxgain, "txpower": txpower, "manual": manual,
            "settings": settings_screen, "testequipment": testequipment,
            "presets": presets,
        }
        # ★以前は起動時に全16画面を一括構築していたが、映像ソース画面のffmpeg
        # デバイス列挙(subprocess起動)等、画面ごとの構築コストがすべて起動を
        # ブロックしていた(実測で1秒以上)。実際に開くまで見えないHome以外の
        # 画面は、初回navigate_to()時に遅延構築する(_ensure_screen_built参照)。
        self._ensure_screen_built("home")

    def _ensure_screen_built(self, route: str) -> QtWidgets.QWidget:
        widget = self._screens.get(route)
        if widget is None:
            widget = self._screen_modules[route].create(self)
            self._screens[route] = widget
            self.stack.addWidget(widget)
        return widget

    def rebuild_language(self) -> None:
        """設定画面の言語変更後、現在表示中の画面を再生成して切替を即時反映する。

        他の画面は次にnavigate_to()された時点で新しい言語で遅延再構築される
        (_ensure_screen_built参照)。"""
        route = "home"
        current = self.stack.currentWidget()
        for name, widget in self._screens.items():
            if widget is current:
                route = name
                break
        while self.stack.count():
            widget = self.stack.widget(0)
            self.stack.removeWidget(widget)
            widget.deleteLater()
        self._screens = {}
        self.navigate_to(route)

    def navigate_to(self, route: str) -> None:
        widget = self._ensure_screen_built(route)
        current = self.stack.currentWidget()
        if current is not widget and hasattr(current, "on_hide"):
            current.on_hide()
        if hasattr(widget, "on_show"):
            widget.on_show()
        self.stack.setCurrentWidget(widget)

    def _on_control_connection(self) -> None:
        socket = self._control_server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda s=socket: self._handle_control_socket(s))
        socket.disconnected.connect(socket.deleteLater)

    def _handle_control_socket(self, socket) -> None:
        command = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
        if command == "tx":
            self.navigate_to("tx")
            self._screens["tx"]._on_start_stop()
        elif command == "rx":
            self.navigate_to("rx")
            self.rx_controller.start(self.settings)
        elif command == "presets":
            self.navigate_to("presets")
        elif command == "screenshot":
            self.capture_screenshot()
        elif command == "restart":
            self.restart_app()
        socket.write(b"OK\n")
        socket.flush()

    def save_settings(self) -> None:
        settings_store.save(self.settings)

    def restart_app(self) -> None:
        """iPad版の「アプリ再起動」と同じソフトリスタートを行う。

        プロセスは終了させず、送受信を停止してPlutoを再起動し、再接続後に
        保存済みの無線設定を再適用する。SSHとネットワーク待機はGUIを止めない
        ようにバックグラウンドで実行する。
        """
        if self._app_restarting:
            return
        self.tx_controller.stop()
        self.rx_controller.stop()
        self.save_settings()
        self._startup_restart_pending = True
        self.stack.hide()
        self._begin_pluto_restart(
            "アプリ再起動", tr("アプリを再起動しています…", "Restarting the app..."))

    def _startup_reboot_pluto(self) -> None:
        """起動直後にPluto+を再起動する(iPad版ContentViewの起動時rebootと同じ)。

        「アプリ再起動」ボタンと同じ経路(_begin_pluto_restart)を使う。完了後
        (対象ホーム未設定でスキップした場合を含む)、続けて短いRX DMA確認を行う。

        ★Windows版ではPi5実機と異なりSSH経由のPluto再起動が前提の運用ではなく、
        起動のたびに数秒〜十数秒待たされるだけで実害がある(実機ではなく
        開発機で毎回叩く想定のため)。Windows版では常にこの再起動をスキップする。
        """
        self._startup_restart_pending = True
        if platform_compat.IS_WINDOWS:
            self._startup_restart_pending = False
            self.navigate_to("home")
            self.stack.show()
            self.rx_controller.run_iio_preflight(self.settings)
            return
        try:
            host = self.settings.pluto_host()
        except ValueError:
            host = ""
        if not host:
            self._startup_restart_pending = False
            self.navigate_to("home")
            self.stack.show()
            self.rx_controller.run_iio_preflight(self.settings)
            return
        self._begin_pluto_restart(
            "起動時Pluto再起動",
            tr("アプリ起動時にPlutoも再起動しています…", "Restarting Pluto at app startup..."))

    def _restart_display_title(self) -> str:
        # _restart_titleは判定キー(日本語固定)なので、表示時だけ言語に合わせる。
        titles = {
            "アプリ再起動": tr("アプリ再起動", "App Restart"),
            "起動時Pluto再起動": tr("起動時Pluto再起動", "Pluto Restart at Startup"),
        }
        return titles.get(self._restart_title, self._restart_title)

    def _begin_pluto_restart(self, title: str, message_text: str) -> None:
        if self._app_restarting:
            return
        self._app_restarting = True
        self._restart_title = title
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(self._restart_display_title())
        dialog.setModal(True)
        dialog.setFixedSize(500, 240 if title in ("起動時Pluto再起動", "アプリ再起動") else 210)
        dialog.setStyleSheet(
            "QDialog { background: #101416; color: white; } "
            "QLabel { color: white; }")
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(12)
        icon = QtWidgets.QLabel("⟳")
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setStyleSheet("color: #0c9bc0; font-size: 52px; font-weight: bold;")
        layout.addWidget(icon)
        message = QtWidgets.QLabel(message_text)
        message.setAlignment(QtCore.Qt.AlignCenter)
        message.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(message)
        if title in ("起動時Pluto再起動", "アプリ再起動"):
            sub_message = QtWidgets.QLabel(tr("Plutoも再起動しています…", "Pluto is also restarting…"))
            sub_message.setAlignment(QtCore.Qt.AlignCenter)
            sub_message.setStyleSheet("font-size: 14px; color: #0c9bc0;")
            layout.addWidget(sub_message)
            note = QtWidgets.QLabel(tr(
                "Plutoの再起動に20秒以上かかる場合は確認をスキップしてホーム画面表示",
                "If Pluto takes more than 20 seconds to restart, the check is skipped and the Home screen is shown"))
            note.setAlignment(QtCore.Qt.AlignCenter)
            note.setWordWrap(True)
            note.setStyleSheet("font-size: 11px; color: #aeb9bd;")
            layout.addWidget(note)
        self._restart_dialog = dialog
        self.restart_finished.connect(self._finish_app_restart)
        dialog.show()
        if title in ("起動時Pluto再起動", "アプリ再起動"):
            QtCore.QTimer.singleShot(20000, self._skip_startup_restart)
        threading.Thread(target=self._restart_pluto_and_restore, daemon=True).start()

    def _skip_startup_restart(self) -> None:
        if not self._app_restarting or not self._startup_restart_pending:
            return
        print("[pluto-startup] confirmation timeout; continuing to home screen", flush=True)
        if self._restart_dialog is not None:
            self._restart_dialog.accept()
            self._restart_dialog.deleteLater()
            self._restart_dialog = None
        try:
            self.restart_finished.disconnect(self._finish_app_restart)
        except TypeError:
            pass
        self._startup_restart_pending = False
        self._app_restarting = False
        self.navigate_to("home")
        self.stack.show()

    def _restart_pluto_and_restore(self) -> None:
        try:
            host = self.settings.pluto_host()
            cmd = [
                "sshpass", "-p", "analog", "ssh",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=6",
                "-o", "PreferredAuthentications=password",
                "-o", "PubkeyAuthentication=no",
                f"root@{host}", "reboot",
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                print(f"[pluto-startup] reboot command finished rc={result.returncode}", flush=True)
            except (OSError, subprocess.TimeoutExpired):
                print("[pluto-startup] reboot command ended while Pluto was restarting", flush=True)

            # 再起動前の接続を復旧済みと誤判定しないよう、いったん
            # Plutoがオフラインになることを確認してから復旧を待つ。
            print("[pluto-startup] waiting for Pluto to go offline", flush=True)
            time.sleep(5)
            offline_deadline = time.monotonic() + 20
            went_offline = False
            while time.monotonic() < offline_deadline:
                if not self._pluto_is_online(host):
                    went_offline = True
                    print("[pluto-startup] Pluto offline confirmed", flush=True)
                    break
                time.sleep(1)
            if not went_offline:
                print("[pluto-startup] Pluto offline was not confirmed", flush=True)
                self.restart_finished.emit(False, tr(
                    "Plutoの再起動完了を確認できませんでした", "Could not confirm that Pluto finished restarting"))
                return

            print("[pluto-startup] waiting for Pluto Web UI and IIO", flush=True)
            deadline = time.monotonic() + 90
            online = False
            while time.monotonic() < deadline:
                if self._pluto_is_online(host):
                    online = True
                    print("[pluto-startup] Pluto Web UI and IIO online confirmed", flush=True)
                    break
                time.sleep(2)
            if not online:
                print("[pluto-startup] Pluto online was not confirmed", flush=True)
                self.restart_finished.emit(False, tr("Plutoへ再接続できませんでした", "Could not reconnect to Pluto"))
                return

            lo_hz = self.settings.effective_lo_hz()
            if lo_hz is None:
                self.restart_finished.emit(False, tr("周波数が未設定です", "Frequency is not set"))
                return
            verified = False
            last_error = tr("設定値の読み戻しに失敗しました", "Failed to read back the settings")
            for attempt in range(5):
                try:
                    _push_pluto_settings(self.settings, lo_hz)
                    if self._wait_for_pluto_settings(host, self.settings, lo_hz, timeout=8):
                        verified = True
                        print(f"[pluto-startup] settings verified (attempt={attempt + 1})", flush=True)
                        break
                    last_error = tr(
                        f"Pluto設定の確認に失敗しました (attempt={attempt + 1})",
                        f"Failed to verify Pluto settings (attempt={attempt + 1})")
                except OSError as exc:
                    last_error = tr(
                        f"Pluto設定書き込みに失敗しました (attempt={attempt + 1}): {exc}",
                        f"Failed to write Pluto settings (attempt={attempt + 1}): {exc}")
                    print(f"[pluto-startup] {last_error}", flush=True)
                time.sleep(1)
            if not verified:
                raise RuntimeError(last_error)
            print("[pluto-startup] settings reapplied and verified; startup restart complete", flush=True)
            self.restart_finished.emit(True, tr("設定を再適用しました", "Settings re-applied"))
        except Exception as exc:  # noqa: BLE001 - UIへ失敗を返して再起動処理を完了する
            self.restart_finished.emit(False, tr(
                f"Pluto設定の再適用に失敗しました: {exc}", f"Failed to re-apply Pluto settings: {exc}"))

    @staticmethod
    def _pluto_is_online(host: str) -> bool:
        """iPad版と同じくWeb UIとiiodの両方が復旧したことを確認する。"""
        try:
            request = urllib.request.Request(f"http://{host}/pluto.php", method="GET")
            with urllib.request.urlopen(request, timeout=3) as response:
                if not 200 <= response.status < 300:
                    return False
        except (OSError, ValueError):
            return False
        try:
            with socket.create_connection((host, 30431), timeout=3):
                return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _wait_for_pluto_settings(
        host: str, settings: settings_store.AppSettings, lo_hz: float, timeout: float
    ) -> bool:
        """SSHで書き込んだDVB-S2設定をPlutoから読み戻して確認する。"""
        expected = {
            "freq": f"{lo_hz / 1_000_000:.3f}",
            "channel": "Custom", "mode": "DVBS2",
            "mod": settings.modulation_scheme,
            "sr": str(round(settings.symbol_rate_msps * 1000)),
            "fec": settings.fec_rate.replace("/", ""),
            "pilots": "On", "frame": "LongFrame",
            "power": str(int(settings.tx_power_db)), "rolloff": "0.35",
        }
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                command = [
                    "sshpass", "-p", "analog", "ssh",
                    "-o", "StrictHostKeyChecking=accept-new",
                    "-o", "ConnectTimeout=6",
                    "-o", "PreferredAuthentications=password",
                    "-o", "PubkeyAuthentication=no",
                    f"root@{host}", "cat", "/www/settings.txt",
                ]
                result = subprocess.run(command, capture_output=True, text=True, timeout=8)
                if result.returncode != 0:
                    raise OSError(result.stderr.strip() or tr("SSH読み戻しに失敗しました", "SSH read-back failed"))
                actual = {}
                for line in result.stdout.splitlines():
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        actual[parts[0]] = parts[1].strip()
                if all(actual.get(key) == value for key, value in expected.items()):
                    return True
            except (OSError, ValueError):
                pass
            time.sleep(1)
        return False

    @QtCore.pyqtSlot(bool, str)
    def _finish_app_restart(self, success: bool, detail: str) -> None:
        startup_restart = self._startup_restart_pending
        if self._restart_dialog is not None:
            self._restart_dialog.accept()
            self._restart_dialog.deleteLater()
            self._restart_dialog = None
        try:
            self.restart_finished.disconnect(self._finish_app_restart)
        except TypeError:
            pass
        self._app_restarting = False
        if startup_restart:
            self._startup_restart_pending = False
            self.navigate_to("home")
            self.stack.show()
            self.rx_controller.run_iio_preflight(self.settings)
        if not success:
            QtWidgets.QMessageBox.warning(self, self._restart_display_title(), detail)

    def capture_screenshot(self) -> None:
        """現在のQt/DSI画面をPNGへ保存する。DRMを直接取得しないためGUIを止めない。"""
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            print("[screenshot] primary screen is unavailable", flush=True)
            return
        pixmap = screen.grabWindow(0)
        output_path = platform_compat.tmp_path("shonan_lcd_actual.png")
        if pixmap.isNull() or not pixmap.save(output_path, "PNG"):
            print(f"[screenshot] failed to save {output_path}", flush=True)
            return
        print(f"[screenshot] saved {output_path} ({pixmap.width()}x{pixmap.height()})", flush=True)

    def closeEvent(self, event) -> None:
        self.tx_controller.stop()
        self.rx_controller.stop()
        # 先にMCU1(ESP32)のGPIO26をOFFにしてから、実際の終了(super().closeEvent)を
        # MCU1_GPIO26_OFF_DELAY_SEC秒待つ(電源系統が安全に落ちきるのを待つ猶予)。
        # Pi5本体のGPIOは使用しない。
        host = self.settings.ptt_controller_host
        if host:
            try:
                _send_ptt_channel_state(host, PTT_CHANNEL_POWER, "off")
            except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
                print(f"[MCU1] GPIO26 OFF通知に失敗しました: {exc}", flush=True)
            time.sleep(MCU1_GPIO26_OFF_DELAY_SEC)
        super().closeEvent(event)


_GLOBAL_STYLESHEET = """
QWidget { background-color: black; color: #eeeeee; font-size: 14px; }
QPushButton {
  background-color: #14235c; color: white; font-weight: bold;
  border: 2px solid #0c1638; border-radius: 8px; padding: 8px;
  outline: none;
}
QPushButton:pressed { background-color: #0c1638; }
QPushButton:disabled { background-color: #999999; border-color: #777777; color: #dddddd; }
QPushButton:focus { outline: none; }
QRadioButton, QCheckBox { color: #eeeeee; }
QRadioButton::indicator, QCheckBox::indicator { width: 28px; height: 28px; }
QGroupBox { font-weight: bold; color: #eeeeee; border: 1px solid #555555; border-radius: 6px; margin-top: 8px; }
QLineEdit, QComboBox { background-color: #222222; color: #eeeeee; border: 1px solid #555555; border-radius: 4px; padding: 6px; }
QScrollArea { background-color: black; border: none; }
"""


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(_GLOBAL_STYLESHEET)
    window = MainWindow()
    if platform_compat.IS_WINDOWS:
        # ★showFullScreen()(排他的フルスクリーン)は環境によって描画が真っ黒に
        # なる不具合が確認されたため、Windowsではタイトルバー付きの最大化
        # (showMaximized)で画面いっぱいに表示する。
        window.showMaximized()
    else:
        window.showFullScreen()
    # ★SIGUSR1/SIGUSR2/SIGALRM/SIGWINCHはUnix専用シグナルで、Windowsのsignalモジュール
    # には存在しない。外部からのスクリーンショット/TX起動トリガーはPi5実機の運用
    # (ssh経由でkillコマンドを送る)専用の機能のため、Windowsでは単に登録しない。
    if not platform_compat.IS_WINDOWS:
        signal.signal(signal.SIGUSR1, lambda _signum, _frame: QtCore.QTimer.singleShot(
            0, window.capture_screenshot))
        signal.signal(signal.SIGUSR2, lambda _signum, _frame: QtCore.QTimer.singleShot(
            0, lambda: (window.navigate_to("tx"), window._screens["tx"]._on_start_stop())))
        signal.signal(signal.SIGALRM, lambda _signum, _frame: QtCore.QTimer.singleShot(
            0, lambda: (window.navigate_to("tx"), window._screens["tx"]._on_start_stop())))
        signal.signal(signal.SIGWINCH, lambda _signum, _frame: QtCore.QTimer.singleShot(
            0, lambda: (window.navigate_to("rx"), window.rx_controller.start(window.settings))))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
