"""TX/RXバックエンドプロセス管理。

TX: ffmpeg映像ソース → UDP-TS(MPEG-TS over UDP、ポート8282)でPluto+上の
`udpts.sh`(/www/settings.txtを`save.php`経由で読み、`tsp | pluto_dvb`の
パイプで変調・送出する常駐スクリプト)へ直接プッシュする方式(shonan_lite-ipad
と同じ経路)。開始直前にHTTP POSTで`/save.php`へfreq/mod/sr/fec等を書き込み、
udpts.shのループがそれを読み直して`pluto_dvb`を正しいパラメータで再起動する
のを待ってからffmpegを起動する。

送信はPluto内蔵の`pluto_dvb`経路のみを使用する。

RX: shonan_rx.py(+ffplay)をQProcessで起動/停止し、標準エラー出力の状態行を
正規表現でパースしてQt Signalで通知する。
"""
from __future__ import annotations

import collections
import concurrent.futures
import ipaddress
import os
import http.client
import queue
import re
import shlex
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

from PyQt5 import QtCore

import platform_compat
from i18n import tr
from settings_store import (
    RX_SUPPORTED_MODCODS, TX_AUDIO_BITRATE_BPS, TX_SUPPORTED_MODCODS,
    TX_VIDEO_BITRATE_BPS, AppSettings,
)

APP_DIR = platform_compat.app_dir()  # .../app(凍結時はsys._MEIPASS)
# iPad版Assets.xcassets/TestPattern.imagesetから取り込んだ共通テストパターン。
ANDROID_TEST_PATTERN = APP_DIR / "assets" / "test_pattern_ipad.png"

# Pluto+上でudpts.shが`tsp -I ip 0.0.0.0:8282`として常駐待ち受けするUDP-TSポート
# (udpts.sh参照、ファームウェア固定値)。
PLUTO_UDP_TS_PORT = 8282

# libiioのiiod常駐プロセスが待ち受けるTCPポート(main.py _pluto_is_online()と同じ
# 判定に使うファームウェア固定値)。discover_pluto_ip()の誤検出対策で参照する。
PLUTO_IIOD_PORT = 30431

def _detect_gnuradio_available() -> bool:
    """shonan_rx.pyが実際に使うインタプリタ(platform_compat.
    gnuradio_python_executable()、Windowsではアプリ本体の.venv-winとは別の
    radioconda環境)でgnuradio.dvbs2rxがimportできるかを確認する。現在の
    プロセス(.venv-win)自体にはgnuradioが入っていないため、importlib等で
    自プロセスをチェックしても意味がない。"""
    python_exe = platform_compat.gnuradio_python_executable()
    try:
        result = subprocess.run(
            [python_exe, "-c", "import gnuradio.dvbs2rx"],
            capture_output=True, timeout=10, **platform_compat.no_window_kwargs())
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


# ★以前はモジュール読み込み時(=アプリ起動時)に即座に_detect_gnuradio_available()を
# 呼んでいたが、radioconda環境のpython.exeを毎回起動するため起動が数百ms〜1秒
# 近く遅くなっていた(実測)。RXを使わない起動では無駄なコストなので、実際に
# RXを開始しようとした時点まで遅延させ、結果はプロセス内でキャッシュする。
_GNURADIO_AVAILABLE: Optional[bool] = None


def _gnuradio_available() -> bool:
    global _GNURADIO_AVAILABLE
    if _GNURADIO_AVAILABLE is None:
        _GNURADIO_AVAILABLE = _detect_gnuradio_available()
    return _GNURADIO_AVAILABLE


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_PLUTO_SETTINGS_OPENER = urllib.request.build_opener(_NoRedirectHandler)
# ffmpeg自身の進捗表示行("frame=  150 fps=...")の出現をもって「実際に符号化・
# 送出できている」とみなす(udpts.sh側のpluto_dvbのUnderflow等はPi5側から見えない)。
# frame番号自体もここから実測フレーム数として取り出す。
_TX_STREAMING_RE = re.compile(r"frame=\s*(\d+)")
# カメラ内蔵マイク/USBオーディオの実デバイス名解決はOS依存のため
# platform_compat(ALSA on Linux / DirectShow+WASAPI on Windows)に委ねる。


def _detect_playback_alsa_device() -> Optional[str]:
    """RX音声の再生先デバイス。Linuxは`aplay -l`からUSBオーディオを動的検出、
    Windowsはplatform_compat経由でOS既定の再生デバイスを使う。"""
    return platform_compat.detect_playback_device()


def _detect_camera_alsa_device() -> Optional[str]:
    """カメラ内蔵マイクの入力デバイス。見つからない場合はNoneを返す(送信側は
    無音AAC入力へ切り替え、映像送信を音声デバイス不在で中断させない)。"""
    return platform_compat.detect_camera_audio_device()


def _audio_input_args() -> list[str]:
    return platform_compat.audio_input_args()


# コールサイン/日時/備考オーバーレイに使うフォント(shonan_lite-ipad版CameraOverlayRenderer
# のPi5移植)。DejaVu Sansは英数字用、Droid Sans Fallbackは日本語用(実機で確認した限り
# 互いに相手の文字種のグリフを含まない)。drawtextフィルタは1回の呼び出しにつき
# フォントを1つしか使えないため、コールサイン・備考はPillowで事前にPNGへ文字種ごとに
# フォントを切り替えて合成し、ffmpegのoverlayフィルタで映像へ重ねる
# (_render_overlay_image/_build_overlay_pipeline参照)。日時は英数字のみなので
# 従来通りdrawtextのライブ更新(%{localtime})を使う。
_OVERLAY_FONT = platform_compat.overlay_ascii_font()
_OVERLAY_SHADOW = "shadowcolor=black@0.8:shadowx=1:shadowy=1"
_OVERLAY_ASCII_FONT_PATH = _OVERLAY_FONT
_OVERLAY_CJK_FONT_PATH = platform_compat.overlay_cjk_font()


def _ffmpeg_filter_path(path: str) -> str:
    """drawtext等のフィルタグラフ文字列に埋め込むためのパスエスケープ。Windowsの
    ドライブレター(C:)のコロンやバックスラッシュはフィルタ構文の区切り文字(`:`)
    ・エスケープ文字(`\\`)と衝突するため、スラッシュ化した上でコロンをエスケープする。
    ★単にバックスラッシュエスケープするだけ(C\\:/...)ではffmpeg 9.0.1の
    フィルタグラフパーサが"No option name"エラーで拒否することを実機確認済み
    (drive-letterコロンの直後を値の終端と誤認する)。値全体を単一引用符で
    囲んだ上でコロンもエスケープする('C\\:/...')必要がある。"""
    escaped = path.replace("\\", "/").replace(":", "\\:")
    return f"'{escaped}'"
_OVERLAY_IMAGE_NAME = "shonan_overlay.png"

# 送信映像の解像度はフルHD(1920x1080)固定。カメラの実キャプチャ解像度や画像ファイルの
# 寸法・縦横比に関わらず、縦横比を保って縮小/拡大し、余白は黒で埋めて1920x1080に揃える。
TX_VIDEO_WIDTH = 1920
TX_VIDEO_HEIGHT = 1080
_TX_VIDEO_SCALE_FILTER = (
    f"scale={TX_VIDEO_WIDTH}:{TX_VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
    f"pad={TX_VIDEO_WIDTH}:{TX_VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2,setsar=1"
)


def _split_font_runs(text: str) -> list[tuple[str, bool]]:
    """textを(区間文字列, 日本語グリフが必要か)のリストへ分割する。"""
    runs: list[tuple[str, bool]] = []
    current = ""
    current_is_cjk: Optional[bool] = None
    for ch in text:
        is_cjk = ord(ch) >= 0x3000
        if current_is_cjk is not None and is_cjk != current_is_cjk:
            runs.append((current, current_is_cjk))
            current = ""
        current += ch
        current_is_cjk = is_cjk
    if current:
        runs.append((current, bool(current_is_cjk)))
    return runs


def _parse_color(value) -> tuple[int, int, int]:
    """"#RRGGBB"を(R, G, B)へ変換する。不正な値は白。"""
    try:
        text = str(value).lstrip("#")
        if len(text) == 6:
            return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        pass
    return (255, 255, 255)


def _draw_mixed_text(draw, x: int, y: int, text: str, font_size: int, align: str,
                     color: tuple[int, int, int] = (255, 255, 255)) -> None:
    """英数字と日本語が混在するtextを、区間ごとにフォントを切り替えて描画する。"""
    from PIL import ImageFont

    fonts = {
        False: ImageFont.truetype(_OVERLAY_ASCII_FONT_PATH, font_size),
        True: ImageFont.truetype(_OVERLAY_CJK_FONT_PATH, font_size),
    }
    # 影は通常黒。黒など暗い文字色では影が見えないため白っぽい影にする。
    luminance = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
    shadow = (0, 0, 0, 204) if luminance >= 80 else (255, 255, 255, 204)
    runs = _split_font_runs(text)
    if align == "right":
        total_width = sum(draw.textlength(t, font=fonts[c]) for t, c in runs)
        x -= total_width
    cursor = x
    for run_text, is_cjk in runs:
        font = fonts[is_cjk]
        draw.text((cursor + 1, y + 1), run_text, font=font, fill=shadow)
        draw.text((cursor, y), run_text, font=font, fill=(*color, 255))
        cursor += draw.textlength(run_text, font=font)


def _clamp_font_size(size) -> int:
    try:
        return max(8, min(256, int(size)))
    except (TypeError, ValueError):
        return 24


def _render_overlay_image(tmp_dir: str, callsign: str, note: str,
                          callsign_size: int = 68, note_size: int = 24,
                          callsign_color: str = "#FFFFFF", note_color: str = "#FFFFFF") -> str:
    """コールサイン(左上・大)と備考(右下・小、日時のすぐ上)を透過PNGへ描画する。
    callsign_size/note_sizeは1920x1080上での文字サイズ(px)。"""
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    if callsign:
        _draw_mixed_text(draw, 24, 24, callsign, _clamp_font_size(callsign_size), align="left",
                         color=_parse_color(callsign_color))
    if note:
        # 文字サイズに関わらず備考の下端を日時のすぐ上(従来の24px時と同じ位置)に揃える。
        size = _clamp_font_size(note_size)
        _draw_mixed_text(draw, 1920 - 24, 1080 - 126 - size, note, size, align="right",
                         color=_parse_color(note_color))
    path = f"{tmp_dir}/{_OVERLAY_IMAGE_NAME}"
    img.save(path)
    return path


