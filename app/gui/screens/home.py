"""Homeメニュー。Android版 ui/HomeScreen.kt の homeMenuButtons 相当。"""
from __future__ import annotations

import http.client
import subprocess
import urllib.error
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

import platform_compat
from backend import PTT_CHANNEL_POWER, _send_ptt_channel_state
from widgets import NavButton, error_dialog
from i18n import tr


def is_english(settings) -> bool:
    return getattr(settings, "language", "JAPANESE") == "ENGLISH"

_BUTTONS = [
    ("送信", "Transmit", "tx"),
    ("受信", "Receive", "rx"),
    ("周波数", "Frequency", "frequency"),
    ("RSSI測定", "RSSI Measurement", "rssi"),
    ("シンボルレート", "Symbol Rate", "symbolrate"),
    ("誤り訂正", "FEC", "fec"),
    ("変調方式", "Modulation", "modulation"),
    ("映像ソース", "Video Source", "videosource"),
    ("出力設定", "Stream Output", "streamoutput"),
    ("RXゲイン", "RX Gain", "rxgain"),
    ("TX出力", "TX Power", "txpower"),
    ("設定", "Config", "settings"),
    ("機器試験", "Diagnostic", "testequipment"),
    ("ヘルプ", "Help", "manual"),
    ("アプリ再起動", "App Restart", "pluto_reboot"),
    ("アプリ終了", "Exit App", "app_exit"),
    ("Langstone", "SDR Transceiver", "langstone"),
    ("プリセット", "Presets", "presets"),
    ("Pluto電源", "Pluto Power", "pluto_power_cycle"),
]

# ホーム画面カードの文字サイズ(背景画像に元々焼き込まれていた比率に合わせる:
# 日本語は大きく、英語(2行目)は約6割の小さめサイズ、英語UIのみの1行表示は
# 日本語版の英語1行カード(App Restart等)と同じ中間サイズ)。
_CARD_JA_PX = 26
_CARD_EN_SUB_PX = 15
_CARD_EN_ONLY_PX = 22

# Pluto+のdatvplutofrmファームウェアの既定rootクレデンシャル(Dropbear SSH)。
_PLUTO_SSH_USER = "root"
_PLUTO_SSH_PASSWORD = "analog"

# ★Langstone V3(app/third_party/Langstone-V3、g4eml氏のSDRトランシーバー)は
# Qt eglfsとは別に/dev/fb0を直接描画する独立アプリのため、同時稼働はできない。
# shonan-gui.service/langstone.service/shonan-boot-menu.serviceの3つは
# systemdのConflicts=で互いに排他制御されるため、切替はsystemctl startを
# 直接呼ぶだけでよくPi5自体のrebootは不要(app/scripts/install.sh 9/9参照)。
# マーカーファイルはConditionPathExistsとの整合のため引き続き作成/削除する
# (Langstone側の「GOTO SHONAN_LITE」ボタンはこのファイルを削除する。
# app/third_party/Langstone-V3/LangstoneGUI_Pluto.c参照)。
_LANGSTONE_BOOT_MARKER = Path.home() / ".pi5_boot_mode_langstone"


class FecCheckIcon(QtWidgets.QWidget):
    """iPad版FECカードの円囲みチェックアイコン。"""

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        margin = max(1, min(self.width(), self.height()) * 0.08)
        circle = QtCore.QRectF(
            margin, margin, self.width() - margin * 2, self.height() - margin * 2)
        pen = QtGui.QPen(QtGui.QColor("white"), max(1.5, self.width() * 0.07))
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(circle)
        check = QtGui.QPainterPath()
        check.moveTo(self.width() * 0.28, self.height() * 0.52)
        check.lineTo(self.width() * 0.45, self.height() * 0.68)
        check.lineTo(self.width() * 0.74, self.height() * 0.34)
        painter.drawPath(check)
        painter.end()


