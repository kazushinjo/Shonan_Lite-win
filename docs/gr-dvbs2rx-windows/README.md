# Windows native build of gr-dvbs2rx (for real RX demodulation) / gr-dvbs2rxのWindowsネイティブビルド(実際のRX復調用)

The Windows dev port normally can't run `app/rx/shonan_rx.py` for real
(`ModuleNotFoundError: No module named 'gnuradio'`), because GNU Radio +
the DVB-S2 OOT modules it needs have no official Windows build. This
directory records how a working native build was produced on this machine,
so it can be reproduced after a machine reset or on another Windows PC.

WindowsのdevポートではGNU Radioと必要なDVB-S2 OOTモジュールの公式Windowsビルドがないため、
通常は`app/rx/shonan_rx.py`を実際に動かせません
(`ModuleNotFoundError: No module named 'gnuradio'`)。このディレクトリには、動作するネイティブビルドを
このマシンで作成した手順を記録してあり、マシンの初期化後や別のWindows PCでも再現できます。

## What's needed / 必要なもの

1. **radioconda** (a conda distribution of GNU Radio for Windows) —
   installs GNU Radio itself plus `gr-iio` prebuilt via conda-forge.
   Download the Windows installer from
   https://github.com/radioconda/radioconda-installer/releases and run it
   (`/InstallationType=JustMe /S` for a silent per-user install). Default
   install location assumed below: `%USERPROFILE%\radioconda`.  
   **radioconda**(WindowsのGNU Radio用condaディストリビューション) —
   GNU Radio本体と、conda-forge経由でビルド済みの`gr-iio`を導入します。
   https://github.com/radioconda/radioconda-installer/releases からWindows用インストーラを
   ダウンロードして実行します(ユーザー単位のサイレントインストールは`/InstallationType=JustMe /S`)。
   以下で想定する既定のインストール先は`%USERPROFILE%\radioconda`です。
2. **Visual Studio Build Tools 2022** with the "Desktop development with
   C++" workload (`Microsoft.VisualStudio.Workload.VCTools`) — needed to
   compile `gr-dvbs2rx` from source, since conda-forge does **not** ship a
   prebuilt `gr-dvbs2rx` package (unlike `gr-iio`, which radioconda already
   includes).  
   **Visual Studio Build Tools 2022**(「C++によるデスクトップ開発」ワークロード
   `Microsoft.VisualStudio.Workload.VCTools`付き) — `gr-dvbs2rx`をソースからコンパイルするために必要です。
   conda-forgeにはビルド済みの`gr-dvbs2rx`パッケージが**ありません**(radiocondaに最初から含まれる`gr-iio`とは異なります)。
3. `git` (already required elsewhere in this project).  
   `git`(このプロジェクトの他の箇所でも必要です)。

## What's in this directory / このディレクトリの内容

