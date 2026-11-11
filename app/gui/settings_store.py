"""shonan-pi5 GUI設定の永続化。

設定は単一のJSONファイル(~/.config/shonan-pi5/settings.json)にまとめて保存する。

- Pluto+がPi5に直結のため、送信先IP/Port(別筐体への送信先)ではなく
  pluto_uri(自機からPluto+へのlibiio URI)を持つ。
- fec_rate+modulation_schemeを合成した値がshonan_rx.pyへ実際に渡る
  --mod-cod になる(mod_cod()参照)。
- 送信ポート、受信ポート、シンボルレート、FEC、変調、ゲイン、出力、音量は
  いずれも実際の送受信制御に使われる。
"""
from __future__ import annotations

import json
import ipaddress
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import platform_compat
from i18n import tr

SETTINGS_DIR = Path(os.environ.get("SHONAN_CONFIG_DIR", str(Path.home() / ".config" / "shonan-pi5")))
SETTINGS_PATH = SETTINGS_DIR / "settings.json"

# バンドごとの標準LO周波数(Hz)プロファイル。
BAND_PROFILES = {
    "BAND_1200": {"label_ja": "1200MHz帯", "label_en": "1200MHz Band", "lo_hz": 1_273_000_000,
                   "wifi": "2.4GHz/5GHz いずれも可", "wifi_reason": "RF帯域と重複しないため直接干渉なし", "bitrate_mbps": 1.5},
    "BAND_2400": {"label_ja": "2400MHz帯", "label_en": "2400MHz Band", "lo_hz": 2_407_000_000,
                   "wifi": "5GHz", "wifi_reason": "2.4GHz Wi-FiとRF帯域が重複するため", "bitrate_mbps": 1.5},
    "BAND_5600": {"label_ja": "5600MHz帯", "label_en": "5600MHz Band", "lo_hz": 5_730_000_000,
                   "wifi": "2.4GHz", "wifi_reason": "5GHz Wi-FiとRF帯域が重複するため", "bitrate_mbps": 1.5},
    "BAND_10000": {"label_ja": "10GHz帯", "label_en": "10GHz Band", "lo_hz": 10_180_000_000,
                   "wifi": "2.4GHz/5GHz いずれも可", "wifi_reason": "重複なし", "bitrate_mbps": 1.5},
    "BAND_24000": {"label_ja": "24GHz帯", "label_en": "24GHz Band", "lo_hz": 24_000_000_000,
                   "wifi": "2.4GHz/5GHz いずれも可", "wifi_reason": "重複なし", "bitrate_mbps": 1.5},
}

FEC_RATES = ["1/4", "1/3", "2/5", "1/2", "3/5", "2/3", "3/4", "4/5", "5/6", "8/9", "9/10"]
MODULATION_SCHEMES = ["QPSK", "8PSK", "16APSK", "32APSK"]

# DVB-S2(ETSI EN 302 307-1)のロングフレームで定義されている全28 MOD-COD。
# ★送信はPlutoのpluto_dvb(無印Pluto v0.39のソフト変調、Pluto+ FPGA版のDVB-S2回路の
# どちらも全組み合わせに対応)、受信はgr-dvbs2rx(16/32APSKはV2のパッチ
# docs/patches/gr-dvbs2rx_apsk.patchで追加)。pi5/rx/shonan_rx.pyの_MODCOD_FEC_RATESは
# これと同じ内容にすること(tests/test_settings_store.pyで照合している)。
MODULATION_FEC_RATES = {
    "QPSK": ["1/4", "1/3", "2/5", "1/2", "3/5", "2/3", "3/4", "4/5", "5/6", "8/9", "9/10"],
    "8PSK": ["3/5", "2/3", "3/4", "5/6", "8/9", "9/10"],
    "16APSK": ["2/3", "3/4", "4/5", "5/6", "8/9", "9/10"],
    "32APSK": ["3/4", "4/5", "5/6", "8/9", "9/10"],
}
TX_SUPPORTED_MODCODS = [
    f"{modulation}-S_{rate}"
    for modulation, rates in MODULATION_FEC_RATES.items() for rate in rates
]
RX_SUPPORTED_MODCODS = list(TX_SUPPORTED_MODCODS)


# 16APSK・32APSKを正しく送れるのはPluto+のFPGA版ファーム(fw_versionに"FPGA"を含む)だけ。
# 無印Pluto・Pluto+の通常版はARMのソフト変調(pluto_dvb)で、APSKは振幅が潰れて受信できない
# (2026-11-11 実機試験)。それらのPlutoでは変調方式を8PSKまでにする。
APSK_MODULATIONS = ("16APSK", "32APSK")


