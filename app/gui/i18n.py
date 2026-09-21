"""表示言語(日本語/English)の切替ヘルパー。

現在の言語はモジュール変数で保持し、起動時(main.py)と設定画面での切替時に
set_language()で更新する。各画面はtr(ja, en)で文言を選ぶ。言語変更後は
main.rebuild_language()が画面を作り直すため、構築時にtr()を呼べば十分。
"""
from __future__ import annotations

JAPANESE = "JAPANESE"
ENGLISH = "ENGLISH"

_language = JAPANESE


def set_language(lang: str) -> None:
    global _language
    _language = ENGLISH if lang == ENGLISH else JAPANESE


def is_english() -> bool:
    return _language == ENGLISH


def tr(ja: str, en: str) -> str:
    """現在の表示言語に応じてjaまたはenを返す。"""
    return en if _language == ENGLISH else ja


def bilingual(text: str) -> str:
    """「日本語 / English」形式の見出しから、English表示時は英語側だけを返す。

    " / "を含まない文字列や日本語表示時はそのまま返す。"""
    if _language == ENGLISH and " / " in text:
        return text.split(" / ", 1)[1]
    return text
