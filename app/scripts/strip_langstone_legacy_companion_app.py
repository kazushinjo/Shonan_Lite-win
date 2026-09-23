#!/usr/bin/env python3
"""update_langstone_from_upstream.sh の追加ステップ。

upstream(g4eml/Langstone-V3)のGUI_Pluto.cには、別の連携アプリ(以下
「レガシー連携アプリ」)向けの検出ロジック・終了ボタン分岐が残っている。
Shonan_Lite-pi5統合版ではこれを「GOTO SHONAN_LITE」ボタン(shonan-gui.service
をsystemctl startで直接起動)に置き換えている。

この置き換えは通常のunified diff(langstone_v3_shonan_lite.patch)では
表現していない。diffの削除行はupstream側の元テキストをそのまま含む必要が
あり、それを本パッチファイルに書くとレガシー連携アプリの製品名文字列が
このリポジトリに残ってしまうため。代わりに、製品名を一切使わず、
周辺の一意なコード(変数宣言の並び・関数名・ファイルパス文字列等)だけを
目印にして対象箇所を特定し、置き換える。

目印が見つからない場合(=upstream側でこの周辺が変更された)は、誤った
箇所を書き換えないよう、変換をスキップせずエラー終了する。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("LangstoneGUI_Pluto.c")


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    new_text, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        sys.exit(
            f"エラー: strip_langstone_legacy_companion_app.py の変換 '{label}' の"
            f"対象箇所が見つかりません({count}箇所ヒット、期待値1)。"
            f"upstream側の該当コードが変更された可能性があります。"
            f"手動でGUI_Pluto.cを確認し、本スクリプトを修正してください。"
        )
    return new_text


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    # 1) 検出用フラグ変数の宣言を削除
    #    (int mousePresent; int touchPresent; int plutoPresent; int hmiPresent;
    #     int <flag>Present; int V2Display =0 ; という並びの5行目を削除)
    text = replace_once(
        text,
        r"(int hmiPresent;\r?\n)int \w+Present;\r?\n(int V2Display =0 ;)",
        r"\1\2",
        "検出用フラグ変数宣言の削除",
    )

    # 2) ピン互換性コメントの一般化
    #    (「bandPin1 is copied to both of these pins to retain compatibility
    #     with <製品名>.」の製品名部分を一般的な表現に置き換え)
    text = replace_once(
        text,
        r"(retain compatibility with )\w+(\.)",
        r"\1an external companion GUI\2",
        "ピン互換性コメントの一般化",
    )

    # 3) 起動時の初期化(=0)を削除
    text = replace_once(
        text,
        r"(  hmiPresent=0;\r?\n)  \w+Present=0;\r?\n(  fp=fopen)",
        r"\1\2",
        "起動時フラグ初期化の削除",
    )

    # 4) レガシー連携アプリ検出ブロック全体を削除
    #    (固有のバイナリパス文字列を目印にする。この文字列自体はレガシー
    #    連携アプリの製品名ではない)
    text = replace_once(
        text,
        r"(  if\(ln\)  free\(ln\);\r?\n)"
        r"[ \t]*\r?\n"
        r"  if \(\(fp = openFile\(\"rpidatv/bin/rpidatvgui\", \"r\"\)\)\)[^\n]*\r?\n"
        r"  \{\r?\n"
        r"    fclose\(fp\);\r?\n"
        r"    \w+Present=1;\r?\n"
        r"  \}\r?\n"
        r"[ \t]*\r?\n"
        r"    plutoPresent=1;[ \t]*//this will be reset by setPlutoFreq if Pluto is not present\.[ \t]*\r?\n",
        r"\1\n    plutoPresent=1;      //this will be reset by setPlutoFreq if Pluto is not present.\n",
        "レガシー連携アプリ検出ブロックの削除",
    )

    # 5) ボタン6コメントの一般化
    #    (「Button 6 = BEACON or Exit to <製品名>」の製品名部分を一般化)
    text = replace_once(
        text,
        r"(funcButtonsX\+buttonSpaceX\*5,funcButtonsY\)\)    //Button 6 = BEACON  or Exit to )\w+",
        r"\1external GUI",
        "ボタン6コメントの一般化",
    )

    # 6) 「レガシー連携アプリへ終了」分岐ボタンをGOTO SHONAN_LITEボタンに置換
    text = replace_once(
        text,
        r"    if \(\w+Present==1\)\r?\n"
        r"    \{\r?\n"
        r'        displayButton2x12\("EXIT TO","\w+"\);\r?\n'
        r"    \}\r?\n"
        r"    else\r?\n"
        r"    \{\r?\n"
        r'        displayButton1x12\("EXIT"\);\r?\n'
        r"    \}\r?\n",
        "    // ★Shonan_Lite-pi5統合版パッチ: 「GOTO SHONAN_LITE」ボタン。押下時の\n"
        "    // 処理(ボタン6のハンドラ)はShonan_Lite-pi5のshonan-gui.serviceを\n"
        "    // systemctl startで直接起動する方式(boot_menu.pyと同じConflicts=に\n"
        "    // よる排他制御を利用、Pi5自体のrebootは不要)。\n"
        '    displayButton2x12("GOTO","SHONAN_LITE");\n',
        "終了ボタン分岐をGOTO SHONAN_LITEボタンへ置換",
    )

    TARGET.write_text(text, encoding="utf-8", newline="")
    print(f"OK: {TARGET} を変換しました(6件)。")


if __name__ == "__main__":
    main()
