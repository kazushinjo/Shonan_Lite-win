"""OS依存処理を集約するモジュール(Windows 11移植対応)。

app/gui は元々 Raspberry Pi OS(Linux/aarch64)専用に書かれていた。Windows 11でも
同じコードベースで動かすため、Linux固有のコマンド・パス・API呼び出しをこのモジュール
経由に置き換える。既存のLinux(Pi5実機)側の挙動・性能特性は変更しない
(IS_WINDOWSがFalseの分岐は、元のコードとできる限り同じ実装を保つ)。

対応方針の詳細は docs/windows_port_notes.md および会話ログのポーティング計画を参照。
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

IS_WINDOWS = sys.platform == "win32"


def app_dir() -> Path:
    """`app/`ディレクトリを返す(ソース実行時・PyInstaller凍結時の両方に対応)。

    PyInstallerで固めた場合、`screens/home.py`等のエントリスクリプト以外の
    モジュールは`__file__`がPYZアーカイブ内の実在しないパスになり、
    `Path(__file__).resolve().parents[N]`によるデータファイル探索が壊れる。
    凍結時は`sys._MEIPASS`(bundle実行時にデータ一式を展開・配置したルート)を
    使う。ビルド側で`app/docs`・`app/assets`等をbundleルート直下に
    `docs`・`assets`という相対パスのまま配置することが前提。
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def _add_bundled_ffmpeg_to_path() -> None:
    """インストーラ同梱のffmpeg.exeを`ffmpeg`コマンドとして解決できるようにする。

    ffmpeg呼び出しは各所で`"ffmpeg"`という裸のコマンド名のまま`subprocess`に
    渡しており、OSのPATH解決に依存している。インストーラは`{app}\\ffmpeg\\`に
    ffmpeg.exeを同梱する(システム全体のPATHは変更しない)ため、凍結実行時のみ
    このプロセスのPATH環境変数の先頭にそのフォルダを足す。
    """
    if not (IS_WINDOWS and getattr(sys, "frozen", False)):
        return
    ffmpeg_dir = Path(sys.executable).resolve().parent / "ffmpeg"
    if ffmpeg_dir.is_dir():
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")


_add_bundled_ffmpeg_to_path()

# ★Windowsのsignalモジュールには SIGKILL が定義されていない(SIGTERMのみ)。
# `signal.SIGKILL` を直接参照するとWindowsでは属性アクセス自体がAttributeErrorになる
# ため、両OSで安全に使える定数をここで用意する。
SIGTERM = signal.SIGTERM
SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)

_PLUTO_SSH_USER = "root"
_PLUTO_SSH_PASSWORD = "analog"


# ---------------------------------------------------------------------------
# 一時ディレクトリ / パス
# ---------------------------------------------------------------------------

def default_tmp_dir() -> str:
    """設定の既定tmp_dir値。Linuxは従来通り/tmp、Windowsは%TEMP%
    (どちらも既存ディレクトリなので追加のmkdirは不要)。"""
    if IS_WINDOWS:
        return tempfile.gettempdir()
    return "/tmp"


def tmp_path(filename: str) -> str:
    """OSの一時ディレクトリ配下のファイルパス(main.pyのスクリーンショット保存等)。"""
    base = Path(tempfile.gettempdir()) if IS_WINDOWS else Path("/tmp")
    return str(base / filename)


def default_camera_device() -> str:
    """設定の既定camera_device値。WindowsはDirectShowデバイス名(起動時に実デバイス名へ
    差し替えられる想定のプレースホルダ)、Linuxは従来通り/dev/video0。"""
    if IS_WINDOWS:
        return ""
    return "/dev/video0"


# ---------------------------------------------------------------------------
# 映像オーバーレイ用フォント(コールサイン・備考焼き込み。backend.py参照)
# ---------------------------------------------------------------------------

def overlay_ascii_font() -> str:
    """英数字用の太字フォント。Linuxは従来通りDejaVu Sans Bold、Windowsは
    標準搭載のArial Bold(OSインストール直後から常に存在する)を使う。"""
    if IS_WINDOWS:
        return str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arialbd.ttf")
    return "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def overlay_cjk_font() -> str:
    """日本語(CJK)用の太字フォント。Linuxは従来通りDroid Sans Fallback、Windowsは
    標準搭載の游ゴシックBold(Windows 10/11に常に含まれる)を使う。"""
    if IS_WINDOWS:
        return str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "YuGothB.ttc")
    return "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"


# ---------------------------------------------------------------------------
# 外部コマンド解決
# ---------------------------------------------------------------------------

