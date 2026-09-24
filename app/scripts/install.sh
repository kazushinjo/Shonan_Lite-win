#!/usr/bin/env bash
# 新規Pi5(Raspberry Pi OS / Debian trixie系)にshonan-pi5一式をセットアップする。
# 単体で(curlで直接)実行しても、既にcloneした状態のrepo内から実行しても動くように、
# 未clone時はGitHubからcloneし、既にcloneされていればgit pullで最新化する。
#
# 実行内容:
#   0. 前提条件の確認(git未導入なら自動導入、SSH clone時はSSH鍵を確認・
#      未登録なら生成して案内。LOCAL_SOURCE_DIR指定時はGitHubへの
#      到達性が不要なためこの節ごと省略する)
#   1. ソース一式を取得(GitHubからclone/pull。LOCAL_SOURCE_DIR指定時は
#      ローカルクローンからrsyncでコピー)
#   2. 実行時依存パッケージ(PyQt5、ffmpeg、ALSA/V4L2ツール、日本語/DejaVuフォント等)
#   3. 日本語入力(OpenWnn)対応版Qt Virtual Keyboardをソースからビルド・差し替え
#      (apt版には日本語入力エンジンが同梱されていないため。docs/qtvirtualkeyboard_ja_build.md参照)
#   4. 受信(RX)に必要なGNU Radio + gr-dvbs2rxを導入(gr-dvbs2rxはapt未配布のためソースビルド)
#   5. Langstone V3(SDRトランシーバー、g4eml/Langstone-V3)をビルド。libiio API不一致を
#      避けるため専用のlibiioを/opt/langstone-libiioへ隔離導入する
#   6. 起動時コンソール表示の抑制(tty1のgetty無効化、カーネルquiet起動)
#   7. reboot/shutdown/起動アプリ切替のパスワード無し実行を許可(sudoers.d、TTY無しの
#      systemdサービスからのsudo reboot/shutdown/systemctl startがPAM認証で
#      失敗する不具合の対策)
#   8. 電源電圧警告(稲妻アイコン)表示の抑制(/boot/firmware/config.txtにavoid_warnings=1追記)
#   9. shonan-boot-menu.service / shonan-gui.service / langstone.service(systemd)を
#      作成・有効化。起動時はshonan-boot-menu.service(app/gui/boot_menu.py)が
#      全画面メニューを表示し、選んだ側のサービスをsystemctl startで直接起動する
#      (3サービスは互いにConflicts=で排他制御、マーカーファイル
#      ~/.pi5_boot_mode_langstoneの有無もConditionPathExistsで見る)
#
# 使い方:
#   ./app/scripts/install.sh            # 開発中の現行ブランチをclone
#   ./app/scripts/install_ssh.sh        # SSHでclone(private repoのため通常こちらを使う)
#   ./app/scripts/install_local.sh      # 既にあるローカルクローンから展開(GitHub到達性不要)
#   REPO_BRANCH=main ./app/scripts/install.sh # mainを指定する場合
#   SKIP_JA_KEYBOARD=1 ./app/scripts/install.sh     # 日本語入力ビルドを省略(時間短縮)
#   SKIP_GNURADIO_BUILD=1 ./app/scripts/install.sh  # RX用GNU Radio/gr-dvbs2rxビルドを省略
#   SKIP_LANGSTONE_BUILD=1 ./app/scripts/install.sh # Langstone V3ビルドを省略
#
# 前提条件(詳細はdocs/install_script_guide.md「実行条件(前提条件)」参照):
#   - Raspberry Pi OS 64bit(aarch64)。32bit(armhf)では動作しない
#   - GitHub / apt配布ミラーへのインターネット到達性(LOCAL_SOURCE_DIR指定時、
#     ソース取得自体はGitHub到達性不要。ただし2/9以降のapt/ビルドには変わらず必要)
#   - sudoが使える対話的な実行(パスワード入力に応答できるtty)
#   - patchコマンドが使えること(3/9のダークテーマパッチ、4/9の受信安定化パッチ適用に使用)
#   - git、GitHub SSH鍵は無くても0/9が自動導入・案内する(gitは自動インストール、
#     SSH鍵は生成した上で一度スクリプトを終了するので、鍵をGitHubに登録してから
#     再実行する。LOCAL_SOURCE_DIR指定時はこの節自体を省略する)
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/kazushinjo/Shonan_Lite-RasPI5.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="${SHONAN_INSTALL_DIR:-$HOME/shonan-pi5}"
QTVK_BUILD_DIR="${QTVK_BUILD_DIR:-/tmp/qtvirtualkeyboard-src}"
GR_DVBS2RX_BUILD_DIR="${GR_DVBS2RX_BUILD_DIR:-$HOME/gr-dvbs2rx}"
SERVICE_NAME="shonan-gui.service"