class PresetCard(QtWidgets.QWidget):
    def __init__(self, parent=None, english: bool = False) -> None:
        super().__init__(parent)
        self._english = english

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.scale(self.width() / 322.0, self.height() / 107.0)
        inner = QtCore.QRectF(4, 4, 314, 99)
        fill = QtGui.QLinearGradient(inner.topLeft(), inner.bottomLeft())
        fill.setColorAt(0.0, QtGui.QColor("#071a2c"))
        fill.setColorAt(1.0, QtGui.QColor("#030b16"))
        painter.setBrush(QtGui.QBrush(fill))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(inner, 12, 12)

        icon_center = QtCore.QPointF(52, 52)
        painter.setPen(QtGui.QPen(QtGui.QColor("white"), 3, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap))
        for y, x in ((icon_center.y() - 12, 45), (icon_center.y(), 58), (icon_center.y() + 12, 49)):
            painter.drawLine(QtCore.QPointF(30, y), QtCore.QPointF(73, y))
            painter.setBrush(QtGui.QBrush(QtGui.QColor("white")))
            painter.drawEllipse(QtCore.QPointF(x, y), 3.5, 3.5)

        # 通常カードの日本語タイトルと同じ見かけの大きさに合わせる。
        painter.setPen(QtGui.QColor("white"))
        if self._english:
            font = QtGui.QFont("Noto Sans CJK JP")
            font.setPixelSize(26)
            font.setStyleStrategy(QtGui.QFont.PreferAntialias)
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(108, 27, 205, 55),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "Presets")
        else:
            font = QtGui.QFont("Noto Sans CJK JP")
            font.setPixelSize(26)
            font.setWeight(QtGui.QFont.Thin)
            font.setStyleStrategy(QtGui.QFont.PreferAntialias)
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(108, 27, 205, 30),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "プリセット")
            small_font = QtGui.QFont("Noto Sans CJK JP")
            small_font.setPixelSize(16)
            small_font.setWeight(QtGui.QFont.Thin)
            small_font.setStyleStrategy(QtGui.QFont.PreferAntialias)
            painter.setFont(small_font)
            painter.drawText(QtCore.QRectF(108, 56, 205, 25),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "Presets")
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor("#247f9f"), 2))
        painter.drawRoundedRect(QtCore.QRectF(1, 1, 320, 105), 15, 15)
        painter.end()


class PlutoPowerCard(QtWidgets.QWidget):
    """PresetCardと同様、モック画像上の空きスロットに描画する電源サイクルカード。"""

    def __init__(self, parent=None, english: bool = False) -> None:
        super().__init__(parent)
        self._english = english

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.scale(self.width() / 298.0, self.height() / 111.0)
        inner = QtCore.QRectF(4, 4, 290, 103)
        fill = QtGui.QLinearGradient(inner.topLeft(), inner.bottomLeft())
        fill.setColorAt(0.0, QtGui.QColor("#071a2c"))
        fill.setColorAt(1.0, QtGui.QColor("#030b16"))
        painter.setBrush(QtGui.QBrush(fill))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawRoundedRect(inner, 12, 12)

        # 電源アイコン(上部を開けた円弧+縦線。他画面の電源オフダイアログと同系統)。
        icon_center = QtCore.QPointF(48, 55)
        radius = 20.0
        pen = QtGui.QPen(QtGui.QColor("white"), 3, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        arc_rect = QtCore.QRectF(icon_center.x() - radius, icon_center.y() - radius,
                                  radius * 2, radius * 2)
        painter.drawArc(arc_rect, 100 * 16, 340 * 16)
        painter.drawLine(QtCore.QPointF(icon_center.x(), icon_center.y() - radius - 4),
                          QtCore.QPointF(icon_center.x(), icon_center.y() - 2))

        # 文字サイズ・開始位置は「アプリ再起動」カード(モック画像に焼き込み済み)を
        # 実測して合わせた(タイトル約30px、テキスト開始x=108は他カードと共通)。
        painter.setPen(QtGui.QColor("white"))
        if self._english:
            font = QtGui.QFont("Noto Sans CJK JP")
            font.setPixelSize(30)
            font.setStyleStrategy(QtGui.QFont.PreferAntialias)
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(108, 22, 185, 34),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "Pluto Power")
            small_font = QtGui.QFont("Noto Sans CJK JP")
            small_font.setPixelSize(18)
            small_font.setStyleStrategy(QtGui.QFont.PreferAntialias)
            painter.setFont(small_font)
            painter.drawText(QtCore.QRectF(108, 58, 185, 26),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "Power Cycle")
        else:
            font = QtGui.QFont("Noto Sans CJK JP")
            font.setPixelSize(30)
            font.setWeight(QtGui.QFont.Thin)
            font.setStyleStrategy(QtGui.QFont.PreferAntialias)
            painter.setFont(font)
            painter.drawText(QtCore.QRectF(108, 22, 185, 34),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "Pluto電源")
            small_font = QtGui.QFont("Noto Sans CJK JP")
            small_font.setPixelSize(18)
            small_font.setWeight(QtGui.QFont.Thin)
            small_font.setStyleStrategy(QtGui.QFont.PreferAntialias)
            painter.setFont(small_font)
            painter.drawText(QtCore.QRectF(108, 58, 185, 26),
                             QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, "OFF→ON")
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setPen(QtGui.QPen(QtGui.QColor("#247f9f"), 2))
        painter.drawRoundedRect(QtCore.QRectF(1, 1, 296, 109), 15, 15)
        painter.end()