def _build_overlay_pipeline(
        settings: AppSettings, extra_video_filters: str = "",
        *, split_preview: bool = False) -> tuple[list[str], list[str], str, str, int]:
    """映像(カメラまたは画像ファイル)へのコールサイン・日時・備考オーバーレイを
    含む、ffmpeg入力・フィルタ関連の引数一式を組み立てる。"0:v"を土台として
    重ねるだけなので、入力がカメラでも(-loopで反復する)静止画でも使える。
    戻り値は
    (追加入力引数, フィルタ関連引数, 映像マップ先(-mapの値), プレビュー用映像マップ先,
    音声入力インデックス)。extra_video_filtersは末尾に追加するフィルタ(例: "showinfo")。
    カンマなしの単体フィルタ文字列を渡す。コールサイン・備考が両方空ならオーバーレイなし。

    split_preview=Trueの場合、映像マップ先とプレビュー用映像マップ先に別々のラベルを返す。
    ★-mapで参照する映像出力を、TX本線(mpegts)とプレビュー分岐(rawvideo, pipe:1)の
    2箇所で使うTxController.start()向け。生入力ストリーム("0:v")は何度でも-mapできるが、
    filter_complexの出力パッド("[vout]"のようなラベル)は一度-mapすると消費され、2回目の
    -mapは"Output with label ... was already used elsewhere"で失敗する(実機確認済み)。
    そのためsplitフィルタで明示的に複製し、映像マップ先とプレビュー用映像マップ先へ
    別ラベルを割り当てる。

    ★時刻フォーマットはコロン("%H:%M:%S")ではなく"%H.%M.%S"を使う。drawtextの
    %{localtime\\:FORMAT}展開は最初のコロン1個だけをlocaltime関数の区切りとして
    特別扱いし、FORMAT内に更にコロンがあると引数過多の警告と共に無表示になる
    (実機で検証済み)。
    """
    callsign = settings.overlay_callsign.strip()
    note = settings.overlay_note.strip()
    if not callsign and not note:
        # ★-vfは直後の最初の出力(mpegts本線)にだけ掛かる。プレビュー分岐は"0:v"を
        # 直接-mapし、別途-s 640x360へ縮小するので問題ない。
        video_filter = _TX_VIDEO_SCALE_FILTER
        if extra_video_filters:
            video_filter += f",{extra_video_filters}"
        return [], ["-vf", video_filter], "0:v", "0:v", 1

    image_path = _render_overlay_image(
        settings.tmp_dir, callsign, note,
        settings.overlay_callsign_font_size, settings.overlay_note_font_size,
        settings.overlay_callsign_color, settings.overlay_note_color)
    date_filter = (
        f"drawtext=fontfile={_ffmpeg_filter_path(_OVERLAY_FONT)}:text='%{{localtime\\:%Y-%m-%d %H.%M.%S}}':"
        f"fontsize=24:fontcolor=white:x=w-text_w-24:y=h-text_h-24:{_OVERLAY_SHADOW}"
    )
    # ★オーバーレイ画像は1920x1080固定で描画しているが、USBカメラの実キャプチャ解像度は
    # 機種やv4l2既定値により640x480等になることがある(C920で実機確認)。overlayフィルタは
    # 台紙より大きい画像を単純に左上から切り取るだけなので、解像度が一致しないと右下の
    # 備考が画角外に出て見えなくなる。scale2refでオーバーレイ画像を実際の映像サイズへ
    # 常に合わせてから重ねる。
    # 土台の映像は先にフルHD(1920x1080)へ揃えてから重ねる。
    chain = (f"[0:v]{_TX_VIDEO_SCALE_FILTER}[hd];"
             f"[1:v][hd]scale2ref=w=iw:h=ih[ovl][base];[base][ovl]overlay=0:0,{date_filter}")
    if extra_video_filters:
        chain += f",{extra_video_filters}"
    if split_preview:
        chain += "[vpre];[vpre]split=2[vout][vout2]"
        video_map, preview_map = "[vout]", "[vout2]"
    else:
        chain += "[vout]"
        video_map, preview_map = "[vout]", "[vout]"
    return ["-loop", "1", "-i", image_path], ["-filter_complex", chain], video_map, preview_map, 2


# shonan_rx.pyの標準エラー出力状態行(例: "[shonan_rx] locked=False sof=0 frame=0
# rejected=0 freq_off=0.0 packets=0 errors=0")をパースする。
_RX_STATUS_RE = re.compile(
    r"locked=(True|False) sof=(\d+) frame=(\d+) rejected=(\d+) freq_off=(-?[\d.]+) packets=(\d+) errors=(\d+)"
)
# shonan-android版RxController.ktのロック監視(500ms周期ポーリング)を参考にしつつ、
# あちらにはない「停滞したら実際にプロセスを再起動する」動作を追加(実機でRXの
# フレーム同期が固まったまま進まなくなる不具合が確認されたため)。
WATCHDOG_INTERVAL_MS = 1000
WATCHDOG_STALL_TIMEOUT_MS = 8000  # frameが8秒間進まなければ停滞とみなす


def _quote(s: str) -> str:
    return shlex.quote(s)


def _safe_print(text: str) -> None:
    """print()相当だが例外を一切外へ出さない。

    ★TX/RX子プロセスの出力を`errors="replace"`でデコードした文字列には
    U+FFFD(REPLACEMENT CHARACTER、マルチバイト文字がバイナリパイプの読み出し
    境界で分断された場合等に挿入される)が混ざることがあり、コンソールの既定
    コードページ(日本語Windowsのcp932等)ではこれをエンコードできず
    UnicodeEncodeErrorになる。console=False(凍結ビルド)ではsys.stdoutが
    Noneのこともあり、その場合はAttributeErrorになる。通常のprint()呼び出しが
    Qtのシグナル発行の呼び出し stacksの中(特に入れ子のemit)で例外を送出すると、
    実機でアプリ全体が無言でクラッシュする不具合が確認された(受信開始のたびに
    コンソール窓が点滅を繰り返す症状の根本原因)。デバッグ用の副次的な出力の
    ためにアプリ全体を巻き込んで落とさないよう、ここで例外を握りつぶす。"""
    try:
        print(text, flush=True)
    except Exception:
        pass


_CREATE_NO_WINDOW = 0x08000000  # Windows CreateProcess()フラグ

# ★このPyQt5ビルドはQProcess.setCreateProcessArgumentsModifier()(Qt 5.14+で追加された
# コンソール窓抑止用API)を公開しておらず(AttributeError)、QProcessからは
# CREATE_NO_WINDOWを指定できない。そのためWindows側でコンソール窓を出したくない
# 子プロセス(ffmpeg.exe、radioconda\python.exe)はQProcessではなくsubprocess.Popen
# (creationflags=_CREATE_NO_WINDOWが直接指定できる)で起動する。