log() { echo -e "\n=== $* ===\n"; }

log "0/9 前提条件の確認"
if [ -n "${LOCAL_SOURCE_DIR:-}" ]; then
  echo "LOCAL_SOURCE_DIR=${LOCAL_SOURCE_DIR}が指定されているため、GitHub到達性・SSH鍵の確認は省略します。"
  if ! command -v rsync >/dev/null 2>&1; then
    echo "rsyncが見つからないため導入します。"
    sudo apt-get update
    sudo apt-get install -y rsync
  fi
elif ! command -v git >/dev/null 2>&1; then
  # ★まっさらなRaspberry Pi OSにはgitが入っていない(2026-08-20 新規OS実機で確認)。
  # 1/9のソース取得自体がgitに依存するため、無ければここで導入する。
  echo "gitが見つからないため導入します。"
  sudo apt-get update
  sudo apt-get install -y git
fi

# ★本リポジトリはprivateのため、HTTPS(REPO_URL既定値)ではpush/pull時に必ず
# 認証を要求され、非対話環境(sshpass経由等)では"could not read Username"で
# 即座に失敗する。install_ssh.sh(REPO_URL=git@github.com:...)を使う運用が
# 前提だが、実機に一度もSSH鍵を登録していない新規OSでは同様に失敗する。
# SSH URLの場合のみ、鍵が無ければ生成し、GitHub側に未登録なら案内して
# 一旦終了する(公開鍵の登録はブラウザ操作が必要なため自動化できない)。
# ★LOCAL_SOURCE_DIR指定時(install_local.sh)はGitHubへ一切アクセスしないため、
# この節ごと丸ごとスキップする。
if [ -n "${LOCAL_SOURCE_DIR:-}" ]; then
  :
elif [[ "$REPO_URL" == git@* ]]; then
  SSH_KEY="${HOME}/.ssh/id_ed25519"
  if [ ! -f "$SSH_KEY" ]; then
    echo "GitHub用のSSH鍵が見つからないため新規作成します。"
    ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -C "$(whoami)@$(hostname)-$(date +%Y%m%d)"
  fi
  # ★GitHubはshellアクセスを許可しないため、認証に成功していてもssh自体は
  # 必ずexit 1で終了する仕様(メッセージは"successfully authenticated"だが
  # 終了コードは非ゼロ)。set -o pipefail下でパイプへ直接繋ぐと、grepが
  # マッチ(成功)してもパイプライン全体が失敗扱いになり、SSH鍵を登録済みでも
  # 「認証できません」と誤判定してしまう不具合があった(実機で確認)。
  # sshの終了コードを||trueで握りつぶし、出力だけを変数で受けてから判定する。
  ssh_auth_output=$(ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
    -T git@github.com 2>&1 || true)
  if ! grep -q "successfully authenticated" <<<"$ssh_auth_output"; then
    cat <<MSG

GitHubへのSSH認証ができません。以下の公開鍵をGitHubアカウントに登録してから、
このスクリプトを再度実行してください。

  登録先: https://github.com/settings/ssh/new (Key type: Authentication Key)

$(cat "${SSH_KEY}.pub")

MSG
    exit 1
  fi
else
  # ★REPO_URLがHTTPS(install.sh既定)の場合。本リポジトリはprivateのため、
  # 認証情報の無いHTTPSでは"git clone"が"could not read Username"という
  # 分かりにくいエラーで落ちる。事前にls-remoteでアクセス可否を確認し、
  # 失敗するならSSH版(install_ssh.sh)への切替を案内して終了する
  # (SSH鍵が既にあれば認証だけ確認、無ければその場で生成して案内する)。
  if ! timeout 15 git ls-remote "$REPO_URL" >/dev/null 2>&1; then
    SSH_KEY="${HOME}/.ssh/id_ed25519"
    if [ ! -f "$SSH_KEY" ]; then
      echo "GitHub用のSSH鍵が見つからないため新規作成します。"
      ssh-keygen -t ed25519 -N "" -f "$SSH_KEY" -C "$(whoami)@$(hostname)-$(date +%Y%m%d)"
    fi
    ssh_auth_output=$(ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes \
      -T git@github.com 2>&1 || true)
    if grep -q "successfully authenticated" <<<"$ssh_auth_output"; then
      cat <<MSG

