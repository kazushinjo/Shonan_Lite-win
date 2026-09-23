#!/usr/bin/env bash
# install.shのローカルクローン版。scp/USB等で転送済みのローカルクローンから
# 展開する(GitHubへのネットワーク到達性・認証は一切不要。ソース取得を
# git clone/pullではなくrsyncでのローカルコピーに切り替える以外はinstall.shと
# 完全に同じ)。
#
# 使い方:
#   ./app/scripts/install_local.sh
#     (本スクリプトが置かれているクローン自身をソースとして使う)
#   LOCAL_SOURCE_DIR=/path/to/clone ./app/scripts/install_local.sh
#     (別の場所にあるローカルクローンをソースにする場合)
set -euo pipefail

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
export LOCAL_SOURCE_DIR="${LOCAL_SOURCE_DIR:-$(readlink -f "$SCRIPT_DIR/../..")}"
exec "$SCRIPT_DIR/install.sh" "$@"
