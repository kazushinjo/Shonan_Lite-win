# インストーラのビルド / Building the installer

配布インストーラ `ShonanLiteSetup.exe`(約700MB)をソースから作る手順。
How to build the distributed installer `ShonanLiteSetup.exe` (about 700 MB) from source.

## 事前準備 / Prerequisites

1. **Git・Python 3**(Windows用の Python ランチャー `py` を含む。動作確認済み: 3.14)。  
   **Git and Python 3** (including the Windows Python launcher `py`; verified with 3.14).
2. **Inno Setup 6**:  
   **Inno Setup 6**:
   ```powershell
   winget install --id JRSoftware.InnoSetup
   ```
3. **ffmpeg**:  
   **ffmpeg**:
   ```powershell
   winget install --id Gyan.FFmpeg
   ```
4. **radioconda 2025.03.14 と、ビルド済みの gr-dvbs2rx**: `%USERPROFILE%\radioconda` に radioconda を導入し、
   [`docs/gr-dvbs2rx-windows/`](../docs/gr-dvbs2rx-windows/README.md) の手順で gr-dvbs2rx をビルド・導入しておく
   (Visual Studio Build Tools 2022 の C++ ワークロードが必要)。インストーラに同梱する gr-dvbs2rx は、
   ここに導入されたものを使う。  
   **radioconda 2025.03.14 and a built gr-dvbs2rx**: install radioconda into `%USERPROFILE%\radioconda`, then build and install
   gr-dvbs2rx following [`docs/gr-dvbs2rx-windows/`](../docs/gr-dvbs2rx-windows/README.md)
   (requires the Visual Studio Build Tools 2022 C++ workload). The installer bundles the gr-dvbs2rx installed there.

## ビルド / Build

リポジトリを clone した状態で、どのフォルダからでも実行できる:  
Run from any folder in a cloned repository:

```powershell
powershell -ExecutionPolicy Bypass -File build_installer\build_installer.ps1
```

成果物は `build_installer\output\ShonanLiteSetup.exe`。圧縮に数分〜10分程度かかる。
`-SkipInstaller` を付けると、`staging` の準備と PyInstaller までで止まる(Inno Setup は実行しない)。  
The result is `build_installer\output\ShonanLiteSetup.exe`. Compression takes a few to ten minutes.
With `-SkipInstaller` it stops after preparing `staging` and running PyInstaller (Inno Setup is not run).

スクリプトは次の順に実行する / The script does the following, in order:

