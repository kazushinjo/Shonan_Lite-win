"""共通UIウィジェット。Android版 ui/SettingsWidgets.kt のPyQt5移植。

タッチ操作前提(現状Pi5ではタッチデバイス`ft5x06`をevdev/libinput経由でQtが拾う想定、
未検出時はマウス/キーボードでも操作できるよう、ボタン等は十分大きいタッチターゲットにする)。
"""
from __future__ import annotations

from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QScroller

from i18n import bilingual, is_english, tr

TOUCH_MIN_HEIGHT = 56
FONT_SIZE_TITLE = 29
FONT_SIZE_BODY = 14


def dpi_scaled_pixmap(pixmap: QtGui.QPixmap, target_widget: QtWidgets.QWidget) -> QtGui.QPixmap:
    """target_widget(QLabel等)へそのままsetPixmap()できる、HiDPI対応済みのpixmapを返す。

    ★Windowsのディスプレイ拡大率(100%以外、125%/150%等)が有効な環境で、
    `pixmap.scaled(label.size(), ...)` の結果をそのまま`setPixmap()`すると、
    結果のpixmapのdevicePixelRatio()が既定の1.0のままになる。これをHiDPI画面へ
    描画すると実際のラベル表示枠より大きく描画され、映像の四隅が枠外にクロップ
    される不具合が実機(拡大率125%)で確認された。scaled()の目標サイズを物理
    ピクセル数(論理サイズ×devicePixelRatioF())にした上で、結果のpixmap自体にも
    同じdevicePixelRatioを設定することで、拡大率が何%でも自動的に正しいサイズで
    表示される(100%環境では dpr=1.0 のため従来と同じ挙動)。"""
    dpr = target_widget.devicePixelRatioF()
    target_size = target_widget.size() * dpr
    scaled = pixmap.scaled(target_size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    return scaled


class NavButton(QtWidgets.QPushButton):
    """Home画面のメニューグリッド等で使う大型ボタン。"""

    def __init__(self, label_ja: str, label_en: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        # ★QGridLayoutはセル内でQPushButtonのsizeHintいっぱいまで場所を使うため、
        # setSpacing()でセル間隔を広げただけではボタン自体は縮まず隙間が見えなかった
        # (setMaximumHeight+AlignTopでも実機で変化なしを確認済み)。
        # font-size/paddingを縮小してsizeHint自体を小さくし、setFixedHeightで
        # 高さを確定させることで確実に隙間ができるようにする。
        self.setFixedHeight(58)
        self.setFixedWidth(172)
        # ★Qtの既定スタイルはQPushButtonにフォーカスリング(太い枠)を描画する。
        # border:noneだけでは消えないため、outline:noneと共にフォーカスポリシー自体を
        # 無効化する(タッチ操作のみのキオスク用途でキーボードフォーカス表示は不要)。
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setStyleSheet(
            "QPushButton {"
            "  font-size: 12px; font-weight: bold; padding: 2px;"
            "  background-color: #172758; color: white;"
            "  border: 1px solid #263b7e; border-radius: 10px; outline: none;"
            "}"
            "QPushButton:pressed { background-color: #0c1638; border-color: #4d7cff; }"
            "QPushButton:focus { border: none; outline: none; }"
        )
        self._label_ja = label_ja
        self._label_en = label_en
        self.set_subtitle(subtitle)

    def set_subtitle(self, subtitle: str) -> None:
        text = self._label_en if is_english() else f"{self._label_ja}\n{self._label_en}"
        if subtitle:
            text += f"\n{subtitle}"
        self.setText(text)


class RadioOptionRow(QtWidgets.QWidget):
    """1つのラジオボタン行。ui/SettingsWidgets.kt RadioOptionRow相当。

    compact=Trueで行間・高さを詰める(800x480の小画面で選択肢数が多く、
    既定サイズだとスクロールが必要になる画面向け)。
    """

    def __init__(self, label: str, checked: bool, on_select: Callable[[], None], parent=None,
                 compact: bool = False):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0) if compact else layout.setContentsMargins(4, 4, 4, 4)
        self.radio = QtWidgets.QRadioButton(label)
        self.radio.setMinimumHeight(52 if compact else TOUCH_MIN_HEIGHT)
        self.radio.setStyleSheet(f"font-size: {FONT_SIZE_BODY}px;")
        self.radio.setChecked(checked)
        self.radio.toggled.connect(lambda checked: on_select() if checked else None)
        layout.addWidget(self.radio)
        layout.addStretch(1)


class MemoNote(QtWidgets.QLabel):
    """記録専用(実機制御なし)であることを示す注記。ui/SettingsWidgets.kt OperationalMemoNote相当。"""

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet("color: #888888; font-size: 12px; padding: 4px;")


class SettingsSubScreen(QtWidgets.QWidget):
    """設定系サブ画面の共通スキャフォールド: タイトルバー+戻るボタン+スクロール可能な本体。

    ui/SettingsWidgets.kt SettingsSubScreen相当。サブクラスは self.body_layout に
    ウィジェットを追加する。
    """

    def __init__(self, title: str, on_back: Callable[[], None], parent=None,
                 background: str = "#070808"):
        super().__init__(parent)
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QtWidgets.QWidget()
        self.header_bar = bar
        bar.setStyleSheet("background-color: #191d1f;")
        bar_layout = QtWidgets.QHBoxLayout(bar)
        back_btn = QtWidgets.QPushButton(tr("ホームに戻る", "Back to Home"))
        back_btn.setMinimumSize(100, TOUCH_MIN_HEIGHT)
        back_btn.setStyleSheet(f"font-size: {FONT_SIZE_TITLE}px; font-weight: bold;")
        back_btn.clicked.connect(on_back)
        bar_layout.addWidget(back_btn)
        title_label = QtWidgets.QLabel(bilingual(title))
        title_label.setStyleSheet(f"color: white; font-size: {FONT_SIZE_TITLE}px; font-weight: bold;")
        bar_layout.addWidget(title_label, 1)
        outer.addWidget(bar)

        scroll = QtWidgets.QScrollArea()
        self.scroll_area = scroll
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        body.setObjectName("settingsBody")
        body.setStyleSheet(
            f"QWidget#settingsBody {{ background: {background}; }}"
            "QLabel { color: #eeeeee; font-size: 16px; }"
            "QPushButton { background-color: #080808; color: white;"
            " border: 1px solid #4b5357; border-radius: 8px;"
            " padding: 8px 12px; font-weight: bold; min-height: 52px; }"
            "QPushButton:pressed { background-color: #1677ff; }"
            "QLineEdit, QComboBox, QDateTimeEdit { background-color: #252a2d;"
            " color: white; border: 1px solid #4b5357; border-radius: 8px;"
            " padding: 8px; min-height: 42px; }"
            "QSlider { min-height: 40px; }"
            "QCheckBox { color: white; min-height: 52px; }"
        )
        self.body_layout = QtWidgets.QVBoxLayout(body)
        self.body_layout.setContentsMargins(16, 16, 16, 16)
        self.body_layout.setSpacing(12)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # ★QScrollAreaは既定ではタッチのドラッグスクロールに対応しない(スクロールバーの
        # 精密なタッチ操作が必要になってしまう)。QScrollerでタッチジェスチャーによる
        # ドラッグスクロール(慣性スクロール含む)を有効化する。
        QScroller.grabGesture(scroll.viewport(), QScroller.TouchGesture)


class NumericKeypadDialog(QtWidgets.QDialog):
    """タッチ専用の数字入力ダイアログ。QT_QPA_PLATFORM=eglfs環境ではOSのソフトキーボードが
    出ないため、周波数入力等のフリーテキスト欄向けに自前で用意する。

    ダイアログ専用の表示欄は持たない。呼び出し元の実際の入力フィールド(target_edit)を
    一時的にこのダイアログのレイアウトへ移動して直接編集させ、閉じるときに元の位置へ
    戻す(キャンセル時は編集前の値へ復元してから戻す)。
    """

    def __init__(self, title: str, target_edit: QtWidgets.QLineEdit, parent=None,
                 allow_decimal: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)

        self._target = target_edit
        self._allow_decimal = allow_decimal
        self._original_text = target_edit.text()
        # ★このダイアログはQDialogとしてMainWindowとは別のトップレベルウィンドウになる。
        # QT_IM_MODULE=qtvirtualkeyboard指定下では、対象欄がフォーカスを得ると
        # プラットフォーム入力コンテキストがMainWindow側に手動埋め込み済みの
        # keyboard_panelとは別に、このウィンドウ用の(独立トップレベルの)入力パネルを
        # 生成しようとし、eglfsの「OpenGLウィンドウ1枚制限」に抵触してセグフォルトする
        # (実機で確認)。この欄はテンキーボタンでのみ入力するためIMEは不要であり、
        # setFocus()より前にWA_InputMethodEnabledを外して入力コンテキストの起動自体を防ぐ。
        self._target.setAttribute(QtCore.Qt.WA_InputMethodEnabled, False)
        self._original_stylesheet = target_edit.styleSheet()
        self._original_min_height = target_edit.minimumHeight()
        self._original_max_length = target_edit.maxLength()
        self._original_max_width = target_edit.maximumWidth()
        self._original_layout = target_edit.parentWidget().layout()
        self._original_index = self._original_layout.indexOf(target_edit)

        layout = QtWidgets.QVBoxLayout(self)

        # ★readOnlyのままだと物理/USBキーボードのBackspace等が一切効かない
        # (widgets.py冒頭の注記通りキーボードでの操作もサポートする)。数字専用バリデータ+
        # maxLengthで最大8桁に制限しつつ編集可能にし、オンスクリーンボタンとキーボード入力の
        # 両方を1文字単位でtarget_editへ直接・即座に反映させる。呼び出し元画面での
        # 幅制限(maximumWidth)はダイアログの大きい文字では窮屈なので編集中は解除する。
        self._target.setReadOnly(False)
        if allow_decimal:
            self._target.setValidator(QtGui.QDoubleValidator(0.0, 99_999_999.0, 6, self))
        else:
            self._target.setValidator(QtGui.QIntValidator(0, 99_999_999, self))
        self._target.setMaxLength(8)
        self._target.setMaximumWidth(QtWidgets.QWIDGETSIZE_MAX)
        self._target.setAlignment(QtCore.Qt.AlignRight)
        self._target.setMinimumHeight(TOUCH_MIN_HEIGHT)
        # ★呼び出し元画面(frequency.py)の表示フォント(24px)より小さくならないようにする。
        self._target.setStyleSheet(f"font-size: {max(FONT_SIZE_TITLE, 24)}px;")
        self._original_layout.removeWidget(self._target)
        layout.addWidget(self._target)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(4)
        positions = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("C", 3, 0), ("0", 3, 1), ("←", 3, 2),
        ]
        if allow_decimal:
            positions = [item for item in positions if item[0] != "←"]
            positions.extend([(".", 3, 2), ("←", 3, 3)])
        for label, row, col in positions:
            btn = QtWidgets.QPushButton(label)
            btn.setMinimumSize(64, TOUCH_MIN_HEIGHT)
            btn.setStyleSheet(f"font-size: {FONT_SIZE_TITLE}px;")
            btn.clicked.connect(lambda _checked=False, label=label: self._on_key(label))
            grid.addWidget(btn, row, col)
        layout.addLayout(grid)

        buttons = QtWidgets.QHBoxLayout()
        cancel_btn = QtWidgets.QPushButton(tr("キャンセル", "Cancel"))
        cancel_btn.setMinimumHeight(TOUCH_MIN_HEIGHT)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        ok_btn = QtWidgets.QPushButton("OK")
        ok_btn.setMinimumHeight(TOUCH_MIN_HEIGHT)
        ok_btn.clicked.connect(self.accept)
        buttons.addWidget(ok_btn)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._target.setFocus()
        self._target.end(False)

    def _on_key(self, label: str) -> None:
        self._target.setFocus()
        if label == "C":
            self._target.clear()
        elif label == "←":
            self._target.backspace()
        elif label == "." and "." in self._target.text():
            return
        else:
            self._target.insert(label)

    def done(self, result: int) -> None:
        if result == QtWidgets.QDialog.Rejected:
            self._target.setText(self._original_text)
        self._target.setAttribute(QtCore.Qt.WA_InputMethodEnabled, True)
        self._target.setReadOnly(True)
        self._target.setMaxLength(self._original_max_length)
        self._target.setMaximumWidth(self._original_max_width)
        self._target.setValidator(None)
        self._target.setStyleSheet(self._original_stylesheet)
        self._target.setMinimumHeight(self._original_min_height)
        self.layout().removeWidget(self._target)
        self._original_layout.insertWidget(self._original_index, self._target)
        super().done(result)

    @staticmethod
    def edit_in_place(parent: QtWidgets.QWidget, title: str, target_edit: QtWidgets.QLineEdit,
                      allow_decimal: bool = False) -> bool:
        dialog = NumericKeypadDialog(title, target_edit, parent, allow_decimal=allow_decimal)
        return dialog.exec_() == QtWidgets.QDialog.Accepted