- `gr-dvbs2rx-windows-msvc.patch` — the patch to apply on top of
  [igorauad/gr-dvbs2rx](https://github.com/igorauad/gr-dvbs2rx) `master`
  (tested against commit `130c315`). It fixes everything MSVC rejects that
  GCC/Clang silently accept:  
  [igorauad/gr-dvbs2rx](https://github.com/igorauad/gr-dvbs2rx)の`master`(コミット`130c315`で検証)に
  適用するパッチです。GCC/Clangは黙って受け入れるがMSVCが拒否するものをすべて修正します:
  - GCC-only flags (`-march=native`, `-mavx2`, `-msse4.1`) → MSVC
    equivalents (`/arch:AVX2`) or omitted where intrinsics work unguarded.  
    GCC専用フラグ(`-march=native`、`-mavx2`、`-msse4.1`) → MSVC相当(`/arch:AVX2`)に置き換え、
    intrinsicsがそのまま動く箇所では省略。
  - C11 `aligned_alloc`/`free` (MSVC's CRT lacks it) → `_aligned_malloc`/
    `_aligned_free` on MSVC, unchanged on Linux (`lib/ldpc_decoder_bb_impl.cc`,
    `lib/ldpc_decoder/layered_decoder.hh`).  
    C11の`aligned_alloc`/`free`(MSVCのCRTにはない) → MSVCでは`_aligned_malloc`/`_aligned_free`、
    Linuxでは変更なし(`lib/ldpc_decoder_bb_impl.cc`、`lib/ldpc_decoder/layered_decoder.hh`)。
  - Raw C-style casts between `__m256i`/`__m256`/`__m256d` (a GCC/Clang
    extension) → proper `_mm256_castXX_YY` intrinsics (`avx2.hh`).  
    `__m256i`/`__m256`/`__m256d`間の生のCスタイルキャスト(GCC/Clangの拡張) → 正しい
    `_mm256_castXX_YY` intrinsicsに置き換え(`avx2.hh`)。
  - Variable-length arrays (C99/GNU extension, not supported by MSVC at
    all) → a `GR_DVBS2RX_VLA` macro (new file `portable_vla.hh`) that
    keeps the real VLA on GCC/Clang and falls back to a heap `std::vector`
    only under MSVC (`algorithms.hh`, `generic.hh`, `layered_decoder.hh`,
    `xfecframe_demapper_cb_impl.cc`).  
    可変長配列(C99/GNU拡張。MSVCは全く未対応) → `GR_DVBS2RX_VLA`マクロ(新規ファイル`portable_vla.hh`)。
    GCC/Clangでは本物のVLAを維持し、MSVCのときだけヒープ上の`std::vector`にフォールバック
    (`algorithms.hh`、`generic.hh`、`layered_decoder.hh`、`xfecframe_demapper_cb_impl.cc`)。
  - A `/utf-8` compile flag added for the `ldpc_decoder_*` CMake targets,
    since they don't link GNU Radio (which brings `/utf-8` in transitively
    elsewhere) and would otherwise mis-decode this patch's Japanese
    comments under the Japanese-locale default codepage (932), corrupting
    unrelated subsequent lines during parsing.  
    `ldpc_decoder_*`のCMakeターゲットに`/utf-8`コンパイルフラグを追加。これらはGNU Radioをリンクしない
    (他の箇所ではGNU Radioが推移的に`/utf-8`を持ち込む)ため、日本語ロケールの既定コードページ(932)では
    このパッチの日本語コメントを誤ってデコードし、解析中に無関係な後続行を壊してしまうためです。
  - `-DCMAKE_POLICY_VERSION_MINIMUM=3.5` is passed at configure time (not
    part of the patch) to tolerate the bundled `cpu_features` submodule's
    outdated `cmake_minimum_required`.  
    構成時に`-DCMAKE_POLICY_VERSION_MINIMUM=3.5`を渡します(パッチには含まれません)。同梱の
    `cpu_features`サブモジュールの古い`cmake_minimum_required`を許容するためです。
  - A genuine **pre-existing bug, not Windows-specific**, found while
    debugging a `STATUS_INTEGER_DIVIDE_BY_ZERO` crash inside
    `gnuradio-dvbs2rx.dll`: `ldpc_decoder_bb_impl::get_average_trials()`
    divided `d_total_trials / d_batch_cnt` with no zero-check. On real
    hardware, PL lock (and the first LDPC batch) normally completes well
    within the first status-print interval, so `d_batch_cnt` is never
    actually 0 when this getter gets called in practice — but any session
    that hasn't locked yet by the first status tick (e.g. no TX signal
    present, wrong frequency/symbol-rate, antenna path not connected)
    crashes the whole process deterministically. Fixed with a ternary
    guard. Found by resolving the crash's fault RVA against a
    `RelWithDebInfo` build's PDB (`dbghelp.dll` via ctypes -
    `SymFromAddr`/`SymGetLineFromAddr64`) after bisecting the flowgraph
    block-by-block with synthetic and real-Pluto sources to rule out
    everything else.  
    **Windows固有ではない既存の本物のバグ**。`gnuradio-dvbs2rx.dll`内の`STATUS_INTEGER_DIVIDE_BY_ZERO`
    クラッシュをデバッグ中に発見しました: `ldpc_decoder_bb_impl::get_average_trials()`が
    `d_total_trials / d_batch_cnt`をゼロ判定なしで割っていました。実機ではPLロック(と最初のLDPCバッチ)は
    通常、最初のステータス出力間隔内に十分完了するため、このゲッターが呼ばれる時点で`d_batch_cnt`が
    0になることは実際にはありません。しかし、最初のステータスの時点でまだロックしていないセッション
    (例: TX信号がない、周波数/シンボルレートが違う、アンテナ経路が未接続)ではプロセス全体が
    確実にクラッシュします。三項演算子のガードで修正しました。合成信号と実Plutoのソースでフローグラフを
    ブロックごとに切り分けて他の原因を除外したのち、クラッシュのフォールトRVAを`RelWithDebInfo`ビルドの
    PDBで解決して(ctypes経由の`dbghelp.dll`の`SymFromAddr`/`SymGetLineFromAddr64`)特定しました。
- `build_gr_dvbs2rx_windows.bat` — clones gr-dvbs2rx (if not already
  present), applies the patch, configures with CMake+Ninja against
  radioconda's GNU Radio, builds, and installs into radioconda's own
  environment (so `from gnuradio import dvbs2rx` works from
  `radioconda\python.exe`).  
  `build_gr_dvbs2rx_windows.bat` — gr-dvbs2rxをクローンし(未取得の場合)、パッチを適用し、radiocondaの
  GNU Radioに対してCMake+Ninjaで構成・ビルドし、radioconda自身の環境へインストールします
  (`radioconda\python.exe`から`from gnuradio import dvbs2rx`が動作します)。

## Running it / 実行方法

From a normal (non-admin) shell, with radioconda and the VS Build Tools
C++ workload already installed:

radiocondaとVS Build ToolsのC++ワークロードを導入済みの状態で、通常の(管理者ではない)シェルから実行します:

```
docs\gr-dvbs2rx-windows\build_gr_dvbs2rx_windows.bat
```

Edit the `RADIOCONDA` and `GR_DVBS2RX_SRC` variables at the top of the
script first if your radioconda install or desired clone location differ
from the defaults.

radiocondaの導入先や希望のクローン先が既定と異なる場合は、先にスクリプト冒頭の`RADIOCONDA`と
`GR_DVBS2RX_SRC`変数を編集してください。

## Why this lives outside `.venv-win` / `.venv-win`の外に置く理由

The GUI app itself runs under `.venv-win` (a plain python.org Python,
matching this port's normal dependency story). GNU Radio has no pip
wheels for Windows, so it lives in the separate radioconda environment.
`app/gui/platform_compat.py`'s `gnuradio_python_executable()` finds that
radioconda interpreter at runtime and `RxController` launches
`shonan_rx.py` with it instead of `.venv-win`'s Python — see
`app/gui/backend.py`.

GUIアプリ自体は`.venv-win`(python.org標準のPython。このポートの通常の依存関係の方針に合わせたもの)で
動作します。GNU RadioにはWindows用のpip wheelがないため、別のradioconda環境に置かれます。
`app/gui/platform_compat.py`の`gnuradio_python_executable()`が実行時にそのradiocondaのインタプリタを
探し、`RxController`は`.venv-win`のPythonではなくそれを使って`shonan_rx.py`を起動します —
`app/gui/backend.py`を参照してください。
