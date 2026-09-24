#!/usr/bin/env bash
# g4eml/Langstone-V3(app/third_party/Langstone-V3)を最新のupstreamへ
# 更新しつつ、Shonan_Lite-pi5向けの改造(app/docs/patches/langstone_v3_shonan_lite.patch)
# を必ず維持するためのスクリプト。
#
# upstreamのソースを直接app/third_party/Langstone-V3/へ上書きすると、
# ウォーターフォール拡張・「戻る」ボタン化・Pluto+ IP固定等の改造が
# 消えてしまう。本スクリプトは「まっさらなupstreamをclone → こちらの
# パッチを適用 → 成功した場合のみapp/third_party/Langstone-V3/を置き換え」
# という手順を踏むことで、upstream更新のたびに改造を失わずに済むようにする。
#
# パッチが当たらない(=upstream側でこちらの改造箇所付近が変更された)場合は
# 安全のため何もせずエラー終了する。その場合は手動で差分を確認し、
# app/third_party/Langstone-V3/の内容を直接更新したうえで
# app/docs/patches/langstone_v3_shonan_lite.patch を作り直すこと
# (作り直し方は本スクリプト末尾のコメント参照)。
#
# 使い方:
#   ./app/scripts/update_langstone_from_upstream.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET_DIR="$ROOT/app/third_party/Langstone-V3"
PATCH_FILE="$ROOT/app/docs/patches/langstone_v3_shonan_lite.patch"
LEGACY_COMPANION_APP_SCRIPT="$ROOT/app/scripts/strip_langstone_legacy_companion_app.py"
UPSTREAM_URL="https://github.com/g4eml/Langstone-V3.git"
WORK_DIR="${LANGSTONE_UPDATE_WORKDIR:-/tmp/langstone-v3-upstream-update}"

echo "=== 1/4 upstream(${UPSTREAM_URL})を取得 ==="
rm -rf "$WORK_DIR"
git clone --depth 1 "$UPSTREAM_URL" "$WORK_DIR"
rm -rf "$WORK_DIR/.git"

echo "=== 2/4 Shonan_Lite-pi5向けパッチを適用 ==="
if ! patch -p1 -d "$WORK_DIR" --dry-run < "$PATCH_FILE" > /dev/null 2>&1; then
  echo "エラー: パッチがupstreamの最新版に当たりませんでした。" >&2
  echo "upstream側でこちらの改造箇所付近(ウォーターフォール描画、run_pluto/stop_pluto等)" >&2
  echo "が変更された可能性があります。手動でマージしてください:" >&2
  echo "  1. ${WORK_DIR} の内容を確認し、必要な改造を手動で再適用する" >&2
  echo "  2. 完了したら以下でapp/third_party/Langstone-V3/とパッチを更新:" >&2
  echo "     rsync -a --delete ${WORK_DIR}/ ${TARGET_DIR}/" >&2
  echo "     (別途保存しておいた元のupstreamクローンと診断diffを取り、" >&2
  echo "      app/docs/patches/langstone_v3_shonan_lite.patchを作り直す)" >&2
  exit 1
fi
patch -p1 -d "$WORK_DIR" < "$PATCH_FILE"

echo "=== 3/4 レガシー連携アプリ向けコードの置き換え ==="
# ★upstreamのGUI_Pluto.cには、別の連携アプリ向けの検出ロジック・終了ボタン
# 分岐が残っている。この置き換えは通常のunified diffでは表現していない
# (diffの削除行にupstream側の元テキストをそのまま含める必要があり、
# それをlangstone_v3_shonan_lite.patchに書くとその製品名がこのリポジトリに
# 残ってしまうため)。代わりに、製品名を使わず周辺の一意なコードだけを
# 目印にする専用スクリプトで置き換える(詳細はスクリプト内コメント参照)。
python3 "$LEGACY_COMPANION_APP_SCRIPT" "$WORK_DIR/LangstoneGUI_Pluto.c"

echo "=== 4/4 app/third_party/Langstone-V3/を置き換え ==="
rsync -a --delete "$WORK_DIR/" "$TARGET_DIR/"
rm -rf "$WORK_DIR"

echo
echo "完了。git diffで変更内容を確認してからコミットしてください:"
echo "  cd ${ROOT} && git diff --stat app/third_party/Langstone-V3/"
echo
echo "実機での再ビルド・動作確認も忘れずに行うこと"
echo "(app/docs/install_script_guide.md「5/7 Langstone V3のビルド」参照)。"