class HomeScreen(QtWidgets.QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setStyleSheet("background-color: black;")
        self._mock_mode = False
        self._mock_canvas = None
        self._freq_value_label = None

        if self._build_illustrated_home():
            return

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 10)
        outer.setSpacing(6)

        _platform_label = "Windows" if platform_compat.IS_WINDOWS else "RasPI5"
        title = QtWidgets.QLabel(
            f"Shonan_Lite <span style='font-size:9pt;'>for</span> {_platform_label}"
        )
        title.setStyleSheet(
            "color: white; font-size: 17pt; font-weight: bold; font-style: italic; "
            "font-family: 'DejaVu Serif', 'Times New Roman', serif;")
        title.setAlignment(QtCore.Qt.AlignLeft)
        outer.addWidget(title)

        subtitle = QtWidgets.QLabel("DVB-S2 DATV TRANSCEIVER")
        subtitle.setStyleSheet(
            "color: #8f9aaa; font-size: 9px; letter-spacing: 1px; "
            "font-weight: bold; padding-left: 2px;")
        outer.addWidget(subtitle)

        menu_panel = QtWidgets.QFrame()
        menu_panel.setObjectName("homeMenuPanel")
        menu_panel.setStyleSheet(
            "QFrame#homeMenuPanel { background-color: #11161d; "
            "border: 1px solid #293442; border-radius: 18px; }")
        panel_layout = QtWidgets.QVBoxLayout(menu_panel)
        panel_layout.setContentsMargins(14, 10, 14, 14)
        panel_layout.setSpacing(8)
        main_menu_label = QtWidgets.QLabel("Main Menu")
        main_menu_label.setStyleSheet(
            "color: #e9edf3; font-size: 13pt; font-weight: bold; "
            "padding-left: 3px;")
        panel_layout.addWidget(main_menu_label)

        grid_widget = QtWidgets.QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid = QtWidgets.QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self._buttons = {}
        for i, (ja, en, route) in enumerate(_BUTTONS):
            btn = NavButton(ja, en)
            if route == "app_exit":
                btn.clicked.connect(self._on_app_exit_clicked)
            elif route == "pluto_reboot":
                btn.clicked.connect(self._on_app_restart_clicked)
            elif route == "langstone":
                btn.clicked.connect(self._on_langstone_clicked)
            elif route == "tx":
                # ホームの「送信」は送信画面を開くだけにする。
                # 実際の送信開始はTxScreenの「送信開始」ボタンでのみ行う。
                btn.clicked.connect(self._on_transmit_clicked)
            elif route == "pluto_power_cycle":
                btn.clicked.connect(self._on_pluto_power_cycle_clicked)
            else:
                btn.clicked.connect(lambda _, r=route: self.main_window.navigate_to(r))
            self._buttons[route] = btn
            grid.addWidget(btn, i // 4, i % 4, QtCore.Qt.AlignTop | QtCore.Qt.AlignHCenter)
        panel_layout.addWidget(grid_widget, 1)
        outer.addWidget(menu_panel, 1)

        datv_label = QtWidgets.QLabel("Digital Amateur TV System (DATV)")
        datv_label.setStyleSheet("color: white; font-size: 8pt;")
        datv_label.setAlignment(QtCore.Qt.AlignRight)
        outer.addWidget(datv_label)

    def _add_card_label(self, canvas, japanese: str, english_text: str, rect,
                         english_only: bool) -> QtWidgets.QLabel:
        """背景画像に焼き込まれたカード文字を隠し、Qtで描画し直す。

        日本語UIでは「日本語(大)+英語(小)」の2行、英語UIでは英語1行のみを表示し、
        全カードで同じフォントサイズ比になるようにする(_position_mock_home()で
        キャンバスサイズに応じてpxを再計算する)。
        """
        label = QtWidgets.QLabel(canvas)
        label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        label.setStyleSheet("QLabel { background-color: rgba(3, 16, 34, 255); padding-left: 4px; }")
        label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        label._mock_rect = rect
        label._card_japanese = japanese
        label._card_english = english_text
        label._card_english_only = english_only
        self._mock_overlays.append(label)
        self._card_labels.append(label)
        return label

    def _build_illustrated_home(self) -> bool:
        """モック画像を表示し、その上に透明な実ボタンを重ねる。

        画像が配備されていない開発環境では従来のカードUIへフォールバックする。
        モックのカード文字・アイコンを背景として使うため、見た目を一致させながら
        タッチ領域だけをQtの実ボタンとして維持できる。
        """
        english = is_english(self.main_window.settings)
        images_dir = platform_compat.app_dir() / "docs" / "images"
        image_path = images_dir / "home_illustrated_mockup_en.png" if english \
            else images_dir / "home_illustrated_mockup.png"
        if not image_path.exists():
            image_path = images_dir / "home_illustrated_mockup.png"
        if not image_path.exists():
            return False

        self._mock_mode = True
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        canvas = QtWidgets.QWidget(self)
        canvas.setStyleSheet("background-color: black;")
        self._mock_canvas = canvas
        background = QtWidgets.QLabel(canvas)
        bg_pixmap = QtGui.QPixmap(str(image_path))
        background.setPixmap(bg_pixmap)
        background.setScaledContents(True)
        background.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self._mock_background = background
        # ★オーバーレイ座標(_mock_rect)は実ファイルのピクセル寸法を基準に実測した
        # ものなので、スケーリングの基準も実際の画像サイズを使う(以前は1600x1024を
        # 決め打ちしていたが、実ファイルは1568x1018で約2%ずれ、右下に行くほど
        # 誤差が蓄積してカード背景の旧文字を隠しきれていなかった)。
        self._mock_native_size = (bg_pixmap.width(), bg_pixmap.height())

        # 背景画像に埋め込まれた旧FEC表示を一度隠し、iPad版のアイコンと文字を描く。
        # フォントサイズは背景画像に焼き込んだタイトル文字と見かけの大きさを
        # 揃えるため、_position_mock_home()でキャンバスの実サイズに応じて
        # 都度設定し直す(self._scaled_font_labelsに登録)。
        self._mock_overlays = []
        self._scaled_font_labels = []
        self._card_labels = []

        # 背景画像に焼き込まれたタイトル「Shonan_Lite for RasPI5」はWindows版でも
        # 共通のモック画像を使い回すため、Windows実行時のみ黒帯で隠して
        # 「Shonan_Lite for Windows」に差し替える(restart_label等と同じ手法)。
        if platform_compat.IS_WINDOWS:
            title_clear = QtWidgets.QLabel(canvas)
            title_clear.setStyleSheet("background-color: black;")
            title_clear.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            title_clear._mock_rect = (40, 15, 860, 100)
            self._mock_overlays.append(title_clear)

            title_label = QtWidgets.QLabel(canvas)
            # ★font-family/style/weightだけをQSSで指定し、setFont()でpx指定すると、
            # main.pyのアプリ全体スタイルシート(QWidget { font-size: 14px; })の
            # font-size宣言がQFont側の指定より優先され、実機Windowsでは既定の
            # 小さいフォントサイズへ戻ってしまう(実機で確認済みの不具合)。
            # ウィジェット自身のQSSにfont-sizeも明示することで回避する
            # (_position_mock_home()で毎回font-size込みで再設定する)。
            title_label._base_qss = (
                "QLabel { color: white; font-family: 'Times New Roman'; "
                "font-style: italic; font-weight: bold;")
            title_label.setStyleSheet(title_label._base_qss + " }")
            title_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            title_label._mock_rect = (40, 15, 860, 100)
            # 文字サイズはキャンバス幅に応じて_position_mock_home()側で設定する。
            # ★77pxだと"Shonan_Lite for Windows"の実測幅が832pxとなり、rect幅を
            # 超えて末尾の"s"が欠ける(実機で確認)。74pxなら実測約800pxに収まる。
            title_label._mock_title_base_px = 74
            self._mock_overlays.append(title_label)
            self._title_label = title_label

        # ★旧「Pluto再起動/Pluto Reboot」の文字部分だけを覆う。カード全体
        # (752,587,298,111)ぴったりに合わせると、白い矩形の角がカードの丸みを
        # 帯びた枠線にかぶさって「外枠が欠けて見える」ため、枠線には触れない
        # 内側だけを覆う(実機で確認済みの不具合)。
        self._add_card_label(canvas, "アプリ再起動", "App Restart", (824, 592, 204, 94), english)

        # 背景画像に焼き込まれた旧「電源オフ/Power Off」表示を隠し、
        # 「アプリ終了/Exit App」に差し替える(restart_labelと同じ理由で内側だけを覆う)。
        self._add_card_label(canvas, "アプリ終了", "Exit App", (1150, 594, 170, 80), english)

        # 背景画像に焼き込まれた旧「相手局検索/Find Station」表示を隠し、
        # 「RSSI測定/RSSI」に差し替える。アイコン(虫眼鏡)は焼き込みのまま流用し、
        # 文字部分だけを覆う。他カードとフォントサイズを揃えるため、カードが
        # 狭く"RSSI Measurement"は収まらないので"RSSI"に短縮する(正式名称は
        # 遷移先画面のタイトル・マニュアルに表示される)。
        self._add_card_label(canvas, "RSSI測定", "RSSI", (1145, 197, 168, 86), english)

        fec_icon = FecCheckIcon(canvas)
        fec_icon.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        # 上下のカードと同じ左寄せ基準へ合わせる。
        fec_icon._mock_rect = (450, 349, 44, 44)
        self._mock_overlays.append(fec_icon)

        # ★旧「FEC/FEC」の文字・アイコン部分だけを覆う(restart_labelと同じ理由で
        # カード全体(414,320,315,111)ぴったりには合わせない)。
        fec_clear = QtWidgets.QLabel(canvas)
        fec_clear.setStyleSheet("background-color: rgba(3, 16, 34, 255);")
        fec_clear.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        fec_clear._mock_rect = (420, 326, 100, 82)
        self._mock_overlays.append(fec_clear)
        fec_icon.raise_()

        self._add_card_label(canvas, "誤り訂正", "FEC", (505, 337, 160, 72), english)

        # 背景画像に焼き込まれた他のカード文字も同じ手法でQt描画へ統一し、
        # 全カードでフォント・サイズ比(日本語大・英語小)を揃える。
        for route, rect in {
            "tx": (162, 197, 206, 86),
            "rx": (499, 197, 204, 86),
            "symbolrate": (162, 329, 206, 86),
            "modulation": (840, 329, 183, 86),
            "videosource": (1145, 329, 168, 86),
            "streamoutput": (162, 463, 206, 86),
            "rxgain": (499, 463, 204, 86),
            "txpower": (840, 463, 183, 86),
            "settings": (1144, 463, 169, 86),
            "testequipment": (162, 596, 206, 85),
            "manual": (499, 596, 204, 85),
        }.items():
            ja, en = next((b[0], b[1]) for b in _BUTTONS if b[2] == route)
            self._add_card_label(canvas, ja, en, rect, english)

        # 「周波数」カードのタイトル部分(値の上の行)を他カードと同じ手法・
        # サイズ比でQt描画へ差し替える。値表示部分(下記freq_value_label)には
        # かからない高さに抑える。
        self._add_card_label(canvas, "周波数", "Frequency", (840, 197, 183, 54), english)

        # 背景画像に焼き込まれた「周波数」カードのプレースホルダー値「437000 kHz」
        # (グロー込みの実測x818-1013,y255-288程度)を隠し、on_show()で実際の設定値に
        # 差し替える(以前はこのカードだけ動的更新の仕組みが無く、常に
        # モック画像の固定値が表示されていた不具合)。
        freq_clear = QtWidgets.QLabel(canvas)
        freq_clear.setStyleSheet("background-color: rgba(3, 16, 34, 245);")
        freq_clear.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        freq_clear._mock_rect = (846, 256, 172, 32)
        self._mock_overlays.append(freq_clear)

        freq_value_label = QtWidgets.QLabel(canvas)
        freq_value_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        freq_value_label._base_qss = "QLabel { background: transparent; color: white; padding-left: 4px;"
        freq_value_label.setStyleSheet(freq_value_label._base_qss + " }")
        freq_value_label.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        freq_value_label._mock_rect = (846, 256, 172, 32)
        self._mock_overlays.append(freq_value_label)
        self._scaled_font_labels.append((freq_value_label, 18))
        self._freq_value_label = freq_value_label

        # Windows版はLangstone実機/Pluto+電源制御に対応しないため、Langstone・
        # プリセット・Pluto電源カードそのものを表示しない。
        if platform_compat.IS_WINDOWS:
            # 背景画像は完全な黒ではなく僅かに明るいグラデーション(vignette)のため、
            # 純黒(#000)で覆うと縁が浮いて見える。周囲と同じ色を画像から実測して使う。
            bg_image = QtGui.QImage(str(image_path))
            sample_color = QtGui.QColor(
                bg_image.pixel(round(55 * bg_image.width() / 1600),
                               round(715 * bg_image.height() / 1024))
            )
            langstone_clear = QtWidgets.QLabel(canvas)
            langstone_clear.setStyleSheet(f"background-color: {sample_color.name()};")
            langstone_clear.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            # ★カード枠線が実際の座標よりわずかに外側にはみ出すため、余白を持たせて
            # 隠す。特に上端はy=721付近から枠線の光が始まっており、722では
            # 1〜3px隠しきれず細い線が残っていた(実機で確認済みの不具合)。
            langstone_clear._mock_rect = (62, 717, 334, 128)
            self._mock_overlays.append(langstone_clear)
        else:
            preset_card = PresetCard(canvas, english=english)
            preset_card.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            preset_card._mock_rect = (414, 728, 322, 111)
            self._mock_overlays.append(preset_card)

            # 「Langstone」「プリセット」の右側(752,728)はモック画像上まだ空きスロットの
            # ため、PresetCardと同じ要領でPlutoPowerCardを描画する。
            pluto_power_card = PlutoPowerCard(canvas, english=english)
            pluto_power_card.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
            pluto_power_card._mock_rect = (752, 728, 298, 111)
            self._mock_overlays.append(pluto_power_card)

        # 座標は1600x1024のモック画像上。実画面サイズに応じてresizeEventで縮放する。
        card_rects = [
            (68, 186, 322, 111), (414, 186, 315, 111), (752, 186, 298, 111), (1075, 186, 267, 111),
            (68, 320, 322, 111), (414, 320, 315, 111), (752, 320, 298, 111), (1075, 320, 267, 111),
            (68, 454, 322, 111), (414, 454, 315, 111), (752, 454, 298, 111), (1075, 454, 267, 111),
            (68, 587, 322, 111), (414, 587, 315, 111), (752, 587, 298, 111), (1075, 587, 267, 111),
            (68, 728, 322, 111), (414, 728, 322, 111), (752, 728, 298, 111),
        ]
        _windows_hidden_routes = {"langstone", "presets", "pluto_power_cycle"}
        self._buttons = {}
        for (ja, en, route), rect in zip(_BUTTONS, card_rects):
            if platform_compat.IS_WINDOWS and route in _windows_hidden_routes:
                continue
            btn = QtWidgets.QPushButton(canvas)
            btn.setFocusPolicy(QtCore.Qt.NoFocus)
            btn.setToolTip(f"{ja} / {en}")
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none; }"
                "QPushButton:pressed { background: rgba(50, 110, 220, 45); border: 2px solid #4d8dff; }"
            )
            self._connect_home_action(btn, route)
            self._buttons[route] = btn
            btn._mock_rect = rect
        outer.addWidget(canvas, 1)
        self._position_mock_home()
        return True

    def _connect_home_action(self, btn: QtWidgets.QPushButton, route: str) -> None:
        if route == "app_exit":
            btn.clicked.connect(self._on_app_exit_clicked)
        elif route == "pluto_reboot":
            btn.clicked.connect(self._on_app_restart_clicked)
        elif route == "langstone":
            btn.clicked.connect(self._on_langstone_clicked)
        elif route == "tx":
            btn.clicked.connect(self._on_transmit_clicked)
        elif route == "pluto_power_cycle":
            btn.clicked.connect(self._on_pluto_power_cycle_clicked)
        else:
            btn.clicked.connect(lambda _, r=route: self.main_window.navigate_to(r))

    def _position_mock_home(self) -> None:
        if self._mock_canvas is None:
            return
        width = max(1, self._mock_canvas.width())
        height = max(1, self._mock_canvas.height())
        # ★_mock_rect群は実ファイル(1568x1018)のピクセル座標を実測したものなので、
        # 拡縮の基準も決め打ちの1600x1024ではなく実際の画像サイズを使う
        # (以前は約2%小さく計算されてしまい、右下に行くほど誤差が蓄積して
        # カード背景の旧文字を隠しきれていなかった)。
        native_w, native_h = getattr(self, "_mock_native_size", (1600, 1024))
        self._mock_background.setGeometry(0, 0, width, height)
        for overlay in self._mock_overlays:
            x, y, w, h = overlay._mock_rect
            overlay.setGeometry(round(x * width / native_w), round(y * height / native_h),
                                round(w * width / native_w), round(h * height / native_h))
        for btn in self._buttons.values():
            x, y, w, h = btn._mock_rect
            btn.setGeometry(round(x * width / native_w), round(y * height / native_h),
                            round(w * width / native_w), round(h * height / native_h))
        # 背景画像に焼き込んだタイトル文字も画面サイズに応じて拡大縮小されるため、
        # このオーバーレイの文字サイズもキャンバス幅に比例させて見かけを揃える。
        # ★font-sizeはラベル自身のQSSに明示する(main.pyのアプリ全体スタイル
        # シート QWidget { font-size: 14px; } がQFont.setPixelSize()より優先されて
        # しまい、実機Windowsでは既定の小さいサイズへ戻ってしまうため)。
        for label, base_px in getattr(self, "_scaled_font_labels", []):
            px = max(10, round(base_px * width / native_w))
            label.setStyleSheet(f"{label._base_qss} font-size: {px}px; }}")

        # ホームカードの文字(_add_card_label): 日本語UIは「日本語(大)+英語(小)」の
        # 2行、英語UIは英語1行のみをリッチテキストで描画し、全カードで同じ
        # フォントサイズ比になるようにする。
        for label in getattr(self, "_card_labels", []):
            if label._card_english_only:
                px = max(10, round(_CARD_EN_ONLY_PX * width / native_w))
                label.setTextFormat(QtCore.Qt.RichText)
                label.setText(f'<span style="color:white; font-size:{px}px;">'
                              f'{label._card_english}</span>')
            else:
                px_ja = max(10, round(_CARD_JA_PX * width / native_w))
                px_en = max(8, round(_CARD_EN_SUB_PX * width / native_w))
                label.setTextFormat(QtCore.Qt.RichText)
                label.setText(f'<span style="color:white; font-size:{px_ja}px;">'
                              f'{label._card_japanese}</span><br>'
                              f'<span style="color:white; font-size:{px_en}px;">'
                              f'{label._card_english}</span>')

        title_label = getattr(self, "_title_label", None)
        if title_label is not None:
            # 実機Pi5では"for"は他の文字と同じ大きさで表示されるため、
            # spanで縮小せず統一サイズにする。
            title_px = max(10, round(title_label._mock_title_base_px * width / native_w))
            title_label.setText("Shonan_Lite for Windows")
            title_label.setStyleSheet(f"{title_label._base_qss} font-size: {title_px}px; }}")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_mock_home()

    def _on_transmit_clicked(self) -> None:
        """送信画面へ移動するだけで、TXプロセスは起動しない。"""
        self.main_window.navigate_to("tx")

    def _on_app_exit_clicked(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(tr("アプリ終了", "Exit App"))
        dialog.setModal(True)
        dialog.setFixedSize(560, 320)
        dialog.setStyleSheet("QDialog { background: #101416; color: white; } QLabel { color: white; }")
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(12)
        icon = QtWidgets.QLabel("⏻")
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setStyleSheet("color: #f05a45; font-size: 72px; font-weight: bold;")
        layout.addWidget(icon)
        message = QtWidgets.QLabel(tr("アプリを終了します。\nよろしいですか？", "The app will exit.\nAre you sure?"))
        message.setAlignment(QtCore.Qt.AlignCenter)
        message.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(message)
        buttons = QtWidgets.QHBoxLayout()
        exit_btn = QtWidgets.QPushButton(tr("アプリを終了する", "Exit"))
        cancel = QtWidgets.QPushButton(tr("キャンセル", "Cancel"))
        exit_btn.setMinimumHeight(44)
        cancel.setMinimumHeight(44)
        exit_btn.setStyleSheet("QPushButton { background: #f05a45; color: white; border: none; border-radius: 6px; padding: 6px 18px; font-weight: bold; }")
        cancel.setStyleSheet("QPushButton { color: white; border: 1px solid #3b5159; border-radius: 6px; padding: 6px 18px; font-weight: bold; }")
        exit_btn.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        buttons.addWidget(exit_btn)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        # ★システムのshutdownは呼ばず、アプリのプロセスのみを終了する
        # (closeEvent側でTX/RX停止・MCU1のGPIO26 OFF通知まで行う)。
        # shonan-gui.serviceはRestart=on-failureのため、正常終了(exit code 0)
        # では自動再起動されない。
        self.main_window.close()

    def _on_pluto_reboot_clicked(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(tr("Pluto再起動", "Restart Pluto"))
        dialog.setModal(True)
        dialog.setFixedSize(560, 320)
        dialog.setStyleSheet("QDialog { background: #101416; color: white; } QLabel { color: white; }")
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(12)
        icon = QtWidgets.QLabel("⟳")
        icon.setAlignment(QtCore.Qt.AlignCenter)
        icon.setStyleSheet("color: #0c9bc0; font-size: 72px; font-weight: bold;")
        layout.addWidget(icon)
        message = QtWidgets.QLabel(tr("Pluto SDRを再起動します。\nよろしいですか？", "Pluto SDR will restart.\nAre you sure?"))
        message.setAlignment(QtCore.Qt.AlignCenter)
        message.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(message)
        buttons = QtWidgets.QHBoxLayout()
        reboot = QtWidgets.QPushButton(tr("再起動する", "Restart"))
        cancel = QtWidgets.QPushButton(tr("キャンセル", "Cancel"))
        for button in (reboot, cancel):
            button.setMinimumHeight(44)
            button.setStyleSheet("QPushButton { border: 1px solid #3b5159; border-radius: 6px; padding: 6px 18px; font-weight: bold; } QPushButton:pressed { background: #0c9bc0; }")
            buttons.addWidget(button)
        reboot.setStyleSheet("QPushButton { background: #0c9bc0; color: white; border: none; border-radius: 6px; padding: 6px 18px; font-weight: bold; }")
        reboot.clicked.connect(dialog.accept)
        cancel.clicked.connect(dialog.reject)
        layout.addLayout(buttons)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._reboot_pluto()
        except OSError as exc:
            error_dialog(self, tr("Pluto再起動失敗", "Pluto Restart Failed"), str(exc))

    def _on_pluto_power_cycle_clicked(self) -> None:
        """PA_Power/PTTコントローラ(ESP32)のGPIO26(12V電源)をOFF→3秒待ち→ONする
        (Pluto+含む12V系統全体の電源サイクル)。"""
        host = self.main_window.settings.ptt_controller_host
        if not host:
            error_dialog(
                self, tr("PTTコントローラ未設定", "PTT Controller Not Set"),
                tr("設定画面でPA_Power/PTTコントローラ(ESP32)のIPアドレスを設定してください。",
                   "Set the IP address of the PA_Power/PTT controller (ESP32) on the Settings screen."))
            return
        try:
            _send_ptt_channel_state(host, PTT_CHANNEL_POWER, "off")
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            error_dialog(self, tr("Pluto電源OFF失敗", "Pluto Power OFF Failed"), str(exc))
            return
        QtCore.QTimer.singleShot(3000, lambda: self._pluto_power_on(host))

    def _pluto_power_on(self, host: str) -> None:
        try:
            _send_ptt_channel_state(host, PTT_CHANNEL_POWER, "on")
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            error_dialog(self, tr("Pluto電源ON失敗", "Pluto Power ON Failed"), str(exc))

    def _on_app_restart_clicked(self) -> None:
        """iPad版と同じソフトリスタートをMainWindowへ依頼する。"""
        self.main_window.restart_app()

    def _on_langstone_clicked(self) -> None:
        try:
            # ★以前はPi5自体もrebootしていたが、shonan-boot-menu.service導入後は
            # shonan-gui.service/langstone.service/shonan-boot-menu.serviceが
            # systemdのConflicts=で互いに排他制御されるため、systemctl startを
            # 直接呼ぶだけで切り替わる(Pi5自体はrebootしない。呼び出すと現在
            # 稼働中のこのプロセス自体はsystemdに自動停止される)。Pluto+側だけは
            # 切替のたびに必ずreboot して、IIOコンテキストが詰まった状態のまま
            # Langstone側のGNU Radioフローグラフが起動しない不具合(実機で確認)を
            # 避ける。
            try:
                self._reboot_pluto(wait=True)
            except subprocess.TimeoutExpired:
                pass  # 届いていなくても切替は進める
            # ★Langstone V3自身は12V電源(GPIO26)に触れないため、切替時に
            # ここで明示的にONを送っておく(Langstone側の送信でPA電源が
            # 入っていない、という事態を避ける)。
            host = self.main_window.settings.ptt_controller_host
            if host:
                try:
                    _send_ptt_channel_state(host, PTT_CHANNEL_POWER, "on")
                except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
                    print(f"[MCU1] GPIO26 ON通知に失敗しました(Langstone切替): {exc}", flush=True)
            _LANGSTONE_BOOT_MARKER.touch()
            subprocess.Popen(["sudo", "/bin/systemctl", "start", "--no-block", "langstone.service"])
        except OSError as exc:
            error_dialog(self, tr("Langstone起動失敗", "Langstone Start Failed"), str(exc))

    def _reboot_pluto(self, wait: bool = False) -> None:
        # ★アプリ切替時にPluto+を毎回rebootして必ずクリーンな状態にする。
        # Pluto+はTX/RXを繰り返した後、IIOコンテキストが詰まったような状態
        # (fmcomms2_source: Unable to refill buffer: Connection timed out)
        # になることがあり、その状態のままLangstone側のGNU Radioフローグラフを
        # 起動すると永久に「Restarting GNU Radio」を繰り返し動作しない
        # (実機で確認・Pluto+ rebootで解消)。
        pluto_uri = self.main_window.settings.pluto_uri
        prefix = "ip:"
        host = pluto_uri[len(prefix):] if pluto_uri.startswith(prefix) else pluto_uri
        if platform_compat.IS_WINDOWS:
            # WindowsにはsshpassでSSHパスワード認証を自動化する慣習が無いため、
            # platform_compat.reboot_pluto()がparamikoで直接同じ操作を行う。
            # wait=Trueの意味(送信完了まで待つ)もそのまま踏襲する。
            platform_compat.reboot_pluto(host, wait=wait, timeout=10)
            return
        cmd = [
            "sshpass", "-p", _PLUTO_SSH_PASSWORD,
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ConnectTimeout=6",
            "-o", "PreferredAuthentications=password",
            "-o", "PubkeyAuthentication=no",
            f"{_PLUTO_SSH_USER}@{host}",
            "reboot",
        ]
        if wait:
            # Langstone起動直後、Conflicts=によりこのshonan-gui.serviceプロセス
            # 自体がsystemdに停止させられる(Pi5自体はrebootしない)。停止される
            # 前にSSHコマンドの送信が完了する(=実際にPluto+へ届く)ことを保証する
            # ためここで待つ。接続失敗時も(最大ConnectTimeout=6秒程度で)
            # 戻ってきてから先へ進む。
            subprocess.run(cmd, timeout=10)
        else:
            subprocess.Popen(cmd)

    def on_show(self) -> None:
        settings = self.main_window.settings
        lo_hz = settings.effective_lo_hz()
        if lo_hz is not None:
            text = f"{lo_hz / 1000:.0f} kHz"
        else:
            text = "Not Set" if is_english(settings) else "未設定"
        if self._mock_mode:
            if self._freq_value_label is not None:
                self._freq_value_label.setText(text)
            return
        self._buttons["frequency"].set_subtitle(text)


def create(main_window) -> QtWidgets.QWidget:
    return HomeScreen(main_window)