def available_modulation_schemes(pluto_apsk_capable: bool) -> list[str]:
    """接続するPlutoで送れる変調方式。APSK対応(FPGA版ファーム)ならすべて、それ以外は8PSKまで。"""
    if pluto_apsk_capable:
        return list(MODULATION_SCHEMES)
    return [m for m in MODULATION_SCHEMES if m not in APSK_MODULATIONS]


def detect_pluto_apsk_capable(pluto_uri: str, timeout: float = 4.0):
    """Plutoのファームの版(IIOコンテキスト属性fw_version)からAPSK対応かを調べる。

    戻り値: True=FPGA版ファーム(32APSKまで)、False=それ以外(8PSKまで)、None=読めなかった。
    """
    import subprocess
    try:
        result = subprocess.run(["iio_attr", "-u", pluto_uri, "-C", "fw_version"],
                                capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = result.stdout.strip()
    if result.returncode != 0 or "fw_version" not in text:
        return None
    return "FPGA" in text.split(":", 1)[-1]


def supported_fec_rates(modulation: str) -> list[str]:
    """指定した変調方式でTX_SUPPORTED_MODCODSが実際に対応するFEC符号化率一覧。

    FEC画面(screens/fec.py)の選択肢を、開始時に拒否される組み合わせを
    含まないよう絞り込むために使う。
    """
    prefix = f"{modulation}-S_"
    return [combo[len(prefix):] for combo in TX_SUPPORTED_MODCODS if combo.startswith(prefix)]


SYMBOL_RATE_CANDIDATES_MSPS = [0.25, 0.333, 0.5, 0.666, 1.0, 2.0]

TX_VIDEO_BITRATE_BPS = 400_000
# 送信映像のコーデック(Pi5版と同じ)。h265は同じビットレートで画質が上がる代わりに
# 符号化が重い(libx265のCPU符号化)。受信側はTSから自動判別する。
VIDEO_CODECS = ("h264", "h265")
TX_AUDIO_BITRATE_BPS = 16_000


# DVB-S2ノーマルフレームのBCH情報ビット数Kbch(EN 302 307-1 表5a)。TS容量の計算に使う。
_KBCH_NORMAL = {
    "1/4": 16008, "1/3": 21408, "2/5": 25728, "1/2": 32208, "3/5": 38688, "2/3": 43040,
    "3/4": 48408, "4/5": 51648, "5/6": 53840, "8/9": 57472, "9/10": 58192,
}
_BITS_PER_SYMBOL = {"QPSK": 2, "8PSK": 3, "16APSK": 4, "32APSK": 5}

# FEC自動選択で確保する送信TSのビットレート。映像・音声の符号化レートに、TS/PES化と
# PAT/PMT/SDT/PCR等の分の余裕25%を見込む。
REQUIRED_TS_BITRATE_BPS = round((TX_VIDEO_BITRATE_BPS + TX_AUDIO_BITRATE_BPS) * 1.25)


def dvbs2_ts_capacity_bps(symbol_rate_hz: float, modulation: str, fec_rate: str,
                          pilots: bool = True) -> float:
    """DVB-S2(ノーマルフレーム)で送れるTSのビットレート。

    1 PLFRAME = PLHEADER(90) + データ(64800/ビット数 シンボル) + パイロット(16スロットごとに36)。
    そこにKbch-80(BBHEADER)ビットのTSが入る。
    """
    bits = _BITS_PER_SYMBOL[modulation]
    slots = 64800 // (bits * 90)
    plframe = 90 + slots * 90 + ((slots - 1) // 16 * 36 if pilots else 0)
    return symbol_rate_hz * (_KBCH_NORMAL[fec_rate] - 80) / plframe


def auto_fec_rate(symbol_rate_hz: float, modulation: str,
                  required_bps: float = REQUIRED_TS_BITRATE_BPS) -> str:
    """映像・音声に必要なTSビットレートを送れる範囲で、いちばん誤りに強いFECを返す。

    選択肢は誤りに強い順(符号化率の小さい順)に並んでいるので、最初に容量が足りるものを選ぶ。
    どれでも足りない場合は、いちばん多く送れるFEC(最後)を返す。
    """
    rates = supported_fec_rates(modulation)
    for rate in rates:
        if dvbs2_ts_capacity_bps(symbol_rate_hz, modulation, rate) >= required_bps:
            return rate
    return rates[-1]


def normalize_pluto_host(value: str) -> str:
    """Return a safe Pluto host, rejecting pasted control/shell text."""
    host = str(value).strip()
    if host.startswith("ip:"):
        host = host[3:].strip()
    if not host or any(ord(char) < 32 or char.isspace() for char in host):
        raise ValueError(tr("Pluto接続先に空白または制御文字が含まれています",
                            "The Pluto destination contains whitespace or control characters"))
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        # Hostnames are allowed for development, but not URL fragments or quotes.
        if len(host) <= 253 and re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            return host
    raise ValueError(tr("Pluto接続先はIPアドレスまたはホスト名で入力してください",
                        "Enter the Pluto destination as an IP address or hostname"))


def normalize_ptt_controller_host(value: str) -> str:
    """Return a safe PTT controller (ESP32+W5500) host, or "" to disable the feature."""
    host = str(value).strip()
    if not host:
        return ""
    if any(ord(char) < 32 or char.isspace() for char in host):
        raise ValueError(tr("PTTコントローラ接続先に空白または制御文字が含まれています",
                            "The PTT controller destination contains whitespace or control characters"))
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        if len(host) <= 253 and re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            return host
    raise ValueError(tr("PTTコントローラ接続先はIPアドレスまたはホスト名で入力してください",
                        "Enter the PTT controller destination as an IP address or hostname"))


@dataclass
class AppSettings:
    language: str = "JAPANESE"  # JAPANESE | ENGLISH

    selected_band: str = "BAND_1200"
    use_custom_lo_frequency: bool = True
    custom_lo_frequency_hz: int = 437_000_000

    # Pluto+接続(Pi5はローカル直結のためURI形式。Android版のtxDestinationIP/Port相当を代替)
    pluto_uri: str = "ip:192.168.0.10"

    # PA_Power/PTTコントローラ(ESP32+W5500、hardware/W5500_PA_PTT_Control)のIPアドレス。
    # 空文字なら連携しない(未接続環境でもTX/RXの動作に影響しない)。
    ptt_controller_host: str = "192.168.0.100"
    rx_listen_port: int = 4003
    rx_status_port: int = 4002
    rx_volume: float = 0.5  # 0.0..1.0 (初期音量50%)
    tmp_dir: str = field(default_factory=platform_compat.default_tmp_dir)

    # Android版と同じソフトウェアループ試験設定
    loopback_use_localhost: bool = False
    loopback_target_ip: str = "192.168.0.21"
    simultaneous_tx_rx_test: bool = False

    # GUI起動時およびRX開始直前にPluto RX DMAの短い読出し試験を行う。
    # 通常運用では不要なため既定はOFF。障害切り分け時に設定画面でONにする。
    iio_preflight_enabled: bool = False

    # ONのときだけTX画面からオンデバイスRX画面への導線を表示する。
    # RX自体の実装はPi5内蔵GNU Radio経路を使用する。
    use_on_device_demod: bool = False

    # 映像ソース(Android VideoSourceOption相当)
    camera_device: str = field(default_factory=platform_compat.default_camera_device)
    video_source: str = "colorbar"  # camera | file | colorbar
    video_file_path: str = ""
    use_color_bar_source: bool = True
    # 送信映像のコーデック(VIDEO_CODECSのいずれか)。受信側はTSから自動判別する。
    video_codec: str = "h264"

    # カメラ映像へ焼き込むオーバーレイ(shonan_lite-ipad版CameraOverlayRenderer相当)。
    # コールサイン(左上・大)+送信開始時の日時と備考(右下・小)。カラーバーには
    # 焼き込まない(カラーバー画像自体に既にコールサインが描かれているため)。
    overlay_callsign: str = ""
    overlay_note: str = ""
    # 文字サイズ(px、1920x1080の送信映像上での大きさ)。映像ソース画面で選択する。
    overlay_callsign_font_size: int = 68
    overlay_note_font_size: int = 24
    # コールサイン・備考の文字色("#RRGGBB")。映像ソース画面で選択する。
    overlay_callsign_color: str = "#FFFFFF"
    overlay_note_color: str = "#FFFFFF"

    # RXゲイン
    rx_agc_enabled: bool = False
    rx_gain_db: int = 60  # 0..73、AGC OFF時のみ有効

    # RSSI測定: True=「検索停止」が押されるまで繰り返す(連続)、False=範囲の終わりまで1回で自動停止
    rssi_repeat_scan: bool = True

    # TX出力
    tx_power_db: float = 0.0  # -70..0、0=最大出力（40 dB外部アッテネータ試験の既定）

    # FEC+Modulationの合成がmod_cod()。symbol_rate_mspsはRXへ実際に渡す。
    symbol_rate_msps: float = 0.5
    # gr-dvbs2rxの受信実装とPluto側の試験設定で共通して使用できる既定値。
    fec_rate: str = "3/5"
    modulation_scheme: str = "QPSK"
    # True=シンボルレート・変調方式に合わせてFECを自動で選ぶ(auto_fec_rate)。False=手動。
    fec_auto: bool = True
    # 最後に調べたPlutoがAPSK(16/32APSK)を送れるか(FPGA版ファームか)。つながらないときはこの値を使う。
    pluto_apsk_capable: bool = False

    # RFループバック自己申告フラグ(Android版のRF loopback警告と同じ、インターロックなし)
    rf_loopback_enabled: bool = False

    # ユーザー登録プリセット。各要素は表示名(name)と設定値(values)を持つ。
    presets: list[dict] = field(default_factory=list)

    def effective_lo_hz(self) -> Optional[int]:
        if self.use_custom_lo_frequency:
            return self.custom_lo_frequency_hz
        # Android版effectiveLoHzと同じくLOOPBACKでは手動値へフォールバックする。
        return BAND_PROFILES[self.selected_band]["lo_hz"] or self.custom_lo_frequency_hz

    def is_loopback(self) -> bool:
        # ループ試験機能は廃止。旧設定にLOOPBACKが残っていても通常経路を使う。
        return False

    def effective_loopback_host(self) -> str:
        return "127.0.0.1" if self.loopback_use_localhost else self.loopback_target_ip

    def mod_cod(self) -> str:
        """FEC + Modulation を合成した --mod-cod 文字列。"""
        return f"{self.modulation_scheme}-S_{self.fec_rate}"

    def pluto_host(self) -> str:
        return normalize_pluto_host(self.pluto_uri)

    def symbol_rate_hz(self) -> int:
        return round(self.symbol_rate_msps * 1_000_000)

    def apply_pluto_capability(self, capable: bool) -> bool:
        """Plutoの判定を反映する。APSKを選んでいてそのPlutoで使えない場合は8PSKへ変え、Trueを返す。"""
        self.pluto_apsk_capable = capable
        if capable or self.modulation_scheme not in APSK_MODULATIONS:
            return False
        self.modulation_scheme = "8PSK"
        if not self.apply_auto_fec() and self.fec_rate not in supported_fec_rates("8PSK"):
            self.fec_rate = supported_fec_rates("8PSK")[0]
        return True

    def apply_auto_fec(self) -> bool:
        """FEC自動のとき、今のシンボルレート・変調方式に合うFECへ合わせる。変えたらTrue。"""
        if not self.fec_auto:
            return False
        rate = auto_fec_rate(self.symbol_rate_hz(), self.modulation_scheme)
        if rate == self.fec_rate:
            return False
        self.fec_rate = rate
        return True

    def tx_mod_cod_supported(self) -> bool:
        return self.mod_cod() in TX_SUPPORTED_MODCODS

    def rx_mod_cod_supported(self) -> bool:
        return self.mod_cod() in RX_SUPPORTED_MODCODS


def load() -> AppSettings:
    if not SETTINGS_PATH.exists():
        return AppSettings()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        defaults = asdict(AppSettings())
        defaults.update({k: v for k, v in data.items() if k in defaults})
        # 旧バージョンのループ試験設定を通常バンドへ移行する。
        if defaults.get("selected_band") == "LOOPBACK":
            defaults["selected_band"] = "BAND_1200"
        if defaults.get("use_color_bar_source"):
            defaults["video_source"] = "colorbar"
        elif defaults.get("video_source") == "colorbar":
            defaults["use_color_bar_source"] = True
        if defaults.get("video_codec") not in VIDEO_CODECS:
            defaults["video_codec"] = AppSettings.video_codec
        # 選択肢から外した変調方式(16APSK等)で保存された設定はQPSKへ移行し、
        # FECもQPSKで使えない値なら既定値へ戻す。
        if defaults.get("modulation_scheme") not in MODULATION_SCHEMES:
            defaults["modulation_scheme"] = AppSettings.modulation_scheme
            if defaults.get("fec_rate") not in supported_fec_rates(defaults["modulation_scheme"]):
                defaults["fec_rate"] = AppSettings.fec_rate
        try:
            defaults["pluto_uri"] = f"ip:{normalize_pluto_host(defaults["pluto_uri"])}"
        except (TypeError, ValueError):
            defaults["pluto_uri"] = AppSettings.pluto_uri
        try:
            defaults["ptt_controller_host"] = normalize_ptt_controller_host(
                defaults.get("ptt_controller_host", ""))
        except (TypeError, ValueError):
            defaults["ptt_controller_host"] = AppSettings.ptt_controller_host
        settings = AppSettings(**defaults)
        settings.apply_auto_fec()
        return settings
    except (json.JSONDecodeError, OSError, TypeError):
        return AppSettings()


def save(settings: AppSettings) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
