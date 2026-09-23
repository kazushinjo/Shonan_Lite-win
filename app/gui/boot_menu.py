"""Boot-time application selector for the Raspberry Pi 5 touch display."""
from __future__ import annotations

import http.client
import os
import subprocess
import sys
import urllib.error
from pathlib import Path


def _configure_touch() -> None:
    """Bind Qt to the Raspberry Pi touchscreen without a fixed event number."""
    for name_file in sorted(Path("/sys/class/input").glob("event*/device/name")):
        try:
            device_name = name_file.read_text(encoding="utf-8").strip().lower()
            if device_name == "raspberrypi-ts" or "ft5x06" in device_name:
                event = name_file.parents[1].name
                os.environ["QT_QPA_EGLFS_DISABLE_INPUT"] = "1"
                os.environ["QT_QPA_GENERIC_PLUGINS"] = (
                    f"evdevtouch:/dev/input/{event}"
                )
                return
        except OSError:
            continue


_configure_touch()

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PyQt5 import QtCore, QtWidgets

import settings_store
from backend import PTT_CHANNEL_POWER, _send_ptt_channel_state


MARKER = Path.home() / ".pi5_boot_mode_langstone"
LANGSTONE_UNIT = Path("/etc/systemd/system/langstone.service")


class IPSettingDialog(QtWidgets.QDialog):
    """タッチ専用の簡易IPアドレス入力ダイアログ(数字+ドットのみのテンキー)。"""

    def __init__(self, current_ip: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pluto IP設定")
        self.setModal(True)
        self.setStyleSheet(
            "QDialog{background:#101416;color:white;}"
            "QLabel{color:white;}"
            "QPushButton{font-size:20px;min-height:56px;border-radius:8px;"
            "background:#1c2733;color:white;border:1px solid #3b5159;}"
            "QPushButton:pressed{background:#2d80c7;}"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        label = QtWidgets.QLabel("PlutoのIPアドレス\nPluto IP address")
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setStyleSheet("font-size:18px;font-weight:bold;")
        layout.addWidget(label)

        self.edit = QtWidgets.QLineEdit(current_ip)
        self.edit.setAlignment(QtCore.Qt.AlignCenter)
        self.edit.setStyleSheet(
            "font-size:30px;font-weight:bold;padding:10px;"
            "background:#000000;color:#7fd4ff;border:1px solid #3b5159;border-radius:6px;")
        self.edit.setReadOnly(True)
        layout.addWidget(self.edit)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(8)
        keys = ["7", "8", "9", "4", "5", "6", "1", "2", "3", "C", "0", "←"]
        for i, key in enumerate(keys):
            btn = QtWidgets.QPushButton(key)
            btn.setMinimumWidth(70)
            btn.clicked.connect(lambda _checked=False, k=key: self._on_key(k))
            grid.addWidget(btn, i // 3, i % 3)
        dot_btn = QtWidgets.QPushButton(".")
        dot_btn.setMinimumWidth(70)
        dot_btn.clicked.connect(lambda: self._on_key("."))
        grid.addWidget(dot_btn, 3, 3)
        layout.addLayout(grid)

        buttons = QtWidgets.QHBoxLayout()
        cancel = QtWidgets.QPushButton("キャンセル / Cancel")
        ok = QtWidgets.QPushButton("保存 / Save")
        ok.setStyleSheet("background:#164f87;font-weight:bold;")
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        layout.addLayout(buttons)

    def _on_key(self, key: str) -> None:
        if key == "C":
            self.edit.setText("")
        elif key == "←":
            self.edit.setText(self.edit.text()[:-1])
        else:
            self.edit.setText(self.edit.text() + key)

    def value(self) -> str:
        return self.edit.text().strip()


class BootMenu(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._selected = False
        self.setWindowTitle("Shonan boot menu")
        self.setStyleSheet("background:#050505;color:white;")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(45, 15, 45, 55)
        layout.setSpacing(24)

        title = QtWidgets.QLabel("起動するアプリを選択してください")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("font-size:28px;font-weight:bold;")
        layout.addWidget(title)

        shonan = QtWidgets.QPushButton("Shonan_Lite (DATV)\nDATV送受信")
        langstone = QtWidgets.QPushButton("Langstone V3\nSDRトランシーバー")
        for button in (shonan, langstone):
            button.setMinimumHeight(115)
            button.setStyleSheet(
                "QPushButton{font-size:25px;font-weight:bold;background:#164f87;"
                "border:3px solid white;border-radius:16px;}"
                "QPushButton:pressed{background:#2d80c7;}"
                "QPushButton:disabled{background:#333;color:#888;}"
            )
            layout.addWidget(button)

        shonan.clicked.connect(lambda: self._launch(False))
        langstone.clicked.connect(lambda: self._launch(True))
        if not LANGSTONE_UNIT.exists():
            langstone.setEnabled(False)
            langstone.setText("Langstone V3\nインストール未完了")

        # ★要望: 起動メニューからPluto+のIPアドレスを設定できるようにする。
        # ここで設定した値はsettings.json(pluto_uri)に一元化して永続化し、
        # Shonan_Lite側はそのままpluto_uriとして使い、Langstone側は
        # run_pluto起動時に同じ値をPLUTO_IP環境変数として読み込む
        # (run_pluto参照)。
        self.ip_button = QtWidgets.QPushButton()
        self.ip_button.setMinimumHeight(64)
        self.ip_button.setStyleSheet(
            "QPushButton{font-size:16px;font-weight:bold;background:#1c2733;"
            "border:2px solid #3b5159;border-radius:12px;color:#7fd4ff;}"
            "QPushButton:pressed{background:#2d80c7;color:white;}"
        )
        self.ip_button.clicked.connect(self._on_ip_setting)
        layout.addWidget(self.ip_button)
        self._refresh_ip_button()

    def _refresh_ip_button(self) -> None:
        try:
            current = settings_store.load().pluto_host()
        except Exception:
            current = "192.168.0.10"
        self.ip_button.setText(f"Pluto IP設定: {current}  /  Pluto IP Setting")

    def _on_ip_setting(self) -> None:
        settings = settings_store.load()
        dialog = IPSettingDialog(settings.pluto_host(), self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        try:
            host = settings_store.normalize_pluto_host(dialog.value())
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Pluto IP設定エラー", str(exc))
            return
        settings.pluto_uri = f"ip:{host}"
        settings_store.save(settings)
        self._refresh_ip_button()

    def _launch(self, langstone: bool) -> None:
        if self._selected:
            return
        self._selected = True
        if langstone:
            MARKER.touch()
            unit = "langstone.service"
            # ★Langstone V3自身は12V電源(GPIO26)に触れないため、起動選択時に
            # ここで明示的にONを送っておく(home.py側のアプリ内Langstoneボタンと
            # 同じ経路。起動メニューから直接Langstoneを選んだ場合はhome.pyの
            # 処理を経由しないため、ここでも送信しないとPA電源が入らない)。
            host = settings_store.load().ptt_controller_host
            if host:
                try:
                    _send_ptt_channel_state(host, PTT_CHANNEL_POWER, "on")
                except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
                    print(f"[MCU1] GPIO26 ON通知に失敗しました(起動メニュー): {exc}", flush=True)
        else:
            MARKER.unlink(missing_ok=True)
            unit = "shonan-gui.service"
        subprocess.run(
            ["sudo", "/bin/systemctl", "start", "--no-block", unit],
            check=False,
        )
        QtCore.QTimer.singleShot(300, QtWidgets.QApplication.quit)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    menu = BootMenu()
    menu.showFullScreen()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