このリポジトリはprivateのため、HTTPS(既定)では認証できません。
SSH鍵は登録済みです。代わりに以下を実行してください。

  ./app/scripts/install_ssh.sh

MSG
    else
      cat <<MSG

このリポジトリはprivateのため、HTTPS(既定)では認証できません。
以下の公開鍵をGitHubアカウントに登録してから、./app/scripts/install_ssh.sh
を実行してください。

  登録先: https://github.com/settings/ssh/new (Key type: Authentication Key)

$(cat "${SSH_KEY}.pub")

MSG
    fi
    exit 1
  fi
fi

if [ -n "${LOCAL_SOURCE_DIR:-}" ]; then
  log "1/9 ソース取得 (ローカルクローン: ${LOCAL_SOURCE_DIR})"
  if [ ! -d "$LOCAL_SOURCE_DIR/app" ]; then
    echo "LOCAL_SOURCE_DIRが不正です(app/が見つかりません): $LOCAL_SOURCE_DIR" >&2
    exit 1
  fi
  # ★scp/USB等で転送済みのローカルクローンをそのままrsyncでコピーする
  # (.gitは転送に含まれないことがあるため除外。install.sh自体は配備用の
  # ため、既存INSTALL_DIRとの差分もLOCAL_SOURCE_DIRの内容で正とする)。
  mkdir -p "$INSTALL_DIR"
  rsync -a --delete --exclude='.git' "$LOCAL_SOURCE_DIR"/ "$INSTALL_DIR"/
else
  log "1/9 ソース取得 (${REPO_URL}, branch=${REPO_BRANCH})"
  if [ -d "$INSTALL_DIR/.git" ]; then
    # 直接scpで更新されたPi側の作業ツリーも、指定ブランチの内容へ正確に戻す。
    # install.shは配備用スクリプトのため、ローカル変更を残さずリモートを正とする。
    git -C "$INSTALL_DIR" fetch origin "$REPO_BRANCH"
    git -C "$INSTALL_DIR" checkout -B "$REPO_BRANCH" "origin/$REPO_BRANCH"
    git -C "$INSTALL_DIR" reset --hard "origin/$REPO_BRANCH"
  else
    git clone --branch "$REPO_BRANCH" --single-branch "$REPO_URL" "$INSTALL_DIR"
  fi
fi
GUI_DIR="$INSTALL_DIR/app/gui"

log "2/9 実行時依存パッケージ"
sudo apt-get update
sudo apt-get install -y \
  git curl \
  python3-pyqt5 python3-pyqt5.qtquick python3-pyqt5.sip python3-pil \
  ffmpeg v4l-utils alsa-utils libiio-utils sshpass \
  fonts-droid-fallback fonts-dejavu-core \
  qtvirtualkeyboard-plugin qml-module-qtquick-virtualkeyboard \
  qml-module-qt-labs-folderlistmodel qml-module-qtquick-window2 \
  qml-module-qtquick-layouts qml-module-qtquick-controls2 qml-module-qtquick2

# カメラ・マイク・Pluto用デバイスへ、ログインユーザーからアクセスできるようにする。
sudo usermod -aG video,audio "$USER" 2>/dev/null || true

if [ "${SKIP_JA_KEYBOARD:-0}" = "1" ]; then
  echo "SKIP_JA_KEYBOARD=1のため日本語入力ビルドを省略します(英語配列のみ利用可)。"
