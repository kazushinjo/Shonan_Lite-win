#!/usr/bin/env bash
# ローカルの作業フォルダー(このクローン自身)をRaspberry Pi 5へtar+ssh転送し、
# Pi5上でinstall_local.shを実行する。PC側(Windows Git Bash/Mac/Linux)から実行する。
# 追加ツール(sshpass/rsync)は使わず、標準のssh/scp/tarのみで動かす。そのため
# Pi5への接続は2回発生し(転送1回・インストール実行1回)、それぞれで標準の
# sshパスワードプロンプトが出て都度パスワードを入力することになる
# (自動化したい場合はPi5にSSH公開鍵を登録してパスワード認証自体を無くすこと)。
#
# 使い方:
#   ./app/scripts/deploy_to_pi5.sh
#     (IPアドレス・ユーザー名を対話的に入力する)
#   PI5_HOST=192.168.1.50 PI5_USER=pi ./app/scripts/deploy_to_pi5.sh
#     (IP/ユーザー名を環境変数で指定する場合。パスワードはssh自体が都度聞く)
#   SKIP_JA_KEYBOARD=1 SKIP_GNURADIO_BUILD=1 ./app/scripts/deploy_to_pi5.sh
#     (install_local.sh側のビルド省略オプションをそのまま転送先の実行にも反映する)
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
LOCAL_REPO_DIR="$(readlink -f "$SCRIPT_DIR/../..")"
REMOTE_SRC_DIR="shonan-pi5-src"

if [ -z "${PI5_HOST:-}" ]; then
  read -rp "Pi5のIPアドレス/ホスト名: " PI5_HOST
fi
: "${PI5_HOST:?IPアドレス/ホスト名が必要です}"

if [ -z "${PI5_USER:-}" ]; then
  read -rp "Pi5のユーザー名 [pi]: " PI5_USER
  PI5_USER="${PI5_USER:-pi}"
fi

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)

echo "=== ${PI5_USER}@${PI5_HOST}:~/${REMOTE_SRC_DIR} へソースを転送しています(1回目のパスワード入力) ==="
tar --exclude='.git' -C "$LOCAL_REPO_DIR" -cf - . \
  | ssh "${SSH_OPTS[@]}" "${PI5_USER}@${PI5_HOST}" \
      "mkdir -p ~/${REMOTE_SRC_DIR} && tar -C ~/${REMOTE_SRC_DIR} -xf -"

# ★install_local.sh側の省略オプションをローカルの環境変数から拾い、リモート
# 実行時のコマンド文字列に安全に埋め込む(値は%qでシェルクォートする)。
REMOTE_ENV=""
for var in SHONAN_INSTALL_DIR SKIP_JA_KEYBOARD SKIP_GNURADIO_BUILD SKIP_LANGSTONE_BUILD; do
  if [ -n "${!var:-}" ]; then
    REMOTE_ENV="${REMOTE_ENV}${var}=$(printf '%q' "${!var}") "
  fi
done

echo "=== Pi5上でinstall_local.shを実行しています(2回目のパスワード入力) ==="
ssh -t "${SSH_OPTS[@]}" "${PI5_USER}@${PI5_HOST}" \
  "cd ~/${REMOTE_SRC_DIR} && ${REMOTE_ENV}./app/scripts/install_local.sh"