def confirm_dialog(parent: QtWidgets.QWidget, title: str, message: str) -> bool:
    """Yes/No確認ダイアログ。Android版RFループバック警告と同じ用途で使う。

    ★標準のQMessageBox.warning()はYes/Noボタンが既定の小さいデスクトップ
    サイズ(高さ約24px程度)のままで、タッチでは反応が悪い/押しにくいという
    指摘が実機で出た。他のUI部品と同じTOUCH_MIN_HEIGHT基準の大きい
    ボタンを持つカスタムダイアログに置き換える(戻り値の意味・呼び出し方は
    QMessageBox版と互換)。
    """
    # ★設定画面の本文文字サイズ(24px)と統一する。ダイアログの最小サイズも
    # それに合わせて調整する(以前の29px基準の880x420から縮小)。
    dialog_font_size = 24
    dialog = QtWidgets.QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.setModal(True)
    dialog.setMinimumSize(760, 340)
    dialog.setStyleSheet("QDialog { background-color: #191d1f; }")
    layout = QtWidgets.QVBoxLayout(dialog)
    layout.setContentsMargins(32, 32, 32, 32)
    layout.setSpacing(24)
    title_label = QtWidgets.QLabel(bilingual(title))
    title_label.setStyleSheet(f"font-size: {dialog_font_size}px; font-weight: bold; color: white;")
    layout.addWidget(title_label)
    # ★messageを改行("\n")区切りの段落ごとに別々のQLabelとして追加する。
    # 1つのQLabel内で<span style="color:...">により途中で色を変えると、
    # 複数行に折り返された際にそれ以降の文字列まで同じ色が"bleed"してしまう
    # (Qtのリッチテキスト描画の既知の制限、日本語+折り返しの組み合わせで実機
    # 再現確認済み)。段落を分ければ各QLabelの最後で色指定が終わるため
    # bleedしない。
    for paragraph in message.split("\n"):
        if not paragraph:
            continue
        label = QtWidgets.QLabel(paragraph)
        label.setWordWrap(True)
        label.setStyleSheet(f"font-size: {dialog_font_size}px; color: #eeeeee;")
        layout.addWidget(label)
    layout.addStretch(1)

    buttons = QtWidgets.QHBoxLayout()
    buttons.setSpacing(16)
    buttons.addStretch(1)
    yes_btn = QtWidgets.QPushButton(bilingual("はい / Yes"))
    yes_btn.setMinimumSize(150, TOUCH_MIN_HEIGHT)
    yes_btn.setStyleSheet(
        f"font-size: {dialog_font_size}px; font-weight: bold; background-color: #7a1414; color: white;")
    yes_btn.clicked.connect(dialog.accept)
    buttons.addWidget(yes_btn)
    no_btn = QtWidgets.QPushButton(bilingual("いいえ / No"))
    no_btn.setMinimumSize(150, TOUCH_MIN_HEIGHT)
    no_btn.setStyleSheet(f"font-size: {dialog_font_size}px; font-weight: bold;")
    no_btn.clicked.connect(dialog.reject)
    buttons.addWidget(no_btn)
    buttons.addStretch(1)
    layout.addLayout(buttons)

    no_btn.setDefault(True)
    no_btn.setFocus()
    return dialog.exec_() == QtWidgets.QDialog.Accepted


def error_dialog(parent: QtWidgets.QWidget, title: str, message: str) -> None:
    QtWidgets.QMessageBox.critical(parent, title, message)