else
  log "3/9 日本語入力(OpenWnn)対応版Qt Virtual Keyboardをビルド"
  sudo apt-get install -y \
    qtbase5-dev qtbase5-private-dev qtdeclarative5-dev qtdeclarative5-private-dev \
    qtquickcontrols2-5-dev qt5-qmake build-essential libqt5svg5-dev

  QT_VERSION="$(qmake -query QT_VERSION)"
  QT_TAG="v${QT_VERSION}-lts-lgpl"
  echo "Qtバージョン: ${QT_VERSION} (タグ ${QT_TAG} を使用)"

  rm -rf "$QTVK_BUILD_DIR"
  git clone --depth 1 --branch "$QT_TAG" \
    https://github.com/qt/qtvirtualkeyboard.git "$QTVK_BUILD_DIR"

  # ★言語切替ポップアップ(globeアイコン)の既定配色(白背景+緑文字)はこのアプリの
  # 全体ダークテーマと合わないため、ダーク背景+白文字に変更するパッチを当てる
  # (qtvirtualkeyboard_ja_build.mdの「言語切替ポップアップと単語予測ポップアップは
  # 別スタイルプロパティ」参照)。
  STYLE_PATCH="$INSTALL_DIR/app/docs/patches/qtvirtualkeyboard_style_dark_language_popup.patch"
  if [ -f "$STYLE_PATCH" ]; then
    patch -p1 -d "$QTVK_BUILD_DIR" < "$STYLE_PATCH"
  fi

  (
    cd "$QTVK_BUILD_DIR"
    qmake CONFIG+=openwnn CONFIG+=lang-ja_JP CONFIG+=lang-en_GB CONFIG+=lang-en_US \
      qtvirtualkeyboard.pro
    make -j"$(nproc)"
  )

  # apt版ファイルをバックアップしてから自前ビルドで差し替える。
  QT5_LIB_DIR="/usr/lib/aarch64-linux-gnu"
  QT5_QML_DIR="$QT5_LIB_DIR/qt5/qml/QtQuick/VirtualKeyboard"
  QT5_PLUGIN_DIR="$QT5_LIB_DIR/qt5/plugins"
  BACKUP_DIR="$HOME/qtvk_backup_$(date +%Y%m%d%H%M%S)"
  mkdir -p "$BACKUP_DIR"
  sudo cp -a "$QT5_LIB_DIR"/libQt5VirtualKeyboard.so* "$BACKUP_DIR/" 2>/dev/null || true
  sudo cp -a "$QT5_QML_DIR" "$BACKUP_DIR/VirtualKeyboard_qml" 2>/dev/null || true
  sudo cp -a "$QT5_PLUGIN_DIR/platforminputcontexts/libqtvirtualkeyboardplugin.so" \
    "$BACKUP_DIR/" 2>/dev/null || true
  mkdir -p "$BACKUP_DIR/virtualkeyboard_plugins"
  sudo cp -a "$QT5_PLUGIN_DIR/virtualkeyboard/." \
    "$BACKUP_DIR/virtualkeyboard_plugins/" 2>/dev/null || true
  echo "旧ファイルのバックアップ先: $BACKUP_DIR"

  sudo cp -a "$QTVK_BUILD_DIR/lib/libQt5VirtualKeyboard.so.${QT_VERSION}" "$QT5_LIB_DIR/"
  sudo cp -a "$QTVK_BUILD_DIR/qml/QtQuick/VirtualKeyboard/libqtquickvirtualkeyboardplugin.so" \
    "$QT5_QML_DIR/"
  sudo cp -a "$QTVK_BUILD_DIR/qml/QtQuick/VirtualKeyboard/plugins.qmltypes" "$QT5_QML_DIR/"
  sudo cp -a "$QTVK_BUILD_DIR/qml/QtQuick/VirtualKeyboard/Settings/libqtquickvirtualkeyboardsettingsplugin.so" \
    "$QT5_QML_DIR/Settings/"
  sudo cp -a "$QTVK_BUILD_DIR/qml/QtQuick/VirtualKeyboard/Styles/libqtquickvirtualkeyboardstylesplugin.so" \
    "$QT5_QML_DIR/Styles/"
  sudo cp -a "$QTVK_BUILD_DIR/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so" \
    "$QT5_PLUGIN_DIR/platforminputcontexts/"
  sudo mkdir -p "$QT5_PLUGIN_DIR/virtualkeyboard"
  sudo cp -a "$QTVK_BUILD_DIR/plugins/virtualkeyboard/libqtvirtualkeyboard_openwnn.so" \
    "$QT5_PLUGIN_DIR/virtualkeyboard/"
  sudo ldconfig