def check_pluto_connection(settings: AppSettings) -> tuple[bool, str]:
    """Check the Pluto IIO context without changing RF settings."""
    try:
        settings.pluto_host()  # validate the URI before invoking an external command
        result = subprocess.run(
            [platform_compat.find_binary("iio_info"), "-u", settings.pluto_uri],
            capture_output=True, text=True, timeout=5,
            **platform_compat.no_window_kwargs(),
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return False, detail[-1] if detail else tr(f"iio_info終了コード={result.returncode}", f"iio_info exit code={result.returncode}")
    return True, tr("IIOコンテキスト接続OK", "IIO context connection OK")


# Android版(PlutoDiscoveryClient.kt)と同じ安全上限: /23より広いネットワークは
# 走査対象ホスト数が多すぎるためスキャンしない。
_DISCOVERY_MAX_SCAN_HOST_BITS = 9


def _local_ipv4_subnets() -> list[tuple[str, int]]:
    """このPCが持つ全IPv4インタフェースの(アドレス, プレフィックス長)一覧。

    ★Pluto+はPCの既定ルート(通常WiFi、家庭/現場LANの192.168.0.x等)とは別の
    USB Ethernet gadgetアダプタ(既定IP 192.168.2.1)に直結されることが多い。
    既定ルートのサブネットだけをUDP connect()のトリックで調べる実装では、
    このgadgetアダプタのセグメントがそもそも走査対象に入らずPlutoを発見でき
    ない実害が確認された。psutilで全インタフェースを列挙し、ループバック・
    リンクローカル(169.254.x、DHCP失敗時の自動割当)を除いた各サブネットを
    返す(requirements-win.txtにpsutilを必須依存として追加済み)。
    psutil未導入環境(Pi5側等)ではUDP connect()による既定ルートの1本のみに
    後退する(/24と仮定。家庭/現場運用で一般的な/24 LANであれば実用上問題ない)。
    """
    try:
        import psutil
        subnets = []
        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if addr.family != socket.AF_INET or not addr.netmask:
                    continue
                if addr.address.startswith("127.") or addr.address.startswith("169.254."):
                    continue
                prefix = sum(bin(int(octet)).count("1") for octet in addr.netmask.split("."))
                subnets.append((addr.address, prefix))
        if subnets:
            return subnets
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return [(probe.getsockname()[0], 24)]
    except OSError:
        return []


def _probe_pluto(host: str, timeout: float) -> Optional[str]:
    """android版probePlutoHttp()と同じくGET /pluto.phpの200応答を見るが、それだけでは
    「任意のパスに200を返すHTTPサーバ」(ルーター管理画面等、実機で誤検出を確認済み)を
    Plutoと誤認してしまう。main.py の _pluto_is_online() と同じく、iiod待受ポート
    (TCP PLUTO_IIOD_PORT)が実際に開いていることも合わせて要求し、判定を厳格化する。
    """
    try:
        request = urllib.request.Request(f"http://{host}/pluto.php", method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if not (200 <= response.status < 300):
                return None
    except (OSError, ValueError):
        return None
    try:
        with socket.create_connection((host, PLUTO_IIOD_PORT), timeout=timeout):
            return host
    except OSError:
        return None


def discover_pluto_ip(*, timeout: float = 0.3, max_workers: int = 64) -> Optional[str]:
    """自機の全IPv4インタフェース配下でPluto+(Web UI応答+iiod待受の両方)を探す。

    android版PlutoDiscoveryClient.discoverPlutoIp()の第1段(自機サブネットの
    総当たりスキャン)を土台にしつつ、次の2点を強化している:
    1. GET /pluto.phpの200応答だけでは同一LAN上の無関係な機器(何にでも200を
       返すHTTPサーバ)を誤検出する実害が確認されたため、main.py
       _pluto_is_online()と同じくiiod待受ポートの応答も合わせて要求する。
    2. Pluto+はPCの既定ルート(通常WiFi)とは別のUSB Ethernet gadgetアダプタ
       (既定IP 192.168.2.1)に直結されることが多いため、既定ルートの1本だけ
       でなく全インタフェースのサブネットを走査する(_local_ipv4_subnets参照)。
    あちらにあるESP32ブリッジ(hardware/ESP32_WiFi_Ethernet_Bridge)経由の
    第2段フォールバックは、Windows版のハードウェア構成
    (hardware/W5500_PA_PTT_Control)には存在しないため実装しない。
    """
    candidates: set[str] = set()
    for local_ip, prefix_len in _local_ipv4_subnets():
        host_bits = 32 - prefix_len
        if host_bits < 1 or host_bits > _DISCOVERY_MAX_SCAN_HOST_BITS:
            prefix_len = 24  # 想定外の範囲(検出失敗/広すぎるネットワーク)は/24にフォールバック
        network = ipaddress.ip_network(f"{local_ip}/{prefix_len}", strict=False)
        candidates.update(str(ip) for ip in network.hosts() if str(ip) != local_ip)
    if not candidates:
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = [
            host for host in executor.map(
                lambda h: _probe_pluto(h, timeout), candidates)
            if host
        ]
    if not results:
        return None
    return min(results, key=lambda ip: ipaddress.ip_address(ip))


def _build_udp_ts_url(settings: AppSettings) -> str:
    """Pluto+上のudpts.shが`tsp -I ip 0.0.0.0:8282`で待ち受けるUDP-TS宛先URL。"""
    return f"udp://{settings.pluto_host()}:{PLUTO_UDP_TS_PORT}?pkt_size=1316"


def _read_pluto_rx_sample_rate_hz(settings: AppSettings) -> Optional[int]:
    """送信設定反映後のPluto RX実サンプルレートをIIOから取得する。

    PlutoのTX設定はpluto_dvbがAD9361のクロック条件を調整するため、
    シンボルレート×2の要求値と、実際にRXへ流れるサンプルレートが異なる
    場合がある。送信開始後の実値を受信側にも使い、TX/RXのサンプルレートを
    常に一致させる。
    """
    if settings.is_loopback():
        return None
    try:
        result = subprocess.run(
            [platform_compat.find_binary("iio_attr"), "-u", settings.pluto_uri,
             "-i", "-c", "ad9361-phy", "voltage0", "sampling_frequency"],
            capture_output=True, text=True, timeout=3,
            **platform_compat.no_window_kwargs(),
        )
        value = int(float(result.stdout.strip()))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return value if value > 0 else None


def _push_pluto_settings(settings: AppSettings, lo_hz: float) -> None:
    """Pluto+の`/save.php`へDVB-S2パラメータをPOSTし、`/www/settings.txt`を書き換える。

    udpts.sh(常駐shループ)は毎周回settings.txtを読み直して`pluto_dvb`を
    正しいパラメータで再起動するため、ffmpeg側のUDP-TS送出を始める前にこれを
    呼んでおく必要がある(呼ばないとPlutoが直前の周波数/シンボルレートのまま
    変調し続け、RXが一切ロックしない)。FEC値はudpts.sh側の`pluto_dvb`引数と
    同じく"/"を除いた表記(例: "3/5"→"35")で送る。pilots/frame/rolloff等
    shonan_rx.py側にも対応する設定項目がない値は両者で固定の既定値に揃える
    (pilots=On, frame=LongFrame, rolloff=0.35)。
    """
    # 430MHz帯では438.200MHzのような小数MHzを使用するため、整数化しない。
    freq_mhz = f"{lo_hz / 1_000_000:.3f}"
    symbol_rate_ksps = round(settings.symbol_rate_msps * 1000)
    fec_field = settings.fec_rate.replace("/", "")
    power = str(int(settings.tx_power_db))
    data = urllib.parse.urlencode({
        "callsign": "NOCALL", "freq": str(freq_mhz), "channel": "Custom",
        "mode": "DVBS2", "mod": settings.modulation_scheme,
        "sr": str(symbol_rate_ksps), "srselect": "2000", "fec": fec_field,
        # 実機のpluto_dvb経路ではパイロットONの方がBBHEADER CRCエラーが
        # 大幅に減り、映像TSまで安定して到達することを確認済み。
        "pilots": "On", "frame": "LongFrame", "power": power,
        "rolloff": "0.35", "pcrpts": "800", "patperiod": "200",
        "h265box": "", "codec": "", "sound": "", "audioinput": "",
        "remux": "0", "trvlo": "0", "trvloselect": "0", "provname": "shonan",
    }).encode()
    req = urllib.request.Request(
        f"http://{settings.pluto_host()}/save.php", data=data, method="POST")
    last_error = None
    for attempt in range(3):
        try:
            _PLUTO_SETTINGS_OPENER.open(req, timeout=5).close()
            return
        except urllib.error.HTTPError as exc:
            # save.phpは保存後に302を返す。保存は完了しているため成功扱いに
            # し、リダイレクト先(Web UI)の応答待ちでTXを失敗させない。
            if exc.code in (301, 302, 303, 307, 308):
                return
            last_error = exc
            if attempt < 2:
                time.sleep(1)
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            last_error = exc
            if attempt < 2:
                # Pluto再起動直後やpluto_dvb再起動中はWeb CGIが一時的に
                # 応答しないことがあるため、TX開始を即時失敗にしない。
                time.sleep(1)
    raise last_error


def _send_ptt_request(host: str, state: str) -> None:
    """PA_Power/PTTコントローラ(ESP32+W5500、hardware/W5500_PA_PTT_Control)へ
    TX開始/終了を通知する(`GET /tx?state=on|off`)。

    ESP32側はこのリクエストのハンドラ内でPTT(GPIO27)のON/OFFのみを行う
    (12V電源には触れない)。未接続・応答なしの場合は例外をそのまま送出する
    (呼び出し側でログのみに握りつぶし、TX本体の動作は妨げない)。
    """
    url = f"http://{host}/tx?state={state}"
    urllib.request.urlopen(url, timeout=1.5).close()


# ESP32ファームウェア(hardware/W5500_PA_PTT_Control.ino)のPIN_OUTインデックスに対応。
PTT_CHANNEL_POWER = 0  # GPIO26: 12V電源(2SJ334ハイサイドスイッチ)
PTT_CHANNEL_PTT = 1    # GPIO27: PTT


def _send_ptt_channel_state(host: str, idx: int, state: str) -> None:
    """PA_Power/PTTコントローラ(ESP32+W5500)の個別チャンネルを明示的にON/OFFする
    (`GET /ch?idx=<idx>&state=on|off`)。

    Shonan_Lite-RasPI5(pi5/gui)アプリ本体の起動/終了に連動したGPIO26(12V電源、
    idx=PTT_CHANNEL_POWER)制御に使う。TX/RX切替(`_send_ptt_request()`)とは独立した経路。
    未接続・応答なしの場合は例外をそのまま送出する(呼び出し側でログのみに握りつぶす)。
    """
    url = f"http://{host}/ch?idx={idx}&state={state}"
    urllib.request.urlopen(url, timeout=1.5).close()


def _terminate_process_group(process: QtCore.QProcess, sig: int) -> None:
    """QProcess.terminate()/kill()は直接の子(bash -c '...')にしか届かず、
    パイプで繋いだffmpeg等の孫プロセスには届かない(bashが死んでも
    孤児として実行され続け、送信/受信が止まらない)。start()側でsetsidを使い
    bashをプロセスグループリーダーにしているため、そのグループ全体へ送る。
    ★Windowsではbash/setsid経由の起動をしない(RxController.start()参照)ため、
    プロセスグループの概念自体が不要。QProcess自身のterminate()/kill()で足りる。"""
    if platform_compat.IS_WINDOWS:
        if sig == platform_compat.SIGKILL:
            platform_compat.kill_process(process)
        else:
            platform_compat.terminate_process(process)
        return
    pid = int(process.processId())
    if pid <= 0:
        return
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


class TxController(QtCore.QObject):
    status_updated = QtCore.pyqtSignal(dict)  # {"connected": bool}
    log_line = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    stopped = QtCore.pyqtSignal()
    # 送信用FFmpegの同じ入力映像をrawvideoとして分岐し、送信画面の
    # プレビューへ渡す。カメラを別のFFmpegで二重に開かないための信号。
    preview_frame = QtCore.pyqtSignal(bytes, int, int)
    # ★Windows版のみ使用。RxControllerと同じ理由でQProcessではなくsubprocess.Popen
    # (コンソール窓抑止、_CREATE_NO_WINDOW参照)で起動するため、終了通知はシグナル経由。
    _tx_popen_finished = QtCore.pyqtSignal(object)

    _QUICK_FAIL_THRESHOLD_SEC = 3.0
    _MAX_CONSECUTIVE_QUICK_FAILURES = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[QtCore.QProcess] = None
        self._connected = False
        self._tx_packets = 0
        self._tx_frames = 0
        self._last_net_packets: Optional[int] = None
        self._pending_lines: list[str] = []
        self._status_dirty = False
        self._quiet_mode = False
        # ウォッチドッグ再接続用。stop()が呼ばれていないのにプロセスが
        # 終了したら再起動する。
        self._should_be_running = False
        self._last_settings: Optional[AppSettings] = None
        self._last_mode: Optional[str] = None  # "video" | "camera_audio"
        # ★カメラ競合等でffmpegが起動直後に即終了し続けるケースで、無限リトライだと
        # ユーザーに何も見えないままログだけが延々と積み上がる(実機で確認済み: 孤児化
        # したffmpegがカメラを握ったまま残るケースと重なり、リトライのたびに新しい
        # ffmpegプロセスが増殖する事態になっていた)。起動直後(_QUICK_FAIL_THRESHOLD_SEC
        # 未満)に終了することが_MAX_CONSECUTIVE_QUICK_FAILURES回続いたら、それ以上
        # リトライせずエラーとして表示する。
        self._consecutive_quick_failures = 0
        self._last_start_monotonic: Optional[float] = None
        self._preview_buffer = bytearray()
        self._preview_width = 640
        self._preview_height = 360
        self._emit_timer = QtCore.QTimer(self)
        self._emit_timer.setInterval(500)
        self._emit_timer.timeout.connect(self._flush_pending_output)
        # ★Windows版のみ使用(_launch_ffmpeg_windows参照)。プレビュー映像(rawvideo)は
        # RxControllerの受信映像と同じ理由でpyqtSignal(bytes)を使わずqueue.Queueで
        # 受け渡す。標準エラーのログ行もスレッド跨ぎで安全なqueue.Queueに統一する。
        self._tx_preview_queue: "queue.Queue[bytes]" = queue.Queue()
        self._tx_stderr_queue: "queue.Queue[str]" = queue.Queue()
        self._tx_preview_drain_timer = QtCore.QTimer(self)
        self._tx_preview_drain_timer.setInterval(30)
        self._tx_preview_drain_timer.timeout.connect(self._drain_tx_preview_queue)
        self._tx_popen_finished.connect(self._on_tx_popen_finished)

    def is_running(self) -> bool:
        if self._process is None:
            return False
        if isinstance(self._process, subprocess.Popen):
            return self._process.poll() is None
        return self._process.state() != QtCore.QProcess.NotRunning

    def get_status(self) -> dict:
        """quiet_mode(カメラ+音声診断)中はstatus_updatedを発行しないため、呼び出し側は
        これをポーリングして状態を読む(refresh_camera_audio_frame_counts()が併せて
        _connectedも更新する)。"""
        return {"connected": self._connected}

    def _launch_ffmpeg(self, args: list, *, output_file: Optional[str] = None,
                       preview_output: bool = False) -> None:
        if platform_compat.IS_WINDOWS:
            self._launch_ffmpeg_windows(args, output_file=output_file, preview_output=preview_output)
            return
        proc = QtCore.QProcess(self)
        proc.setProgram("ffmpeg")
        proc.setArguments(args)
        # プレビュー分岐時だけstdoutをrawvideo、stderrを進捗ログとして分離する。
        proc.setProcessChannelMode(
            QtCore.QProcess.SeparateChannels if preview_output
            else QtCore.QProcess.MergedChannels
        )
        # ★QProcessが既定でstdinを親と繋がった開いたままのパイプにしてしまい、
        # v4l2カメラ+ALSA同時キャプチャがそれに引きずられて断続的な不具合を起こすことが
        # 実機検証で判明した(real_pluto_bringup_status.md参照)。明示的にnullDeviceへ。
        proc.setStandardInputFile(QtCore.QProcess.nullDevice())
        if output_file:
            proc.setStandardOutputFile(output_file)
        elif preview_output:
            proc.readyReadStandardError.connect(lambda: self._on_output(proc, stderr=True))
            proc.readyReadStandardOutput.connect(lambda: self._on_preview_output(proc))
        else:
            proc.readyReadStandardOutput.connect(lambda: self._on_output(proc))
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(lambda err: self._on_ffmpeg_error(proc, err))
        proc.start()
        self._process = proc
        self._last_start_monotonic = time.monotonic()
        if not output_file:
            self._emit_timer.start()

    def _launch_ffmpeg_windows(self, args: list, *, output_file: Optional[str],
                                preview_output: bool) -> None:
        """Windows版ffmpeg起動。RxControllerと同じ理由でQProcessではなく
        subprocess.Popen(コンソール窓抑止、_CREATE_NO_WINDOW参照)を使う。
        output_fileモード(カメラ+音声診断ログ)は出力を丸ごとファイルへリダイレクト
        するだけでPython側のライブ読み出しが不要なため素直にPopenできる。
        preview_outputモード(実際の送信)はプレビュー映像(高頻度バイナリ)と
        ログ行(低頻度テキスト)をスレッドで読み、RxControllerのRX映像/ログと同じ
        queue.Queue + QTimerでメインスレッドへ受け渡す(pyqtSignal(bytes)の
        スレッド跨ぎemitで実機クラッシュが確認されたため、念のため踏襲する)。"""
        if output_file:
            try:
                out_fh = open(output_file, "wb")
            except OSError as exc:
                self.error.emit(f"ログファイルを開けませんでした: {exc}")
                return
            try:
                proc = subprocess.Popen(
                    ["ffmpeg"] + args, stdin=subprocess.DEVNULL,
                    stdout=out_fh, stderr=subprocess.STDOUT,
                    creationflags=_CREATE_NO_WINDOW,
                )
            except OSError:
                out_fh.close()
                self.error.emit(
                    tr("ffmpegの起動に失敗しました。PATHにffmpegが見つからない可能性があります。"
                       "インストール状態を確認してください。",
                       "Failed to start ffmpeg. ffmpeg may not be on the PATH. "
                       "Please check the installation.")
                )
                return
            finally:
                out_fh.close()  # 子プロセスは複製済みハンドルを保持するため親側は閉じてよい
            self._process = proc
            self._last_start_monotonic = time.monotonic()
            threading.Thread(target=self._wait_tx_popen, args=(proc,), daemon=True).start()
            return

        try:
            proc = subprocess.Popen(
                ["ffmpeg"] + args, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, creationflags=_CREATE_NO_WINDOW,
            )
        except OSError:
            self.error.emit(
                tr("ffmpegの起動に失敗しました。PATHにffmpegが見つからない可能性があります。"
                   "インストール状態を確認してください。",
                   "Failed to start ffmpeg. ffmpeg may not be on the PATH. "
                   "Please check the installation.")
            )
            return
        self._process = proc
        self._last_start_monotonic = time.monotonic()
        self._emit_timer.start()
        if preview_output:
            self._tx_preview_drain_timer.start()
        threading.Thread(target=self._pump_tx_stdout_popen, args=(proc,), daemon=True).start()
        threading.Thread(target=self._pump_tx_stderr_popen, args=(proc,), daemon=True).start()
        threading.Thread(target=self._wait_tx_popen, args=(proc,), daemon=True).start()

    def _pump_tx_stdout_popen(self, proc: subprocess.Popen) -> None:
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                self._tx_preview_queue.put(chunk)
        except (OSError, ValueError):
            pass

    def _pump_tx_stderr_popen(self, proc: subprocess.Popen) -> None:
        # ★readline()は\nまでしか区切らないが、ffmpegの進捗行("frame= 150 fps=...")は
        # \r区切りで出るため、readline()だと\nが来る(=ffmpeg終了時)まで「frame=」が
        # 1行に溜まり続け、TXが実際には送出できていても_connectedがTrueにならない
        # (機器試験が常に「健全サンプル=0/8」でTX NGになる、実機で確認)。Linux版
        # (QProcess+splitlines)と同じく、\r・\nの両方で区切る。
        pending = b""
        try:
            while True:
                chunk = proc.stderr.read(4096)
                if not chunk:
                    break
                *complete, pending = re.split(rb"[\r\n]+", pending + chunk)
                for raw_line in complete:
                    if raw_line:
                        self._tx_stderr_queue.put(raw_line.decode("utf-8", errors="replace"))
        except (OSError, ValueError):
            pass
        if pending:
            self._tx_stderr_queue.put(pending.decode("utf-8", errors="replace"))

    def _wait_tx_popen(self, proc: subprocess.Popen) -> None:
        proc.wait()
        self._tx_popen_finished.emit(proc)

    def _drain_tx_preview_queue(self) -> None:
        try:
            while True:
                chunk = self._tx_preview_queue.get_nowait()
                self._preview_buffer.extend(chunk)
        except queue.Empty:
            pass
        frame_size = self._preview_width * self._preview_height * 3
        while len(self._preview_buffer) >= frame_size:
            frame = bytes(self._preview_buffer[:frame_size])
            del self._preview_buffer[:frame_size]
            self.preview_frame.emit(frame, self._preview_width, self._preview_height)

    def _on_tx_popen_finished(self, proc: subprocess.Popen) -> None:
        if proc is not self._process:
            return  # 再起動後の古いプロセスからの遅延通知(実害なし)
        self._on_finished()

    def _on_ffmpeg_error(self, proc: QtCore.QProcess, err: QtCore.QProcess.ProcessError) -> None:
        # ★FailedToStart(実行ファイルが見つからない等)の場合、Qtはfinished()を発行しない
        # ため_on_finished()側の後始末が走らず、is_running()がFalseのまま無反応に見える。
        # ここで同じ後始末をした上でエラー内容をユーザーへ明示する。
        if err != QtCore.QProcess.FailedToStart:
            return
        self._emit_timer.stop()
        self._should_be_running = False
        if self._process is proc:
            self._process = None
        self.error.emit(
            tr("ffmpegの起動に失敗しました。PATHにffmpegが見つからない可能性があります。"
               "インストール状態を確認してください。",
               "Failed to start ffmpeg. ffmpeg may not be on the PATH. "
               "Please check the installation.")
        )
        self.stopped.emit()

    def start(self, settings: AppSettings) -> None:
        if self.is_running():
            return
        # ★_should_be_runningはstop()または連続クイック失敗時のみFalseに戻る。ここが
        # Falseということはユーザーが明示的に(再)開始した「新規開始」であることを示す
        # (_restart()経由の内部自動リトライ時はTrueのままstart()を呼ぶため、この
        # 判定はfreshスタート時のみ真になる)。_consecutive_quick_failuresを毎回
        # 無条件でリセットすると、以下のクイック失敗カウンタが実質的に機能しなく
        # なる不具合があったため、freshスタート時のみリセットする。
        is_fresh_start = not self._should_be_running
        if not settings.tx_mod_cod_supported():
            self.error.emit(
                f"未対応のMod-Cod組み合わせです: {settings.mod_cod()}\n"
                f"対応組み合わせ: {', '.join(TX_SUPPORTED_MODCODS)}"
            )
            return
        lo_hz = settings.effective_lo_hz()
        if lo_hz is None:
            self.error.emit(tr(
                "周波数が未設定です(ループバック試験を選択中はFrequency画面で手動設定してください)",
                "Frequency is not set (while a loopback test is selected, set it manually on the Frequency screen)"))
            return

        self._last_settings = settings
        self._last_mode = "video"
        self._should_be_running = True
        self._connected = False
        self._tx_packets = 0
        self._tx_frames = 0
        self._last_net_packets = None
        self._pending_lines = []
        self._status_dirty = False
        self._quiet_mode = False
        if is_fresh_start:
            self._consecutive_quick_failures = 0
        self._preview_buffer.clear()

        if settings.use_color_bar_source or settings.video_source == "colorbar":
            # Android版ColorBarSourceと同じ1920x1080固定画像を30fpsで反復する。
            video_args = [
                "-re", "-loop", "1", "-framerate", "30",
                "-i", str(ANDROID_TEST_PATTERN),
            ]
            # ★カラーバー画像自体に既にコールサインが描かれているため焼き込まない
            # (shonan_lite-ipad版VideoSourceSettingsViewと同じ扱い)。
            overlay_input_args: list[str] = []
            overlay_filter_args: list[str] = ["-vf", _TX_VIDEO_SCALE_FILTER]
            video_map = preview_video_map = "0:v"
            audio_index = 1
        elif settings.video_source == "file" and settings.video_file_path:
            # ★選択できるのは静止画のみ(videosource.py参照)。colorbarと同じ
            # 「-loop 1 -framerate 30」で静止画を反復送信する(動画ファイル用の
            # -stream_loopは静止画には効かない)。colorbarと違いこちらはユーザー
            # 選択の任意画像なので、カメラと同じくコールサイン・備考オーバーレイを
            # 適用できるようにする(_build_overlay_pipelineは"0:v"を土台に重ねる
            # だけなので、カメラでも静止画でも同じ仕組みで動く)。
            video_args = [
                "-re", "-loop", "1", "-framerate", "30",
                "-i", settings.video_file_path,
            ]
            overlay_input_args, overlay_filter_args, video_map, preview_video_map, audio_index = \
                _build_overlay_pipeline(settings, split_preview=True)
        else:
            video_args = platform_compat.camera_input_args(settings.camera_device)
            overlay_input_args, overlay_filter_args, video_map, preview_video_map, audio_index = \
                _build_overlay_pipeline(settings, split_preview=True)

        video_kbps = TX_VIDEO_BITRATE_BPS // 1000
        audio_kbps = TX_AUDIO_BITRATE_BPS // 1000
        if settings.is_loopback():
            output_url = f"udp://{settings.effective_loopback_host()}:{settings.rx_listen_port}?pkt_size=1316"
        else:
            try:
                _push_pluto_settings(settings, lo_hz)
            except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as exc:
                self.error.emit(f"Pluto設定送信に失敗しました: {exc}")
                return
            output_url = _build_udp_ts_url(settings)
        if settings.ptt_controller_host:
            try:
                _send_ptt_request(settings.ptt_controller_host, "on")
            except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
                self.log_line.emit(f"[PTT] ESP32への送信開始通知に失敗しました: {exc}")
        args = video_args + overlay_input_args + _audio_input_args() + overlay_filter_args + [
            "-map", video_map, "-map", f"{audio_index}:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            # ★repeat-headers=1必須: これがないとx264はSPS/PPSをエンコード開始時に
            # 1回しか出さない。RXは毎回TXの途中から視聴を始める(FIFOが先に開かれる保証も
            # ない)ため、その最初の1回を確実に逃し、以降デコーダが"non-existing PPS/SPS
            # referenced"を出し続けて一切復号できなくなる不具合が実機で確認された。
            "-x264-params", "nal-hrd=cbr:force-cfr=1:repeat-headers=1",
            "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k", "-bufsize", f"{video_kbps}k",
            "-g", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k",
            "-f", "mpegts", output_url,
            # 送信と同じ映像をプレビュー用rawvideoにも分岐する。
            "-map", preview_video_map, "-an", "-c:v", "rawvideo", "-pix_fmt", "rgb24",
            "-s", "640x360", "-r", "10", "-f", "rawvideo", "pipe:1",
        ]
        self._launch_ffmpeg(args, preview_output=True)

    def stop(self) -> None:
        was_running = self.is_running()
        self._should_be_running = False
        if was_running and self._last_settings and self._last_settings.ptt_controller_host:
            try:
                _send_ptt_request(self._last_settings.ptt_controller_host, "off")
            except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
                self.log_line.emit(f"[PTT] ESP32への送信終了通知に失敗しました: {exc}")
        if not was_running:
            return
        # ffmpegを直接起動している(setsid/bash -cのパイプ構成をやめた)ため、QProcessの
        # terminate()/kill()がそのままffmpeg本体に届く。
        if platform_compat.IS_WINDOWS:
            # ★WindowsのQProcess.terminate()はコンソールアプリ(ffmpegはその代表)に
            # WM_CLOSEを送るだけで、イベントループを持たないコンソールアプリはそれを
            # 一切処理できず無視される。5秒後の強制kill()を待つ間、停止ボタンを押しても
            # 実際には停止せずUIが「送信中」のまま固まって見える。さらに深刻なのは
            # MainWindow.closeEvent()経由でアプリを閉じる場合: このsingleShotタイマーが
            # 発火する前にQApplicationのイベントループごと終了してしまい、ffmpeg子
            # プロセスが孤児のまま生き残る。孤児ffmpegはUSBカメラ/マイクを握ったまま
            # 終了しないため、次回起動後の最初のTX開始が"Error during demuxing:
            # I/O error"で毎回失敗する不具合が実機で確認された。RxController.
            # _stop_process()と同じ理由(そちらも同種の不具合で先にkill()化済み)で、
            # Windowsでは最初からkill()を直接使う。
            self._process.kill()
        else:
            self._process.terminate()
            QtCore.QTimer.singleShot(5000, self._force_kill_if_still_running)

    def _force_kill_if_still_running(self) -> None:
        if self.is_running():
            self._process.kill()

    def _on_output(self, proc: QtCore.QProcess, *, stderr: bool = False) -> None:
        # ★行ごとにシグナルを同期発行せず、いったんバッファに溜めるだけにする
        # (start_camera_audio()実行中のquiet_modeではそもそもこのハンドラ自体を使わない)。
        # 実際の発行は_flush_pending_output()。
        channel = proc.readAllStandardError() if stderr else proc.readAllStandardOutput()
        data = bytes(channel).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._pending_lines.append(line)
            m = _TX_STREAMING_RE.search(line)
            if m:
                self._tx_frames = int(m.group(1))
                self._connected = True
                self._status_dirty = True

    def _on_preview_output(self, proc: QtCore.QProcess) -> None:
        self._preview_buffer.extend(bytes(proc.readAllStandardOutput()))
        frame_size = self._preview_width * self._preview_height * 3
        while len(self._preview_buffer) >= frame_size:
            frame = bytes(self._preview_buffer[:frame_size])
            del self._preview_buffer[:frame_size]
            self.preview_frame.emit(frame, self._preview_width, self._preview_height)

    def _flush_pending_output(self) -> None:
        # ★Windows版(_launch_ffmpeg_windows)はstderr行をqueue.Queue経由で受け渡す
        # (RxControllerと同じ理由でスレッドから直接signalをemitしない)。_on_output()
        # (QProcess経由、Linux)と同じ判定をここで行い、_pending_lines処理に合流させる。
        try:
            while True:
                line = self._tx_stderr_queue.get_nowait()
                self._pending_lines.append(line)
                m = _TX_STREAMING_RE.search(line)
                if m:
                    self._tx_frames = int(m.group(1))
                    self._connected = True
                    self._status_dirty = True
        except queue.Empty:
            pass
        net_packets = platform_compat.net_tx_packets()
        if net_packets is not None:
            if self._last_net_packets is not None:
                self._tx_packets = max(0, (net_packets - self._last_net_packets) * 2)
                self._status_dirty = True
            self._last_net_packets = net_packets
        if self._pending_lines:
            lines, self._pending_lines = self._pending_lines, []
            for line in lines:
                _safe_print(f"[tx] {line}")
                self.log_line.emit(line)
        if self._status_dirty:
            self._status_dirty = False
            self.status_updated.emit({
                "connected": self._connected,
                "packets": self._tx_packets,
                "frames": self._tx_frames,
            })

    def _on_finished(self) -> None:
        self._emit_timer.stop()
        self._tx_preview_drain_timer.stop()
        self._flush_pending_output()
        self._preview_buffer.clear()
        for q in (self._tx_preview_queue, self._tx_stderr_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        self._process = None
        ran_seconds = (
            time.monotonic() - self._last_start_monotonic
            if self._last_start_monotonic is not None else None
        )
        if ran_seconds is not None and ran_seconds < self._QUICK_FAIL_THRESHOLD_SEC:
            self._consecutive_quick_failures += 1
        else:
            self._consecutive_quick_failures = 0
        if self._should_be_running and self._last_settings is not None:
            if self._consecutive_quick_failures >= self._MAX_CONSECUTIVE_QUICK_FAILURES:
                # ★カメラ競合等でffmpegが起動直後に即終了し続ける場合、無限リトライだと
                # 何も表示されないままログだけが延々と積み上がる上、失敗のたびに新しい
                # ffmpegプロセスが増え続ける(孤児化と重なると特に深刻)。実機で確認済み。
                self._consecutive_quick_failures = 0
                self._should_be_running = False
                self.error.emit(
                    tr("送信用ffmpegの起動直後の終了が連続したため、自動リトライを"
                       "停止しました。カメラ/マイクが他のプロセスで使用中でないか、"
                       "コンソールログの詳細を確認してください。",
                       "TX ffmpeg exited immediately several times in a row, so automatic retry "
                       "was stopped. Check that the camera/microphone is not in use by another "
                       "process, and check the console log for details.")
                )
                self.stopped.emit()
                return
            settings, mode = self._last_settings, self._last_mode
            QtCore.QTimer.singleShot(500, lambda: self._restart(settings, mode))
        else:
            self.stopped.emit()

    def _restart(self, settings: AppSettings, mode: Optional[str]) -> None:
        if not self._should_be_running:
            return
        if mode == "camera_audio":
            self.start_camera_audio(settings)
        else:
            self.start(settings)

    def start_camera_audio(self, settings: AppSettings) -> None:
        """カメラ映像+USBカメラ内蔵マイク音声を実際にキャプチャしてPluto+へ送出する経路が
        健全かを確認する診断用。Android版 CameraAudioTxDiagPipeline
        (Camera/Mic→H.264/AAC→TS Mux→Dvbs2TxPipeline)のPi5移植。

        ffmpegの showinfo/ashowinfo フィルタ(1フレームごとに1行ログを出す)を使って、
        Android版のvideoFrameCount/audioFrameCountに相当する正確なフレーム数を取得する。
        """
        if self.is_running():
            return
        is_fresh_start = not self._should_be_running
        if not settings.tx_mod_cod_supported():
            self.error.emit(
                f"未対応のMod-Cod組み合わせです: {settings.mod_cod()}\n"
                f"対応組み合わせ: {', '.join(TX_SUPPORTED_MODCODS)}"
            )
            return
        lo_hz = settings.effective_lo_hz()
        if lo_hz is None:
            self.error.emit(tr("周波数が未設定です", "Frequency is not set"))
            return

        self._last_settings = settings
        self._last_mode = "camera_audio"
        self._should_be_running = True
        self._connected = False
        self._quiet_mode = True
        if is_fresh_start:
            self._consecutive_quick_failures = 0
        self.video_frame_count = 0
        self.audio_frame_count = 0
        self._ca_log_read_offset = 0
        # ffmpegの標準出力+標準エラー(showinfo/ashowinfoのログ含む)をファイルへ落とし、
        # get_status()/refresh_camera_audio_frame_counts()呼び出し時にポーリングで読む。
        self._ca_log_path = f"{settings.tmp_dir}/shonan_ca_ffmpeg.log"

        video_kbps = TX_VIDEO_BITRATE_BPS // 1000
        audio_kbps = TX_AUDIO_BITRATE_BPS // 1000
        # H.264/AACはPi 5で符号化し、Plutoのudpts.shはUDP-TSをそのまま変調へ渡す。
        try:
            _push_pluto_settings(settings, lo_hz)
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException) as exc:
            self.error.emit(f"Pluto設定送信に失敗しました: {exc}")
            return
        udp_ts_url = _build_udp_ts_url(settings)
        overlay_input_args, overlay_filter_args, video_map, _preview_video_map, audio_index = \
            _build_overlay_pipeline(settings, extra_video_filters="showinfo")
        args = platform_compat.camera_input_args(settings.camera_device) + overlay_input_args + \
            _audio_input_args() + overlay_filter_args + [
            "-map", video_map, "-map", f"{audio_index}:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
            # ★repeat-headers=1必須: これがないとx264はSPS/PPSをエンコード開始時に
            # 1回しか出さない。RXは毎回TXの途中から視聴を始める(FIFOが先に開かれる保証も
            # ない)ため、その最初の1回を確実に逃し、以降デコーダが"non-existing PPS/SPS
            # referenced"を出し続けて一切復号できなくなる不具合が実機で確認された。
            "-x264-params", "nal-hrd=cbr:force-cfr=1:repeat-headers=1",
            "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k", "-bufsize", f"{video_kbps}k",
            "-g", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-af", "ashowinfo",
            "-f", "mpegts", udp_ts_url,
        ]
        self._launch_ffmpeg(args, output_file=self._ca_log_path)

    def refresh_camera_audio_frame_counts(self) -> None:
        """診断中に1秒おき等で呼び、ffmpegのshowinfo/ashowinfoログファイルから
        映像/音声フレーム数を数え直し(Android版videoFrameCount/audioFrameCount相当)、
        併せて_connected(ffmpeg自身の進捗行の出現)も更新する。

        ★毎回ファイル全体を読み直して数え直す実装だと、ログが数千行に育つにつれ
        Qtイベントループを塞ぐ時間が伸びる懸念があったため(real_pluto_bringup_status.md
        参照)、前回読み取り位置以降の差分のみ読んで加算する。
        """
        log_path = getattr(self, "_ca_log_path", None)
        if not log_path or not os.path.exists(log_path):
            return
        offset = getattr(self, "_ca_log_read_offset", 0)
        try:
            with open(log_path, "r", errors="replace") as f:
                f.seek(offset)
                chunk = f.read()
                self._ca_log_read_offset = f.tell()
        except OSError:
            return
        self.video_frame_count += chunk.count("Parsed_showinfo")
        self.audio_frame_count += chunk.count("Parsed_ashowinfo")
        if not self._connected and _TX_STREAMING_RE.search(chunk):
            self._connected = True


class RxController(QtCore.QObject):
    status_updated = QtCore.pyqtSignal(dict)
    log_line = QtCore.pyqtSignal(str)
    error = QtCore.pyqtSignal(str)
    stopped = QtCore.pyqtSignal()
    video_frame = QtCore.pyqtSignal(bytes, int, int)

    # ★Windows版RXパイプライン(_start_windows_rx_pipeline)専用の内部シグナル。
    # shonan_rx.py子プロセスをQProcessで起動すると、GNU Radioのフローグラフ実行中に
    # アプリ全体が無言でクラッシュする不具合が実機で確認された(QProcess特有の問題:
    # 同じコマンドをsubprocess.Popenで起動すれば安定動作することを確認済み)。この
    # ためWindows側のみsubprocess.Popen+バックグラウンドスレッドで読み出す構成にし、
    # 読み出しスレッドからQtメインスレッド側へ安全に受け渡すためのシグナル。
    # ★復調後TSの生バイナリ(stdout)はpyqtSignal(bytes)でスレッドをまたいで直接
    # emitすると、実機でアプリ全体が無言でクラッシュする不具合が再現した(str型の
    # _rx_line_receivedや、実データと無関係なbytesシグナルでは再現しない、GNU Radio
    # フローグラフの実stdoutを読むスレッドからbytesをemitする組み合わせでのみ確認済み。
    # 原因はPyQt5側の未解明の問題の可能性が高い)。そのためstdoutのみシグナルを使わず
    # queue.Queue + QTimerポーリング(_stdout_drain_timer)でメインスレッドへ受け渡す。
    _rx_line_received = QtCore.pyqtSignal(str)
    _rx_popen_finished = QtCore.pyqtSignal(object)

    # TxController(TX側で以前確認済みの「ffmpegプロセス増殖」対策)と同じ考え方の
    # 無限リトライ防止。起動直後(_QUICK_FAIL_THRESHOLD_SEC未満)に終了することが
    # _MAX_CONSECUTIVE_QUICK_FAILURES回続いたら、自動リトライを止める。
    _QUICK_FAIL_THRESHOLD_SEC = 3.0
    _MAX_CONSECUTIVE_QUICK_FAILURES = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rx_process: Optional[QtCore.QProcess] = None
        self._ffplay_process: Optional[QtCore.QProcess] = None
        self._fifo_path: Optional[str] = None
        self._settings: Optional[AppSettings] = None
        self._last_frame_count = 0
        self._ms_since_progress = 0
        self._restart_pending = False
        self._consecutive_quick_failures = 0
        self._last_start_monotonic: Optional[float] = None
        # ★console=False(凍結ビルド)ではprint()の内容がユーザーから一切見えないため、
        # 直近のRX側ログを保持しておき、自動リトライを諦めた際のエラーメッセージに
        # 添えて原因調査の手がかりにする。
        self._recent_log_lines: collections.deque = collections.deque(maxlen=12)
        self._rx_line_received.connect(self._process_rx_line)
        self._rx_popen_finished.connect(self._on_rx_popen_finished)
        self._rx_stdout_queue: "queue.Queue[bytes]" = queue.Queue()
        self._stdout_drain_timer = QtCore.QTimer(self)
        self._stdout_drain_timer.setInterval(30)
        self._stdout_drain_timer.timeout.connect(self._drain_rx_stdout_queue)
        # ★Windows版RX表示用ffmpeg(_start_windows_rx_pipeline)もコンソール窓抑止のため
        # QProcessではなくsubprocess.Popenで起動する(_CREATE_NO_WINDOW参照)。その標準出力
        # (rawvideoフレーム)もrx_proc側と同じ理由でpyqtSignal(bytes)を使わず
        # queue.Queue + QTimerで受け渡す。
        self._video_stdout_queue: "queue.Queue[bytes]" = queue.Queue()
        self._video_drain_timer = QtCore.QTimer(self)
        self._video_drain_timer.setInterval(30)
        self._video_drain_timer.timeout.connect(self._drain_video_queue)
        self._video_buffer = bytearray()
        self._video_width = 640
        self._video_height = 360
        self._watchdog_timer = QtCore.QTimer(self)
        self._watchdog_timer.setInterval(WATCHDOG_INTERVAL_MS)
        self._watchdog_timer.timeout.connect(self._check_watchdog)

    def run_iio_preflight(self, settings: AppSettings, *, notify_error: bool = True) -> bool:
        """短いDMA読出しでPluto RX/IIOの健全性を確認する。"""
        if not settings.iio_preflight_enabled:
            self.log_line.emit("[iio-preflight] SKIPPED (disabled in settings)")
            return True
        if settings.is_loopback():
            return True
        probe_cmd = (
            "set -o pipefail; "
            f"iio_readdev -u {_quote(settings.pluto_uri)} -b 32768 "
            "cf-ad9361-lpc voltage0 voltage1 2>/tmp/shonan_iio_probe.err "
            "| head -c 4096 | wc -c"
        )
        try:
            probe = subprocess.run(
                ["bash", "-c", probe_cmd], capture_output=True,
                text=True, timeout=6)
            probe_bytes = int(probe.stdout.strip() or "0")
        except (OSError, ValueError, subprocess.TimeoutExpired):
            probe_bytes = 0
        if probe_bytes >= 4096:
            self.log_line.emit(f"[iio-preflight] OK ({probe_bytes} bytes)")
            return True
        message = (
            tr("Pluto RX DMAのIIOプリフライトに失敗しました。"
               "RF NO LOCKではありません。Plutoを再起動してから再試行してください。",
               "The IIO preflight of the Pluto RX DMA failed. "
               "This is not an RF NO LOCK. Restart the Pluto and try again.")
        )
        self.log_line.emit(f"[iio-preflight] FAILED: {message}")
        if notify_error:
            self.error.emit(message)
        return False

    def is_running(self) -> bool:
        # ★Windowsのみself._rx_processがsubprocess.Popen(QProcessではなく)になる
        # (_start_windows_rx_pipeline参照)ため、両対応で生存確認する。
        if self._rx_process is None:
            return False
        if isinstance(self._rx_process, subprocess.Popen):
            return self._rx_process.poll() is None
        return self._rx_process.state() != QtCore.QProcess.NotRunning

    def start(self, settings: AppSettings) -> None:
        if self.is_running():
            return
        # ★_settingsはstop()でのみNoneにされるため、ここがNoneということはユーザーが
        # 明示的に(再)開始した「新規開始」であることを示す。_on_finished()からの
        # 内部自動リトライ時はNoneのままstart()を再度呼ぶことはない(直接rx_proc起動へ
        # 進むため)ので、この判定はfreshスタート時のみ真になる。
        is_fresh_start = self._settings is None
        if not settings.rx_mod_cod_supported():
            self.error.emit(
                f"未対応のMod-Cod組み合わせです: {settings.mod_cod()}\n"
                f"対応組み合わせ: {', '.join(RX_SUPPORTED_MODCODS)}"
            )
            return
        lo_hz = settings.effective_lo_hz()
        if lo_hz is None:
            self.error.emit(tr("周波数が未設定です", "Frequency is not set"))
            return

        if platform_compat.IS_WINDOWS and not _gnuradio_available():
            self.error.emit(
                tr("このWindows開発環境にはGNU Radio(gr-iio/gr-dvbs2rx)が導入されて"
                   "おらず、実際のDVB-S2復調はできません。RXの動作確認はPi5実機で"
                   "行ってください。",
                   "GNU Radio (gr-iio/gr-dvbs2rx) is not installed in this Windows environment, "
                   "so actual DVB-S2 demodulation is not possible. Verify RX operation on a "
                   "Pi 5 unit.")
            )
            return

        if not self.run_iio_preflight(settings):
            return

        self._settings = settings
        self._last_frame_count = 0
        self._ms_since_progress = 0
        self._restart_pending = False
        if is_fresh_start:
            self._consecutive_quick_failures = 0

        # ★TxControllerは_push_pluto_settings()でpilots=Onを送るため、
        # RX側も--pilotsを明示してTXと一致させる。
        # 送信開始後のPluto実値をRXにも使う。取得できない場合だけ、従来の
        # symbol rate x 2へフォールバックする。
        requested_sample_rate_hz = settings.symbol_rate_hz() * 2
        sample_rate_hz = _read_pluto_rx_sample_rate_hz(settings) or requested_sample_rate_hz
        self.log_line.emit(
            f"[rx-sync] TX/RX sample rate={sample_rate_hz}Hz "
            f"(requested={requested_sample_rate_hz}Hz)"
        )

        if platform_compat.IS_WINDOWS:
            self._fifo_path = None
            self._start_windows_rx_pipeline(settings, lo_hz, sample_rate_hz)
            return

        fifo_path = f"{settings.tmp_dir}/shonan_rx_gui.ts"
        self._fifo_path = fifo_path
        rx_cmd = (
            f"rm -f {_quote(fifo_path)}; mkfifo {_quote(fifo_path)}; "
            f"python3 {APP_DIR}/rx/shonan_rx.py --pluto-uri {_quote(settings.pluto_uri)} "
            f"--lo-hz {lo_hz} --sample-rate-hz {sample_rate_hz} "
            f"--mod-cod {_quote(settings.mod_cod())} --pilots "
            f"--agc {'--agc' if settings.rx_agc_enabled else '--no-agc'} "
            f"--gain-db {settings.rx_gain_db} --output-fifo {_quote(fifo_path)} 2>&1"
        )

        proc = QtCore.QProcess(self)
        proc.setProgram("setsid")
        proc.setArguments(["bash", "-c", rx_cmd])
        # ★TxController.start()と同じ理由でstdinを明示的にnullDeviceへ
        # (real_pluto_bringup_status.md参照。RX側では未確認だが予防的に統一する)。
        proc.setStandardInputFile(QtCore.QProcess.nullDevice())
        proc.readyReadStandardOutput.connect(lambda: self._on_output(proc))
        proc.finished.connect(self._on_finished)
        proc.start()
        self._rx_process = proc
        self._last_start_monotonic = time.monotonic()
        self._watchdog_timer.start()

        # file_sink(RX側)はFIFOをwriteでopenする際、読み手が先にいないとブロックするため
        # 少し遅らせてffmpegを起動する(app/scripts/run_rx_display.shと同じ理由)。
        QtCore.QTimer.singleShot(1500, lambda: self._start_ffplay(fifo_path))

    def _build_display_ffmpeg_args(self, input_args: list[str]) -> list[str]:
        """RX表示用ffmpegの共通引数(FIFO読み込み/標準入力読み込みいずれでも使う)。
        input_argsは`-f mpegts`の入力元を指定する引数(例: ['-i', fifo_path] または
        ['-i', 'pipe:0'])。"""
        args = [
            '-loglevel', 'warning',
            # 無線経路では少数のTS/PES破損が発生するため、破損パケットで
            # デマルチプレクサ全体を停止させず、次のPAT/キーフレームから復帰させる。
            '-err_detect', 'ignore_err',
            '-fflags', '+discardcorrupt+nobuffer', '-flags', 'low_delay',
            '-probesize', '2M', '-analyzeduration', '1M',
            '-f', 'mpegts',
        ] + input_args + [
            '-an', '-vf', f'scale={self._video_width}:{self._video_height}',
            '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1',
        ]
        playback_device = _detect_playback_alsa_device()
        if playback_device is not None:
            args += ['-vn'] + platform_compat.playback_output_args(playback_device)
        return args

    def _start_windows_rx_pipeline(self, settings: AppSettings, lo_hz: float,
                                    sample_rate_hz: int) -> None:
        """Windowsにはmkfifo/setsidが無いため、shonan_rx.pyをffmpegの子プロセスとして
        直接起動し、標準出力を表示用ffmpegの標準入力へ流し込む(シェルの
        `shonan_rx.py | ffmpeg`相当)。

        ★以前はrx_proc側もQProcessで起動し、Qtの`QProcess.setStandardOutputProcess()`
        でffmpegへ直結していたが、実機でQProcess経由だとGNU Radioのフローグラフ
        実行中にアプリ全体が無言でクラッシュする不具合が確認された(受信開始のたびに
        コンソール窓が点滅を繰り返す症状の原因。fmcomms2_source単体やgnuradio importは
        QProcess経由でも問題なく、shonan_rx.pyのフルフローグラフ実行時のみ再現。
        同じコマンドをsubprocess.Popenで起動すれば安定動作することを確認済み)。
        そのためrx_proc側のみsubprocess.Popenへ切り替え、バックグラウンドスレッドで
        標準出力/標準エラーを読み出してQtメインスレッドへシグナル経由で受け渡す
        (_pump_rx_stdout_popen/_pump_rx_stderr_popen/_wait_rx_popen参照)。
        ffmpeg_proc側はQProcess単独起動では問題が再現しなかったため従来通り。"""
        rx_args = [
            platform_compat.gnuradio_python_executable(),
            str(APP_DIR / "rx" / "shonan_rx.py"),
            "--pluto-uri", settings.pluto_uri,
            "--lo-hz", str(lo_hz),
            "--sample-rate-hz", str(sample_rate_hz),
            "--mod-cod", settings.mod_cod(),
            "--pilots",
            "--agc" if settings.rx_agc_enabled else "--no-agc",
            "--gain-db", str(settings.rx_gain_db),
            "--output-stdout",
        ]
        rx_proc = subprocess.Popen(
            rx_args, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=_CREATE_NO_WINDOW,
        )

        try:
            ffmpeg_proc = subprocess.Popen(
                ['ffmpeg'] + self._build_display_ffmpeg_args(['-i', 'pipe:0']),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, creationflags=_CREATE_NO_WINDOW,
            )
        except OSError:
            # ★FailedToStart相当(実行ファイルが見つからない等)。rx_procは後始末のため
            # 一旦保持してからstop()に任せる。
            self._rx_process = rx_proc
            rx_proc.kill()
            self.error.emit(
                tr("ffmpegの起動に失敗しました(映像表示用)。PATHにffmpegが見つからない可能性があります。"
                   "インストール状態を確認してください。",
                   "Failed to start ffmpeg (for video display). ffmpeg may not be on the PATH. "
                   "Please check the installation.")
            )
            return

        self._rx_process = rx_proc
        self._ffplay_process = ffmpeg_proc
        self._last_start_monotonic = time.monotonic()
        self._watchdog_timer.start()
        self._stdout_drain_timer.start()
        self._video_drain_timer.start()

        threading.Thread(target=self._pump_ffmpeg_stdout_popen, args=(ffmpeg_proc,), daemon=True).start()
        threading.Thread(target=self._pump_ffmpeg_stderr_popen, args=(ffmpeg_proc,), daemon=True).start()

        threading.Thread(target=self._pump_rx_stdout_popen, args=(rx_proc,), daemon=True).start()
        threading.Thread(target=self._pump_rx_stderr_popen, args=(rx_proc,), daemon=True).start()
        threading.Thread(target=self._wait_rx_popen, args=(rx_proc,), daemon=True).start()

    def _pump_rx_stdout_popen(self, proc: subprocess.Popen) -> None:
        """rx_proc(subprocess.Popen)の標準出力(復調後TSの生バイナリ)を読み、
        self._rx_stdout_queueへ積む読み出しスレッド。ffmpeg_proc.write()はQt側の
        オブジェクトのためメインスレッドで呼ぶ必要があるが、pyqtSignal(bytes)で
        直接emitすると実機でアプリ全体が無言でクラッシュする不具合が確認された
        ため、queue.Queue + QTimer(_drain_rx_stdout_queue)で受け渡す。"""
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                self._rx_stdout_queue.put(chunk)
        except (OSError, ValueError):
            pass

    def _pump_rx_stderr_popen(self, proc: subprocess.Popen) -> None:
        """rx_proc(subprocess.Popen)の標準エラー(ステータス行)を1行ずつ読み、
        _rx_line_receivedシグナル経由でQtメインスレッドの_process_rx_line()へ渡す。"""
        try:
            for raw_line in iter(proc.stderr.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                self._rx_line_received.emit(line)
        except (OSError, ValueError):
            pass

    def _wait_rx_popen(self, proc: subprocess.Popen) -> None:
        proc.wait()
        self._rx_popen_finished.emit(proc)

    def _drain_rx_stdout_queue(self) -> None:
        """_stdout_drain_timer(Qtメインスレッド)から一定間隔で呼ばれ、
        _pump_rx_stdout_popen()が積んだ復調後TSデータをffmpeg(_ffplay_process、
        Windows版はsubprocess.Popen)の標準入力へ書き出す。"""
        try:
            while True:
                chunk = self._rx_stdout_queue.get_nowait()
                if self._ffplay_process is not None:
                    try:
                        self._ffplay_process.stdin.write(chunk)
                    except (OSError, ValueError):
                        pass  # ffmpeg_procが既に終了済み(停止競合、実害なし)
        except queue.Empty:
            pass

    def _pump_ffmpeg_stdout_popen(self, proc: subprocess.Popen) -> None:
        """ffmpeg_proc(RX表示用、subprocess.Popen)の標準出力(rawvideoフレーム)を
        読み、self._video_stdout_queueへ積む読み出しスレッド。"""
        try:
            while True:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                self._video_stdout_queue.put(chunk)
        except (OSError, ValueError):
            pass

    def _pump_ffmpeg_stderr_popen(self, proc: subprocess.Popen) -> None:
        """ffmpeg_proc(RX表示用、subprocess.Popen)の標準エラー(進捗ログ)を読む。
        _safe_print()自体はシグナルをemitしないため、直接スレッドから呼んでよい。"""
        try:
            for raw_line in iter(lambda: proc.stderr.readline(), b""):
                _safe_print(f"[video] {raw_line.decode('utf-8', errors='replace').strip()}")
        except (OSError, ValueError):
            pass

    def _drain_video_queue(self) -> None:
        """_video_drain_timer(Qtメインスレッド)から一定間隔で呼ばれ、
        _pump_ffmpeg_stdout_popen()が積んだrawvideoフレームをvideo_frameとしてemitする。"""
        try:
            while True:
                chunk = self._video_stdout_queue.get_nowait()
                self._video_buffer.extend(chunk)
        except queue.Empty:
            pass
        frame_size = self._video_width * self._video_height * 3
        while len(self._video_buffer) >= frame_size:
            frame = bytes(self._video_buffer[:frame_size])
            del self._video_buffer[:frame_size]
            self.video_frame.emit(frame, self._video_width, self._video_height)

    def _on_rx_popen_finished(self, proc: subprocess.Popen) -> None:
        # ★再起動後の古いスレッドから遅れて届いたfinished通知は無視する
        # (self._rx_processは既に新しいプロセスに差し替わっているはず)。
        if proc is not self._rx_process:
            return
        self._on_finished()

    def _start_ffplay(self, fifo_path: str) -> None:
        """FIFOを1つのffmpegプロセスだけで読み、映像は生RGBフレームとしてstdoutへ
        (video_frameシグナル経由でQt側QLabelへ描画)、音声はUSBオーディオへ直接出力する
        2系統出力にする。★GUI(Qt eglfs)がKMS/DRMディスプレイを既に占有しているため、
        ffplay単体をFIFOに向けて起動する方式(外部ウィンドウ表示)は、SDL2側が
        DRMマスターを取得できずダミードライバへ無言でフォールバックし、プロセスは
        生きたまま何も表示されない不具合が実機で確認された。ffmpegでRGBへ変換して
        Qt自身の描画パイプラインに乗せることでこの競合を回避する。FIFOは1プロセス
        しか安定して読めないため、映像と音声を同じffmpeg起動から分岐させる。
        ★音声出力先を汎用エイリアス"default"にするとQProcess経由で実機がクラッシュ
        した(この機体の"default"は再生に使えないデバイスへ解決されている模様)。
        USBオーディオのカード番号を_detect_playback_alsa_device()で動的検出して
        明示的に指定することで解消した。見つからない場合は音声出力なしで継続する。"""
        if self._ffplay_process is not None or self._settings is None:
            return
        self._video_buffer.clear()
        proc = QtCore.QProcess(self)
        proc.setProgram('ffmpeg')
        args = [
            '-loglevel', 'warning',
            # 無線経路では少数のTS/PES破損が発生するため、破損パケットで
            # デマルチプレクサ全体を停止させず、次のPAT/キーフレームから復帰させる。
            '-err_detect', 'ignore_err',
            '-fflags', '+discardcorrupt+nobuffer', '-flags', 'low_delay',
            '-probesize', '2M', '-analyzeduration', '1M',
            '-f', 'mpegts', '-i', fifo_path,
            '-an', '-vf', f'scale={self._video_width}:{self._video_height}',
            '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1',
        ]
        playback_device = _detect_playback_alsa_device()
        if playback_device is not None:
            args += ['-vn'] + platform_compat.playback_output_args(playback_device)
        proc.setArguments(args)
        proc.readyReadStandardOutput.connect(lambda: self._on_video_output(proc))
        proc.readyReadStandardError.connect(lambda: _safe_print(
            f"[video] {bytes(proc.readAllStandardError()).decode('utf-8', errors='replace').strip()}"))
        proc.errorOccurred.connect(lambda err: self._on_video_ffmpeg_error(proc, err))
        proc.start()
        self._ffplay_process = proc

    def _on_video_ffmpeg_error(self, proc: QtCore.QProcess, err: QtCore.QProcess.ProcessError) -> None:
        # ★FailedToStart(実行ファイルが見つからない等)はfinished()が発行されないため、
        # 従来はコンソールへのprintのみで、GUI上は無反応(RX映像が出ないだけ)に見えていた。
        # stop()を呼んでRXセッション全体を後始末しつつ、ユーザーへ明示する。
        if err != QtCore.QProcess.FailedToStart:
            return
        _safe_print(f"[video] QProcess error: {err}")
        self.stop()
        self.error.emit(
            tr("ffmpegの起動に失敗しました(映像表示用)。PATHにffmpegが見つからない可能性があります。"
               "インストール状態を確認してください。",
               "Failed to start ffmpeg (for video display). ffmpeg may not be on the PATH. "
               "Please check the installation.")
        )

    def _on_video_output(self, proc: QtCore.QProcess) -> None:
        self._video_buffer.extend(bytes(proc.readAllStandardOutput()))
        frame_size = self._video_width * self._video_height * 3
        while len(self._video_buffer) >= frame_size:
            frame = bytes(self._video_buffer[:frame_size])
            del self._video_buffer[:frame_size]
            self.video_frame.emit(frame, self._video_width, self._video_height)

    def set_volume(self, percent: int) -> None:
        """Android版RxController.setVolume相当。ffmpeg出力プロセスを再起動せず、
        OSのミキサーへ即時反映する(映像パイプラインの再起動によるIDR待ち=
        一瞬のフリーズを避けるため)。Linuxはamixer(ALSA PCMコントロール)、
        Windowsはpycaw(WASAPI既定エンドポイント)をplatform_compat経由で使う。"""
        platform_compat.set_playback_volume(percent)

    # ユーザー操作による明示的な停止。ウォッチドッグによる再起動は_stop_for_restart()を使う。
    def stop(self) -> None:
        _safe_print("[rx] stop() called (user pressed Stop, or main.py shutdown)")
        self._settings = None
        self._restart_pending = False
        self._watchdog_timer.stop()
        self._stop_process()

    def _stop_for_restart(self) -> None:
        self._watchdog_timer.stop()
        self._stop_process()

    def _stop_process(self) -> None:
        self._stdout_drain_timer.stop()
        self._video_drain_timer.stop()
        for q in (self._rx_stdout_queue, self._video_stdout_queue):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break
        if self._ffplay_process is not None:
            # ★terminate()(SIGTERM)は非同期でありプロセスが実際に終了する保証がない。
            # ここで確実に終了させないと、RX再起動(watchdog等)のたびに同じFIFOを
            # 読む古いffmpegプロセスが生き残り、新しいffmpegと2プロセスで同一FIFOを
            # 奪い合って映像ストリームが破損する不具合がPi4実機で確認された
            # (RXはlocked=trueでも映像が一切表示されない症状)。kill()(SIGKILL)は
            # 捕捉・無視できないため確実に終了する。
            self._ffplay_process.kill()
            self._ffplay_process = None
        self._video_buffer.clear()
        if not self.is_running():
            # ★プロセスが既に(watchdog検知前に)終了していた場合、QProcess.finishedは
            # 既に発火済みで_on_finished()もおそらく実行済みのため、ここで改めて
            # _on_finished()を呼び直し、_restart_pendingを見て再起動するかどうかを
            # 判定させる。以前はここで無条件にstopped.emit()していたため、watchdogが
            # 再起動フラグを立てた直後にプロセスが既に死んでいるタイミングと重なると、
            # 再起動されずそのまま停止してしまう不具合があった(実機で再現確認済み)。
            self._on_finished()
            return
        _terminate_process_group(self._rx_process, platform_compat.SIGTERM)
        QtCore.QTimer.singleShot(8000, self._force_kill_if_still_running)

    def _force_kill_if_still_running(self) -> None:
        if self.is_running():
            _terminate_process_group(self._rx_process, platform_compat.SIGKILL)

    def _check_watchdog(self) -> None:
        if not self.is_running():
            return
        self._ms_since_progress += WATCHDOG_INTERVAL_MS
        if self._ms_since_progress >= WATCHDOG_STALL_TIMEOUT_MS:
            # ★_stop_for_restart()が(プロセスが既に死んでいた場合)同じ呼び出しの中で
            # _on_finished()を介してさらに別のシグナルをemitすることがあり、1回の
            # 呼び出しの中で複数シグナルをemitすると実機でクラッシュする不具合が
            # 確認されている(_process_rx_line参照)。QTimer.singleShot(0, ...)で
            # 呼び出しスタックを分割する。
            QtCore.QTimer.singleShot(0, lambda: self.log_line.emit(
                f"[watchdog] frameが{WATCHDOG_STALL_TIMEOUT_MS // 1000}秒間進まないため"
                f"RXを再起動します"
            ))
            self._restart_pending = True
            self._stop_for_restart()

    def _on_output(self, proc: QtCore.QProcess, *, stderr: bool = False) -> None:
        # ★Windowsは標準出力をffmpegへのパイプに使う(_start_windows_rx_pipeline参照)
        # ため、shonan_rx.pyのステータス行(元々file=sys.stderrへ出力)は標準エラーから
        # 読む。Linux版はbashの2>&1で標準出力に合流させているため従来通りstderr=False。
        channel = proc.readAllStandardError() if stderr else proc.readAllStandardOutput()
        data = bytes(channel).decode("utf-8", errors="replace")
        for line in data.splitlines():
            self._process_rx_line(line)

    def _process_rx_line(self, line: str) -> None:
        """shonan_rx.pyの標準エラー出力1行分の共通処理。QProcess経由(Linux、
        _on_output参照)とsubprocess.Popen経由(Windows、_pump_rx_stderr_popen参照)
        の両方から呼ばれる。

        ★log_line信号は現状どの画面からも購読されていない(rx.py参照)。以前はここで
        毎行emitしていたが、実機で「1回の処理の中で2つ目のシグナルをemitする」と
        アプリ全体が無言でクラッシュする不具合が確認された(log_line.emit()の直後に
        status_updated.emit()も呼ばれるケースで再現、Windows版subprocess.Popen経由の
        RXでのみ発生。原因はPyQt5側の未解明の問題の可能性が高い)。誰も購読していない
        signalを削ってでもこの多重emitを避ける。"""
        _safe_print(f"[rx] {line}")
        self._recent_log_lines.append(line)
        m = _RX_STATUS_RE.search(line)
        if m:
            frame = int(m.group(3))
            if frame != self._last_frame_count:
                self._last_frame_count = frame
                self._ms_since_progress = 0
            self.status_updated.emit({
                "locked": m.group(1) == "True",
                "sof": int(m.group(2)),
                "frame": frame,
                "rejected": int(m.group(4)),
                "freq_off": float(m.group(5)),
                "packets": int(m.group(6)),
                "errors": int(m.group(7)),
            })

    def _on_finished(self) -> None:
        self._rx_process = None
        # ★self._settingsはstop()でのみNoneにされる。つまり「ユーザーが明示的に停止した
        # 場合」以外は理由を問わず(watchdogが停滞を検知してSIGTERMした場合はもちろん、
        # RXプロセス自体がwatchdogの検知前に予期せず終了・クラッシュした場合も含めて)
        # 常に再起動する。以前は_restart_pending(watchdogが停滞を検知した場合のみ立つ
        # フラグ)を見ていたため、プロセスが停滞検知に届く前に終了した場合(実機で
        # libiioの一時的なソケットエラー"Create socket: -113"が発生した際に再現確認済み)
        # に再起動されず、そのまま停止してしまう不具合があった。
        self._restart_pending = False
        ran_seconds = (
            time.monotonic() - self._last_start_monotonic
            if self._last_start_monotonic is not None else None
        )
        if ran_seconds is not None and ran_seconds < self._QUICK_FAIL_THRESHOLD_SEC:
            self._consecutive_quick_failures += 1
        else:
            self._consecutive_quick_failures = 0
        if self._settings is not None:
            if self._consecutive_quick_failures >= self._MAX_CONSECUTIVE_QUICK_FAILURES:
                # ★TxController.start()と同じ「起動直後の終了が連続したら自動リトライを
                # 止める」対策(IIOコンテキストの取得失敗等で永久に再起動し続け、コンソール
                # 窓が点滅し続ける不具合が実機で確認された)。
                _safe_print("[rx] giving up after repeated quick failures")
                self._settings = None
                self._consecutive_quick_failures = 0
                self._watchdog_timer.stop()
                recent_log = "\n".join(self._recent_log_lines) or tr("(ログなし)", "(no log)")
                message = (
                    tr("受信プロセスの起動直後の終了が連続したため、自動リトライを"
                       "停止しました。Pluto+の電源・接続状態を確認し、必要であれば"
                       "再起動してから再度お試しください。\n\n直近のログ:\n",
                       "The RX process exited immediately several times in a row, so automatic "
                       "retry was stopped. Check the power and connection of the Pluto+ and "
                       "restart it if necessary, then try again.\n\nRecent log:\n") + recent_log
                )
                # ★同じ呼び出しの中で2つ以上シグナルをemitすると、実機で(Windows版
                # subprocess.Popen経由のRX限定)アプリ全体が無言でクラッシュする不具合が
                # 確認された(_process_rx_line参照)。QTimer.singleShot(0, ...)で呼び出し
                # スタックを分割し、error/stoppedを別々のQtイベントとして発行する。
                QtCore.QTimer.singleShot(0, lambda: self.error.emit(message))
                QtCore.QTimer.singleShot(0, self.stopped.emit)
                return
            _safe_print("[rx] process ended unexpectedly (or watchdog stopped it), restarting")
            settings = self._settings
            QtCore.QTimer.singleShot(500, lambda: self.start(settings))
        else:
            _safe_print("[rx] stop() was called, not restarting")
            self._watchdog_timer.stop()
            self.stopped.emit()