1. `staging` を準備する(下記)。/ Prepares `staging` (below).
2. リポジトリ直下の `.venv-win` を(なければ作成して)使い、`requirements-win.txt` と
   `build_installer\requirements-build.txt`(PyInstaller)を導入し、`ShonanLite.spec` で GUI 本体を
   `build_installer\dist\ShonanLite\` にビルドする。  
   Uses (creating if needed) `.venv-win` in the repository root, installs `requirements-win.txt` and
   `build_installer\requirements-build.txt` (PyInstaller), and builds the GUI into `build_installer\dist\ShonanLite\` with `ShonanLite.spec`.
3. `ShonanLiteSetup.iss` を Inno Setup 6 でコンパイルする。  
   Compiles `ShonanLiteSetup.iss` with Inno Setup 6.

## staging の中身 / What goes into `staging`

`build_installer\staging\` は Git 管理外。スクリプトは、無いものだけを次のとおり用意する(既にあるものはそのまま使う)。  
`build_installer\staging\` is not tracked by Git. The script prepares only what is missing, as follows (existing files are kept).

| パス / Path | 内容 / Contents | 入手元 / Source |
| --- | --- | --- |
| `staging\ffmpeg\ffmpeg.exe` | ffmpeg 本体 / ffmpeg itself | PATH 上の `ffmpeg.exe`、または winget で導入したもの / `ffmpeg.exe` on the PATH, or the one installed by winget |
| `staging\radioconda\radioconda-installer.exe` | radioconda インストーラ / radioconda installer | [radioconda-installer](https://github.com/radioconda/radioconda-installer/releases/tag/2025.03.14) の `radioconda-2025.03.14-Windows-x86_64.exe` を自動ダウンロードし、SHA256 を検証 / downloaded automatically and its SHA256 verified |
| `staging\dvbs2rx_pyd\gnuradio\dvbs2rx\` | gr-dvbs2rx の Python 部分(`__init__.py` `defs.py` `params.py` `utils.py` `dvbs2rx_python.cp312-win_amd64.pyd`) / Python part of gr-dvbs2rx | `%USERPROFILE%\radioconda\Lib\site-packages\gnuradio\dvbs2rx\` |
| `staging\dvbs2rx_dll\gnuradio-dvbs2rx.dll` | gr-dvbs2rx の DLL / gr-dvbs2rx DLL | `%USERPROFILE%\radioconda\Library\bin\` |

同梱の gr-dvbs2rx は radioconda 2025.03.14(GNU Radio 3.10.12.0 / Python 3.12)向けにビルドしたもの。
バージョンが異なる radioconda で作ったものを同梱すると、インストール後に受信が動かない。
`conda update` などで fmt / spdlog が新しくなった radioconda でビルドした場合も同様で、受信開始時に
「DLL load failed ... 指定されたプロシージャが見つかりません」となる(v1.1.0で発生)。
そのため `build_installer.ps1` は、ビルド環境の radioconda が 2025.03.14 のままであること
(`gnuradio-core` 3.10.12.0 / `fmt` 11.0.2 / `spdlog` 1.15.1 / `libboost` 1.86.0 / `volk` 3.2.0 / `python` 3.12.9)と、
`import gnuradio.dvbs2rx` が成功することを確認し、外れていればビルドを中止する。
`staging\dvbs2rx_*` を作り直したいときは、そのフォルダを削除してから再実行する。  
The bundled gr-dvbs2rx must be built against radioconda 2025.03.14 (GNU Radio 3.10.12.0 / Python 3.12). One built against a different radioconda version will not work after installation.
The same happens when it is built in a radioconda whose fmt / spdlog were upgraded (e.g. by `conda update`): RX start fails with
"DLL load failed ... The specified procedure could not be found" (seen with v1.1.0).
`build_installer.ps1` therefore verifies that the build radioconda is still 2025.03.14 (`gnuradio-core` 3.10.12.0 / `fmt` 11.0.2 /
`spdlog` 1.15.1 / `libboost` 1.86.0 / `volk` 3.2.0 / `python` 3.12.9) and that `import gnuradio.dvbs2rx` succeeds, and aborts otherwise.
To rebuild `staging\dvbs2rx_*`, delete those folders and run the script again.

## バージョン番号 / Version number

`ShonanLiteSetup.iss` の `MyAppVersion` は、アプリ本体のバージョン(`app/gui/manual_content_win.py` の `MANUAL_VERSION`)と
揃える。  
Keep `MyAppVersion` in `ShonanLiteSetup.iss` in sync with the app version (`MANUAL_VERSION` in `app/gui/manual_content_win.py`).

## 使用許諾・免責事項 / License and disclaimer

インストーラは、インストール前に `license_and_disclaimer.txt`(使用許諾・免責事項)を表示して同意を求め、GPLv3 の全文(リポジトリ直下の `LICENSE`)を
インストール先に `LICENSE.txt` として置く。サイレントインストールでは同意画面は表示されない。
`license_and_disclaimer.txt` は **UTF-8(BOM付き)** で保存すること(BOM が無いと、Inno Setup が日本語を文字化けして表示する)。
文面は README.md の「免責事項」およびアプリ内マニュアルの「免責事項」の章と揃える。  
The installer shows `license_and_disclaimer.txt` (license and disclaimer) before installing and asks for acceptance, and places the full GPLv3 text
(`LICENSE` in the repository root) in the installation folder as `LICENSE.txt`. The acceptance page is not shown during a silent install.
Save `license_and_disclaimer.txt` as **UTF-8 with a BOM** (without a BOM, Inno Setup displays Japanese text garbled).
Keep the wording in step with the "Disclaimer" section of README.md and the "Disclaimer" chapter of the in-app manual.