fi

if [ "${SKIP_GNURADIO_BUILD:-0}" = "1" ]; then
  echo "SKIP_GNURADIO_BUILD=1のため受信(RX)用GNU Radio/gr-dvbs2rxのビルドを省略します(受信機能は動作しません)。"
else
  log "4/9 受信(RX)用GNU Radio + gr-dvbs2rxを導入"
  # ★gnuradio本体(gr-iio機能も含む。Debianではlibgnuradio-iio*として同梱)はaptで入るが、
  # gr-dvbs2rx(DVB-S2復調のOOT module、igorauad/gr-dvbs2rx)はapt未配布のため、
  # ソースを取得しビルド・インストールする(app/rx/shonan_rx.pyが`from gnuradio import
  # dvbs2rx`で必要とする)。
  sudo apt-get install -y gnuradio gnuradio-dev cmake pkg-config

  if [ -d "$GR_DVBS2RX_BUILD_DIR/.git" ]; then
    git -C "$GR_DVBS2RX_BUILD_DIR" pull --ff-only
  else
    git clone https://github.com/igorauad/gr-dvbs2rx.git "$GR_DVBS2RX_BUILD_DIR"
  fi
  git -C "$GR_DVBS2RX_BUILD_DIR" submodule update --init --recursive

  # ★実機での受信安定化のためにpl_frame_sync/symbol_sync_cc等へ加えた修正パッチ。
  # 既に適用済み(2回目以降の実行等)の場合はgit apply --checkが失敗するのでスキップする。
  RX_PATCH="$INSTALL_DIR/app/docs/patches/gr-dvbs2rx_pi5_bringup.patch"
  if [ -f "$RX_PATCH" ]; then
    if git -C "$GR_DVBS2RX_BUILD_DIR" apply --check "$RX_PATCH" 2>/dev/null; then
      git -C "$GR_DVBS2RX_BUILD_DIR" apply "$RX_PATCH"
    else
      echo "gr-dvbs2rx_pi5_bringup.patchは適用済みか対象外のためスキップします。"
    fi
  fi

  (
    mkdir -p "$GR_DVBS2RX_BUILD_DIR/build"
    cd "$GR_DVBS2RX_BUILD_DIR/build"
    cmake .. -DCMAKE_BUILD_TYPE=Release
    make -j"$(nproc)"
    sudo make install
  )
  sudo ldconfig
fi

if [ "${SKIP_LANGSTONE_BUILD:-0}" = "1" ]; then
  echo "SKIP_LANGSTONE_BUILD=1のためLangstone V3のビルドを省略します(Home画面のLangstone V3ボタンは動作しません)。"