def _radioconda_root() -> Optional[Path]:
    """radioconda(https://github.com/radioconda/radioconda-installer)のインストール
    ルートを探す。環境変数SHONAN_GNURADIO_PYTHONが指定されていればそのpython.exeの
    親ディレクトリを優先する(gnuradio_python_executable()と同じ環境を指すため)。"""
    override = os.environ.get("SHONAN_GNURADIO_PYTHON")
    if override and Path(override).exists():
        return Path(override).resolve().parent
    candidates = [
        Path.home() / "radioconda",
        Path("C:/radioconda"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "radioconda",
    ]
    for candidate in candidates:
        # python.exeまで確認する。Lib\だけ残った不完全なフォルダを選ぶと、
        # gnuradio_python_executable()がsys.executableへフォールバックしてしまう。
        if (candidate / "python.exe").exists():
            return candidate
    return None


def gnuradio_python_executable() -> str:
    """`shonan_rx.py`(gnuradio + gr-iio + gr-dvbs2rx依存)を実行するためのPython
    インタプリタパスを返す。Linuxは`sys.executable`(システムPython3にgnuradioが
    インストール済みの前提、既存Pi5実機と同じ)。Windowsは`.venv-win`にgnuradio
    バイナリが存在しない(PyQt5 GUI本体用の別venvのため)ので、radioconda
    (https://github.com/radioconda/radioconda-installer)でインストールした
    別のPython環境を探して使う。環境変数SHONAN_GNURADIO_PYTHONで明示指定も可能。
    見つからない場合は`sys.executable`にフォールバックする(その場合gnuradio
    インポートに失敗し、呼び出し側のRxController側チェックでエラーになる)。"""
    if not IS_WINDOWS:
        return sys.executable
    override = os.environ.get("SHONAN_GNURADIO_PYTHON")
    if override and Path(override).exists():
        return override
    root = _radioconda_root()
    if root is not None:
        candidate = root / "python.exe"
        if candidate.exists():
            return str(candidate)
    return sys.executable


def find_binary(name: str, fallback_unix_path: Optional[str] = None) -> str:
    """PATH上の実行ファイルを解決する。Windowsは`shutil.which`(.exe拡張子を自動解決)、
    Linuxは従来のPATH解決に加えfallback_unix_pathがあればそれを最終手段として使う
    (例: /usr/bin/iio_attr が絶対パス直書きされていた既存コードの置き換え用)。
    `iio_info`/`iio_attr`等のlibiio付属コマンドはこのアプリの通常のPATHには
    含まれておらず、radioconda環境(gnuradio_python_executable()参照)にのみ
    `Library/bin/`配下として存在するため、Windowsではそこも探す。
    見つからない場合はnameそのものを返す(呼び出し側のsubprocessがPATHから探す)。"""
    found = shutil.which(name)
    if found:
        return found
    if IS_WINDOWS:
        root = _radioconda_root()
        if root is not None:
            candidate = root / "Library" / "bin" / f"{name}.exe"
            if candidate.exists():
                return str(candidate)
    elif fallback_unix_path and Path(fallback_unix_path).exists():
        return fallback_unix_path
    return name


def no_window_kwargs() -> dict:
    """subprocess.run()/Popen()へ`**no_window_kwargs()`として渡すkwargs。

    Windowsではコンソールアプリ(ffmpeg.exe、iio_attr.exe、radioconda\\python.exe等)を
    subprocessで起動すると、アプリ本体がconsole=False(凍結ビルド)でも子プロセス自体は
    新規コンソール窓を割り当ててしまい、送信/受信開始のたびに一瞬表示される不具合が
    あった。CREATE_NO_WINDOWフラグでこれを抑止する。Linuxではコンソールの概念が
    異なる(常にターミナルへの標準出力のみ)ため何もしない。"""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


# ---------------------------------------------------------------------------
# カメラ(v4l2 / DirectShow)
# ---------------------------------------------------------------------------

_DSHOW_DEVICE_RE = re.compile(r'^\[[^\]]*\]\s+"(.+)"\s*(?:\((video|audio)\))?\s*$')
_DSHOW_SECTION_VIDEO = "DirectShow video devices"
_DSHOW_SECTION_AUDIO = "DirectShow audio devices"


def _list_dshow_devices() -> tuple[list[str], list[str]]:
    """`ffmpeg -f dshow -list_devices true -i dummy` の標準エラー出力から
    (映像デバイス名一覧, 音声デバイス名一覧) を得る。ffmpeg未導入・失敗時は([], [])。
    ffmpegのバージョンにより出力形式が異なり、旧版は"DirectShow video/audio devices"
    という見出し行の下に各デバイス行が続く形式、新版(9.0系で確認)は見出し行が無く
    各デバイス行末に"(video)"/"(audio)"が付く形式なので、両方に対応する。"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-f", "dshow", "-list_devices", "true", "-i", "dummy"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=6,
            **no_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return [], []
    videos: list[str] = []
    audios: list[str] = []
    section = None
    for line in (result.stderr or "").splitlines():
        if _DSHOW_SECTION_VIDEO in line:
            section = "video"
            continue
        if _DSHOW_SECTION_AUDIO in line:
            section = "audio"
            continue
        if "Alternative name" in line:
            continue
        m = _DSHOW_DEVICE_RE.match(line.strip())
        if not m:
            continue
        kind = m.group(2) or section
        if kind == "video":
            videos.append(m.group(1))
        elif kind == "audio":
            audios.append(m.group(1))
    return videos, audios


def list_camera_devices() -> list[str]:
    """カメラ列挙。Linuxは/dev/video[0-9]、Windowsはffmpeg dshowの映像デバイス名一覧。"""
    if IS_WINDOWS:
        videos, _audios = _list_dshow_devices()
        return videos
    import glob
    return sorted(glob.glob("/dev/video[0-9]"))


def camera_input_args(device: str, *, video_size: Optional[str] = None) -> list[str]:
    """ffmpegのカメラ入力引数一式。deviceはlist_camera_devices()が返す値
    (Linux: /dev/videoN、Windows: dshowデバイス名)。"""
    args: list[str] = []
    if video_size:
        args += ["-video_size", video_size]
    if IS_WINDOWS:
        return ["-f", "dshow"] + args + ["-i", f"video={device}"]
    return ["-f", "v4l2"] + args + ["-i", device]


def release_camera_device(_device: str) -> None:
    """Linuxの`fuser -k <device>`相当。Windowsには汎用の同等コマンドが無く、
    アプリ側でQProcessを確実にkill()していれば追加処理は不要なため何もしない。"""
    if IS_WINDOWS:
        return
    try:
        subprocess.run(
            ["fuser", "-k", _device],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------------------
# オーディオ(ALSA / DirectShow+WASAPI)
# ---------------------------------------------------------------------------

_CAMERA_AUDIO_NAME_HINT = "C920"
_PLAYBACK_NAME_HINT = "USB"


def detect_camera_audio_device() -> Optional[str]:
    """カメラ内蔵マイクの入力デバイス名(TX音声用)。見つからなければNone
    (呼び出し側は無音AAC入力へフォールバックする、既存Linux実装と同じ扱い)。"""
    if IS_WINDOWS:
        _videos, audios = _list_dshow_devices()
        for name in audios:
            if _CAMERA_AUDIO_NAME_HINT in name:
                return name
        return audios[0] if audios else None
    try:
        result = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first_capture = None
    for line in result.stdout.splitlines():
        m = re.match(r"card (\d+):.*device (\d+):", line)
        if not m:
            continue
        device = f"plughw:{m.group(1)},{m.group(2)}"
        if first_capture is None:
            first_capture = device
        if _CAMERA_AUDIO_NAME_HINT in line:
            return device
    return first_capture


def audio_input_args() -> list[str]:
    """TX側ffmpegの音声入力引数一式。マイクが見つからない場合は無音AAC入力
    (既存Linux実装の_audio_input_args()と同じフォールバック方針)。"""
    device = detect_camera_audio_device()
    if device is not None:
        if IS_WINDOWS:
            return ["-f", "dshow", "-i", f"audio={device}"]
        return ["-f", "alsa", "-i", device]
    return [
        "-f", "lavfi", "-i",
        "anullsrc=channel_layout=mono:sample_rate=48000",
    ]


def detect_playback_device() -> Optional[str]:
    """RX音声再生の出力先。Linuxは"USB"を含むALSAカードを動的検出。
    ★Windowsは常にNoneを返す(=RX音声再生を無効化)。以前は"default"を返し
    playback_output_args()が`-f dsound <device>`をffmpegの出力(-O)側に
    付けていたが、`dsound`はffmpegではWindowsの録音入力デバイス専用の形式で
    再生(出力)ミューサーとしては存在しない(`ffmpeg -devices`にも出力可能な
    Windows音声デバイスは一つも無い)。そのためRX表示用ffmpegが起動直後に
    出力初期化エラーで即終了し、映像が一切表示されないだけでなく、読み手を
    失ったパイプが満杯になった時点(実機で常に同じパケット数、例えば1154で
    発生)でRX側のfile_descriptor_sink書き込みが永久にブロックする不具合が
    あった。Windows側での音声再生は別の仕組み(例:pycaw/WASAPI経由の独自
    プレーヤー)を今後実装するまで保留し、まずは映像を確実に流すことを優先
    する。"""
    if IS_WINDOWS:
        return None
    try:
        result = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in result.stdout.splitlines():
        m = re.match(r"card (\d+):.*device (\d+):", line)
        if not m:
            continue
        if _PLAYBACK_NAME_HINT in line:
            return f"plughw:{m.group(1)},{m.group(2)}"
    return None


def playback_output_args(device: str) -> list[str]:
    """ffmpegの音声出力引数一式(RX再生)。"""
    if IS_WINDOWS:
        return ["-f", "dsound", device]
    return ["-f", "alsa", device]


def set_playback_volume(percent: int) -> None:
    """RX再生音量の即時反映。Linuxはamixer(ALSA PCMコントロール)、Windowsは
    pycaw(WASAPI既定エンドポイントのマスターボリューム)。pycaw未導入/失敗時は
    無音で諦める(ボリュームスライダー自体は動くがハードウェアに反映されないだけ
    にとどめ、RXの映像/音声出力自体は止めない)。"""
    if IS_WINDOWS:
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(
                IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, percent / 100.0)), None)
        except Exception:
            pass
        return
    device = detect_playback_device()
    if device is None:
        return
    m = re.match(r"plughw:(\d+),", device)
    if not m:
        return
    try:
        subprocess.run(
            ["amixer", "-c", m.group(1), "sset", "PCM", f"{percent}%"],
            capture_output=True, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


# ---------------------------------------------------------------------------
# ネットワーク統計(TXパケット数表示用)
# ---------------------------------------------------------------------------

def net_tx_packets() -> Optional[int]:
    """送信パケット数の累積値。Linuxは従来通りeth0のsysfsカウンタ、Windowsは
    psutilで全NIC合算の送信パケット数を使う(表示用の目安値のため厳密なNIC一致は
    不要)。psutil未導入時はNoneを返し、呼び出し側はこれまで通り表示を更新しない。"""
    if IS_WINDOWS:
        try:
            import psutil
            return psutil.net_io_counters().packets_sent
        except Exception:
            return None
    try:
        return int(Path("/sys/class/net/eth0/statistics/tx_packets").read_text())
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Pluto+ SSH制御(reboot等)。sshpass依存を排除するため両OS共通でparamikoを使う。
# ---------------------------------------------------------------------------

def reboot_pluto(host: str, *, wait: bool = False, timeout: float = 10.0) -> None:
    """Pluto+をSSH経由で再起動する。wait=Trueなら送信完了(または接続失敗確定)まで
    ブロックする(Langstone切替直前など、プロセス終了前に確実に送りたい場合用)。
    失敗は無視する(呼び出し側は元々fire-and-forget、またはベストエフォート扱い)。
    """
    def _do_reboot() -> None:
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                host, username=_PLUTO_SSH_USER, password=_PLUTO_SSH_PASSWORD,
                timeout=min(timeout, 6.0), look_for_keys=False, allow_agent=False,
            )
            client.exec_command("reboot", timeout=timeout)
            client.close()
        except Exception:
            pass

    if wait:
        _do_reboot()
        return
    import threading
    threading.Thread(target=_do_reboot, daemon=True).start()


def ssh_read_file(host: str, remote_path: str, *, timeout: float = 8.0) -> Optional[str]:
    """SSH経由でPluto+上の小さなテキストファイルを読む(main.pyの設定読み戻し確認用)。
    失敗時はNone。"""
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host, username=_PLUTO_SSH_USER, password=_PLUTO_SSH_PASSWORD,
            timeout=min(timeout, 6.0), look_for_keys=False, allow_agent=False,
        )
        _stdin, stdout, _stderr = client.exec_command(f"cat {remote_path}", timeout=timeout)
        data = stdout.read().decode("utf-8", errors="replace")
        client.close()
        return data
    except Exception:
        return None


# ---------------------------------------------------------------------------
# プロセス終了(mkfifo/setsid経路を使わないため、Windowsではプロセスグループ操作は不要)
# ---------------------------------------------------------------------------

def terminate_process(process) -> None:
    """QProcessを穏当に終了させる(SIGTERM相当)。両OSともQProcess.terminate()で足りる
    (RX/TX ともQProcessをbash経由で起動しない構成にしたため、子孫プロセスへの
    signal配送を自前で行うos.killpg等は不要)。"""
    process.terminate()


def kill_process(process) -> None:
    """QProcessを強制終了させる(SIGKILL相当)。"""
    process.kill()