else
  log "5/9 Langstone V3(SDRトランシーバー)のビルド"
  # ★Langstone V3(app/third_party/Langstone-V3、g4eml/Langstone-V3より取り込み)は
  # 新しめのlibiio API(iio_attr_*、iio_create_context等)を要求するが、
  # apt版libiio0(gr-iio/gnuradioが依存)は旧APIのため、同じ/usr配下に混在させると
  # 互いのヘッダ/共有ライブラリを上書きして双方が壊れる(実機で確認済みの事故)。
  # そのためLangstone専用のlibiioを/opt/langstone-libiioへ隔離ビルドし、
  # コンパイル時に-I/-L/RPATHで明示的にそちらだけを参照させる。
  # ★libfreetype-devは大きな周波数表示をアンチエイリアス済みTTF(DejaVu Serif
  # Bold)で描画するために使用(displayFreqTTF、LangstoneGUI_Pluto.c参照)。
  sudo apt-get install -y \
    libusb-1.0-0-dev libavahi-client-dev libxml2-dev bison flex libaio-dev \
    libzstd-dev liblgpio-dev libfreetype-dev

  LANGSTONE_LIBIIO_PREFIX="${LANGSTONE_LIBIIO_PREFIX:-/opt/langstone-libiio}"
  LANGSTONE_LIBIIO_SRC_DIR="${LANGSTONE_LIBIIO_SRC_DIR:-/tmp/langstone-libiio-src}"
  rm -rf "$LANGSTONE_LIBIIO_SRC_DIR"
  git clone --depth 1 https://github.com/analogdevicesinc/libiio.git "$LANGSTONE_LIBIIO_SRC_DIR"
  (
    cd "$LANGSTONE_LIBIIO_SRC_DIR"
    cmake . -DCMAKE_INSTALL_PREFIX="$LANGSTONE_LIBIIO_PREFIX"
    make -j"$(nproc)"
    sudo make install
  )

  LANGSTONE_DIR="${LANGSTONE_INSTALL_DIR:-$HOME/Langstone}"
  mkdir -p "$LANGSTONE_DIR"
  cp -a "$INSTALL_DIR"/app/third_party/Langstone-V3/. "$LANGSTONE_DIR/"
  chmod +x "$LANGSTONE_DIR"/run "$LANGSTONE_DIR"/run_pluto "$LANGSTONE_DIR"/stop \
    "$LANGSTONE_DIR"/stop_pluto "$LANGSTONE_DIR"/set_pluto "$LANGSTONE_DIR"/set_sound \
    "$LANGSTONE_DIR"/update 2>/dev/null || true
  (
    cd "$LANGSTONE_DIR"
    cc LangstoneGUI_Pluto.c -o GUI_Pluto \
      -I"$LANGSTONE_LIBIIO_PREFIX/include" $(pkg-config --cflags freetype2) \
      -L"$LANGSTONE_LIBIIO_PREFIX/lib" \
      -Wl,-rpath,"$LANGSTONE_LIBIIO_PREFIX/lib" -liio -llgpio -lm $(pkg-config --libs freetype2)
    cc Screen_Message.c -o Screen_Message \
      $(pkg-config --cflags freetype2) $(pkg-config --libs freetype2) -lm
  )
  echo "Langstone V3をビルドしました: ${LANGSTONE_DIR}/GUI_Pluto"
fi

log "6/9 起動時コンソール表示の抑制"
# ★Pi5の初回起動時や、Home画面の「システム再起動」等でPi5自体がrebootする
# 際、素のRaspberry Pi OSのまま(getty@tty1が有効)だとカーネル起動ログや
# ログインプロンプト/シェルのコンソール出力が実機LCDに一瞬映り込み、
# Langstone/Shonan_Lite本来の画面と無関係な文字が見えてしまう(実機で確認)。
# (★Home画面の「Langstone V3」ボタン/Langstone側の「戻る」ボタンによる
# アプリ切替自体は、shonan-gui.service/langstone.service/
# shonan-boot-menu.serviceがsystemdのConflicts=で互いに排他制御されるため
# Pi5自体はrebootしない。9/9参照)。tty1のgettyを無効化し、カーネルの
# 起動メッセージも抑制する。
sudo systemctl disable --now getty@tty1.service 2>/dev/null || true
CMDLINE_FILE="/boot/firmware/cmdline.txt"
if [ -f "$CMDLINE_FILE" ] && ! grep -q 'quiet' "$CMDLINE_FILE"; then
  sudo sed -i '1s/$/ quiet loglevel=3 logo.nologo vt.global_cursor_default=0/' "$CMDLINE_FILE"
  echo "${CMDLINE_FILE}へquiet起動オプションを追記しました(反映には再起動が必要です)。"
else
  echo "${CMDLINE_FILE}は見つからないか、既にquiet設定済みのためスキップします。"
fi

log "7/9 reboot/shutdown/起動アプリ切替のパスワード無し実行を許可"
# ★Home画面の「Langstone V3」ボタン(shonan-gui.service)、Langstone側の
# 「戻る」ボタン(langstone.service)はいずれもTTYの無いsystemdサービスから
# sudo reboot/sudo shutdownを実行する。標準のsudo設定はパスワード入力を
# 要求するため、PAM会話が成立せず(pam_unix: conversation failed)rebootが
# 実行されないまま処理が先へ進んでしまう不具合を実機で確認した。pi
# ユーザーがreboot/shutdownをNOPASSWDで実行できるよう許可する。
# ★起動時アプリ選択(shonan-boot-menu.service、boot_menu.py)は選択直後に
# 該当サービスをsystemctl startするため、そのコマンドも合わせて許可する。
SUDOERS_FILE="/etc/sudoers.d/shonan-pi5-reboot"
echo "$(whoami) ALL=(root) NOPASSWD: /sbin/reboot, /sbin/shutdown, /usr/sbin/poweroff, /bin/systemctl start --no-block shonan-gui.service, /bin/systemctl start --no-block langstone.service, /bin/systemctl stop shonan-display-off.service" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 440 "$SUDOERS_FILE"
sudo visudo -c
echo "${SUDOERS_FILE}を更新しました。"

log "8/9 電源電圧警告(稲妻アイコン)表示の抑制"
# ★正規の27W USB-C PD電源でも配線・ケーブル品質等でわずかな電圧降下により
# 稲妻アイコン/ログ警告が出ることがある。avoid_warnings=1は表示を抑制するのみで
# 実際のアンダーボルト自体は解消しないため、恒久対策としては正規電源・良質な
# USBケーブルの使用が前提(vcgencmd get_throttledで実際のスロットリング有無を確認可能)。
BOOT_CONFIG="/boot/firmware/config.txt"
if [ -f "$BOOT_CONFIG" ] && ! grep -q '^avoid_warnings=' "$BOOT_CONFIG"; then
  echo "avoid_warnings=1" | sudo tee -a "$BOOT_CONFIG" > /dev/null
  echo "${BOOT_CONFIG}にavoid_warnings=1を追記しました(反映には再起動が必要です)。"
else
  echo "${BOOT_CONFIG}は見つからないか、既にavoid_warnings設定済みのためスキップします。"
fi

log "9/9 systemdサービス登録"
# ★Langstone V3とshonan-gui.serviceは同じ画面(/dev/fb0とeglfs/DRM)を排他的に
# 使うため同時起動できない。Home画面の「Langstone V3」ボタン、およびLangstone側の
# 「戻る」ボタンは、マーカーファイル(~/.pi5_boot_mode_langstone)を作成/削除して
# rebootする(app/gui/screens/home.py、LangstoneGUI_Pluto.c参照)。両サービスとも
# ConditionPathExistsでマーカーの有無を見て、起動すべきでない側は何もせず正常終了
# (skipped)扱いになるようにする。
LANGSTONE_BOOT_MARKER="${HOME}/.pi5_boot_mode_langstone"

SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}"
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Shonan Pi5 Touch GUI
After=multi-user.target shonan-boot-menu.service
Conflicts=shonan-boot-menu.service langstone.service
ConditionPathExists=!${LANGSTONE_BOOT_MARKER}

[Service]
Type=simple
User=${USER}
WorkingDirectory=${GUI_DIR}
Environment=QT_QPA_PLATFORM=eglfs
ExecStart=/usr/bin/python3 ${GUI_DIR}/main.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

if [ "${SKIP_LANGSTONE_BUILD:-0}" != "1" ]; then
  LANGSTONE_SERVICE_FILE="/etc/systemd/system/langstone.service"
  sudo tee "$LANGSTONE_SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Langstone V3 SDR Transceiver
After=multi-user.target shonan-boot-menu.service
Conflicts=shonan-boot-menu.service ${SERVICE_NAME}
ConditionPathExists=${LANGSTONE_BOOT_MARKER}

[Service]
Type=simple
User=${USER}
# ★systemdはUser=だけでは\$HOMEを自動設定しない。run_pluto/GUI_Pluto.c側が
# \$HOME経由でLangstone本体・マーカーファイルのパスを組み立てているため、
# 未設定のままだと全て失敗する(「戻る」を押してもShonan_Liteへ戻らない、
# GNU Radioフローグラフが起動しない等、実機で確認済み)。
# ★systemdの%hスペシファイアは、環境によってはUser=piではなくmanager実行者
# (root)のホームに解決されてしまい"/root/Langstone/..."を参照して
# Permission deniedになる不具合を実機で確認したため、install.sh実行時の
# 実際の値をそのまま埋め込む(スペシファイアに頼らない)。
Environment=HOME=${HOME}
WorkingDirectory=${LANGSTONE_DIR:-$HOME/Langstone}
ExecStart=/bin/bash ${LANGSTONE_DIR:-$HOME/Langstone}/run_pluto
Restart=no
# ★run_pluto先頭行が(元々のupstreamソースのまま)"#"のみのコメント行で、
# 続く2行目が"#!/bin/bash"になっている。カーネルのシェバング認識は先頭行のみを
# 見るため、systemdが直接execすると"Exec format error"になる(実機で確認)。
# /bin/bash経由で明示的に起動することで回避する。

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl disable langstone.service 2>/dev/null || true
fi

# ★起動のたびに「Shonan_Lite / Langstone V3」を選ぶ全画面メニュー
# (app/gui/boot_menu.py)。選んだ側のサービスをsystemctl startで直接起動する
# (ConditionPathExistsのマーカーファイルも合わせて操作するため、上記の
# shonan-gui.service/langstone.service定義とも整合する)。
BOOT_MENU_SERVICE_FILE="/etc/systemd/system/shonan-boot-menu.service"
sudo tee "$BOOT_MENU_SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Shonan/Langstone Boot Menu
After=multi-user.target

[Service]
Type=simple
User=${USER}
WorkingDirectory=${GUI_DIR}
Environment=QT_QPA_PLATFORM=eglfs
ExecStartPre=+/bin/sh -c 'if [ -e /sys/class/graphics/fb0/blank ]; then echo 0 > /sys/class/graphics/fb0/blank; fi'
ExecStart=/usr/bin/python3 ${GUI_DIR}/boot_menu.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo install -m 644 \
  "$INSTALL_DIR/app/systemd/shonan-display-off.service" \
  /etc/systemd/system/shonan-display-off.service

sudo systemctl daemon-reload
sudo systemctl disable "$SERVICE_NAME" 2>/dev/null || true
# ★disableは次回起動時の自動起動を止めるだけで、既に実行中のshonan-gui.service/
# langstone.serviceは止まらない。DRM/KMSデバイスはプロセスを1つしか掴めないため、
# 稼働中のままshonan-boot-menu.serviceを起動すると"Permission denied"で描画に
# 失敗する(実機で確認)。明示的にstopしてから切り替える。
sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
sudo systemctl stop langstone.service 2>/dev/null || true
sudo systemctl enable shonan-boot-menu.service
sudo systemctl enable shonan-display-off.service
sudo systemctl restart shonan-display-off.service
sudo systemctl restart shonan-boot-menu.service

log "インストール内容の検証"
REQUIRED_FILES=(
  "$GUI_DIR/main.py"
  "$GUI_DIR/backend.py"
  "$GUI_DIR/boot_menu.py"
  "$GUI_DIR/screens/videosource.py"
  "$GUI_DIR/screens/rssi.py"
  "$GUI_DIR/qml/InputPanelWrapper.qml"
  "$INSTALL_DIR/app/assets/test_pattern_ipad.png"
)
for required_file in "${REQUIRED_FILES[@]}"; do
  if [ ! -f "$required_file" ]; then
    echo "必須ファイルがありません: $required_file" >&2
    exit 1
  fi
done

for required_command in ffmpeg v4l2-ctl arecord iio_attr sshpass; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "必須コマンドがありません: $required_command" >&2
    exit 1
  fi
done

python3 -c 'from PyQt5 import QtCore, QtQuickWidgets, QtWidgets'
python3 -m compileall -q "$GUI_DIR"
if ! systemctl is-active --quiet shonan-boot-menu.service; then
  echo "shonan-boot-menu.serviceが起動していません" >&2
  sudo systemctl status shonan-boot-menu.service --no-pager || true
  exit 1
fi
echo "ソース・依存パッケージ・GUI構文・systemdサービスを確認しました。"

log "完了"
sudo systemctl status shonan-boot-menu.service --no-pager || true
cat <<'NOTE'

注意:
- 「Pluto再起動」ボタン、「システム日時」設定、実機LCDスクリーンショット取得等の機能は
  sshおよびsudoをパスワードなしで実行できる権限が前提です。必要に応じて
  /etc/sudoers.d/ にNOPASSWDルールを追加してください(このスクリプトでは変更しません)。
- 日本語入力は既定では英語配列で開始します。オンスクリーンキーボード左下のglobeアイコンで
  日本語(ローマ字入力)へ切り替えられます。
- /boot/firmware/config.txtへavoid_warnings=1を新規追記した場合、反映には再起動が必要です
  (sudo reboot)。稲妻アイコン表示は抑制されますが、実際の電圧不足自体は解消されないため、
  正規の27W USB-C PD電源・良質なUSBケーブルの使用を推奨します
  (vcgencmd get_throttledで実際のスロットリング有無を確認できます)。
NOTE
