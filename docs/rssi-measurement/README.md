# RSSI測定の変更仕様 / RSSI Measurement change specification

Shonan_Lite for Windows v1.1.0 で行ったRSSI測定画面の変更を、他の版(Pi 5 版、Android 版、iPad 版など)へ
同じ仕様で移植できるよう記録したもの。  
A record of the changes made to the RSSI Measurement screen in Shonan_Lite for Windows v1.1.0, so the same specification can be
ported to the other editions (Pi 5, Android, iPad, ...).

- 実装 / Implementation: [`app/gui/screens/rssi.py`](../../app/gui/screens/rssi.py)、[`app/gui/settings_store.py`](../../app/gui/settings_store.py)
- 差分 / Patch: [`rssi-changes.patch`](rssi-changes.patch)(下記の 4 コミット分 / the 4 commits below)
- 検証状況 / Verification: 偽の `iio_attr` を使ったテストのみ。**実機の Pluto では未検証。**  
  Tested only with a fake `iio_attr`. **Not yet verified on a real Pluto.**

| コミット / Commit | 内容 / Change |
| --- | --- |
| `3590842` | 「新中心周波数」ボタンを削除 / Removed the "Set as Center" button |
| `2cb06c7` | 「検索停止」まで繰り返す / Repeat until "Stop Search" |
| `a187367` | RXゲイン(AGC/手動)を検索画面に追加 / RX gain (AGC / manual) on the search screen |
| `7e7b885` | 検索方法「連続 / 1回」を追加 / Search mode "Repeat / Once" |

## 1. 変更の概要 / Summary

変更前 / Before: 検索開始→開始周波数から終了周波数まで1回スキャン→自動停止。結果表示の横に「新中心周波数」ボタンがあり、
押すと最も強かった周波数を運用周波数に設定した。RXゲインは変更できなかった。  
Start → scan once from the start to the end frequency → stop automatically. A "Set as Center" button next to the result set the
strongest frequency as the operating frequency. RX gain could not be changed.

変更後 / After:

1. **「新中心周波数」ボタンを廃止。** 「最も強い周波数」は表示のみ。  
   **Removed the "Set as Center" button.** The "Strongest frequency" is display-only.
2. **検索方法「連続 / 1回」を選べる(既定は連続)。** 連続=「検索停止」まで繰り返す。1回=範囲の終わりで自動停止。  
   **Search mode "Repeat / Once" (default Repeat).** Repeat = until "Stop Search"; Once = stop at the end of the range.
3. **検索画面でRXゲインを変更できる(検索中も可)。** AGC のON/OFFと、手動ゲイン 0〜73 dB(−/+)。設定は RXゲイン画面と共通。  
   **RX gain can be changed on the search screen (also during a search).** AGC on/off and manual gain 0–73 dB (−/+); shared with the RX Gain screen.
4. **画面を離れたら検索を停止する。** 繰り返しにより裏で走り続けるのを防ぐ。  
   **The search stops when the screen is left**, so a repeating scan never keeps running in the background.

## 2. 画面 / UI

右側の「検索結果」カードの下段 / Bottom of the right-hand "Search Result" card:

```
最も強い周波数: 1273000 kHz (RSSI 30)
検索方法 / Search Mode                     [ 連続 / Repeat ] [ 1回 / Once ]
RXゲイン / RX Gain                  [AGC]  [ − ]  60 dB  [ + ]
```

- 検索方法は排他的な2ボタン。選択中は水色(`#54bce0`)で強調 / Two exclusive buttons; the selected one is highlighted.
- 「−」「+」は長押しで連続変更(押下から400ms後に開始、80ms間隔)/ Hold to repeat (starts after 400 ms, every 80 ms).
- AGC が ON の間は「−」「+」を無効にする(RXゲイン画面のスライダーと同じ)/ Disable −/+ while AGC is on.
- 文言 / Labels: 「検索方法」/Search Mode、「連続」/Repeat、「1回」/Once、「RXゲイン」/RX Gain、「AGC」

## 3. 設定 / Settings

| 項目 / Field | 型 / Type | 既定 / Default | 意味 / Meaning |
| --- | --- | --- | --- |
| `rssi_repeat_scan` (**新規 / new**) | bool | `true` | true=連続、false=1回 / true = Repeat, false = Once |
| `rx_agc_enabled` (既存 / existing) | bool | `false` | AGC の ON/OFF |
| `rx_gain_db` (既存 / existing) | int | `60` | 手動ゲイン 0〜73 dB。AGC OFF のときのみ有効 |

`rssi_repeat_scan` が無い旧設定ファイルは既定値(連続)で読み込む(既存の読み込み処理が、無いキーを既定値で補う)。  
A legacy settings file without `rssi_repeat_scan` loads with the default (Repeat).

RXゲイン画面と検索画面は同じ `rx_agc_enabled` / `rx_gain_db` を共有する。画面表示時(`on_show`)に、設定値から
コントロールを再読み込みすること。  
The RX Gain screen and the search screen share the same `rx_agc_enabled` / `rx_gain_db`; reload the controls from the settings whenever the screen is shown.

## 4. 検索の動作 / Scan behaviour

定数 / Constants: `STEP_INTERVAL_MS = 150`(1ステップの間隔 / step interval)、`_PEAK_THRESHOLD_DB = 3.0`、
`RX_GAIN_MIN_DB = 0`、`RX_GAIN_MAX_DB = 73`、ゲイン反映のデバウンス / gain debounce = 250 ms。

```text
start():                                  # 「検索開始」
    parse start / end / step, validate (end > start, step >= 1 kHz)
    startFreq, endFreq, stepHz = ...
    applyRxGain()                         # 現在のゲイン設定をPlutoへ / push the current gain setting
    beginSweep()
    scanning = true; button = "検索停止"
    (オンデバイス復調ON かつ TX未動作 → TXを自動開始し、3秒待ってからタイマー開始 / with on-device demod: start TX, wait 3 s)
    timer.start(STEP_INTERVAL_MS)

beginSweep():                             # 1周(開始→終了)の開始 / start one pass
    currentFreq = startFreq
    scanBest = none; scanRssiValues = []
    graph.setRange(startFreq, endFreq)    # グラフをクリア / clears the graph
    graph.setCenter(operating frequency)

scanStep():                               # 150msごと / every 150 ms
    if currentFreq > endFreq:             # 1周終わり / end of a pass
        if not rssi_repeat_scan:          # 「1回」/ Once
            stop(); return
        commitScanResult()                # 「連続」/ Repeat
        beginSweep(); return
    set RX LO = currentFreq; rssi = read RSSI
    if rssi ok: graph.addPoint; scanRssiValues.add(rssi)
                if scanBest is none or rssi < scanBest.rssi: scanBest = (currentFreq, rssi)   # 小さいほど強い
    currentFreq += stepHz

stop():                                   # 「検索停止」/ 1回の終了 / 画面を離れたとき
    timer.stop(); scanning = false; button = "検索開始"
    (この検索でTXを自動開始していた場合のみTXを停止 / stop TX only if this search started it)
    commitScanResult()

commitScanResult():
    if scanBest is none or scanRssiValues is empty: return
    if max(scanRssiValues) - min(scanRssiValues) < 3.0 dB: return      # 明確なピークなし → 前回値を保持
    bestFreq = scanBest.freq; bestRssi = scanBest.rssi
    label = "最も強い周波数: {bestFreq/1000} kHz (RSSI {bestRssi})"

onHide():                                 # 他の画面へ移るとき / when leaving the screen
    if scanning: stop()
```

- 「連続」の1周ごとに `commitScanResult()` で「最も強い周波数」を更新表示する / In Repeat mode the strongest frequency is updated after every pass.
- 検索方法を検索中に切り替えても、実行中の周回は中断しない。次に周回の終わりに達した時点で新しい方法が使われる。  
  Changing the mode during a search does not interrupt the pass in progress; the new mode is used when the pass ends.
- **RSSI は値が小さいほど信号が強い**(グラフは反転して描く)/ **A smaller RSSI value means a stronger signal** (the graph is drawn inverted).

## 5. RXゲイン / RX gain

```text
onGainButton(delta):                      # 「−」「+」
    new = clamp(rx_gain_db + delta, 0, 73); if unchanged: return
    rx_gain_db = new; save settings; update label
    gainApplyTimer.restart(250 ms)        # 連打・長押しをまとめる / coalesce taps and holds

onAgcToggled(on):
    rx_agc_enabled = on; save settings; enable/disable −,+
    gainApplyTimer.restart(250 ms)

applyRxGain():                            # タイマー満了時と検索開始時 / on timer expiry and at search start
    try:
        if rx_agc_enabled: set gain_control_mode = "slow_attack"
        else:              set gain_control_mode = "manual"; set hardwaregain = rx_gain_db
    catch (timeout / I/O error): return   # Plutoに届かなくても設定値は保存済み。次回に反映 / setting is already saved
    if scanning: beginSweep()             # ★下記の理由で周回をやり直す / restart the pass, see below
```

**検索中にゲインを変えたら、その周回を最初からやり直す。** ゲインが変わると RSSI の絶対値が変わるため、同じ1周の中に
異なるゲインの測定値が混ざると「最も強い周波数」を誤判定する。  
**If the gain is changed during a search, restart the current pass.** A gain change shifts the absolute RSSI value; mixing measurements taken at different
gains in one pass would make the "strongest frequency" wrong.

`rx_agc_enabled = true` は `slow_attack`(`shonan_rx.py` の受信起動時の設定と同じ)。`false` は `manual` + `hardwaregain`。  
AGC on = `slow_attack` (same as the receive start-up in `shonan_rx.py`); off = `manual` + `hardwaregain`.

## 6. Pluto(AD9361)の操作 / Pluto (AD9361) access

Windows/Pi 5 版は `iio_attr` コマンドで行う。Android/iPad 版では libiio の同じチャンネル属性に読み替える。  
The Windows/Pi 5 editions use the `iio_attr` command. On Android/iPad use the same channel attributes through libiio.

| 用途 / Purpose | デバイス・チャンネル / Device · channel | 属性 / Attribute | 値 / Value |
| --- | --- | --- | --- |
| 受信周波数を設定 / Set RX frequency | `ad9361-phy` · `altvoltage0` | `frequency` | Hz(整数 / integer) |
| RSSI を読む / Read RSSI | `ad9361-phy` · `voltage0`(input) | `rssi` | 例 / e.g. `40.00 dB` → 先頭の数値 / the leading number |
| ゲインモード / Gain mode | `ad9361-phy` · `voltage0`(input) | `gain_control_mode` | `manual` / `slow_attack` |
| 手動ゲイン / Manual gain | `ad9361-phy` · `voltage0`(input) | `hardwaregain` | dB(例 / e.g. `60`) |

```text
iio_attr -u <uri> -c ad9361-phy altvoltage0 frequency <Hz>
iio_attr -u <uri> -c ad9361-phy voltage0 rssi
iio_attr -u <uri> -i -c ad9361-phy voltage0 gain_control_mode slow_attack|manual
iio_attr -u <uri> -i -c ad9361-phy voltage0 hardwaregain <dB>
```

`voltage0` は入力(RX)と出力(TX)の両方に存在するため、ゲインの操作には入力側を指す `-i` が必要。  
`voltage0` exists on both the input (RX) and output (TX) side, so gain access needs `-i` to select the input.

**注意 / Note:** ゲインの設定コマンドは実機で未検証。移植先で Pluto をつないだら、ゲインを変えて RSSI が変わることを確認すること。  
The gain-setting commands have not been verified on hardware. When porting, confirm on a real Pluto that changing the gain changes the RSSI.

## 7. 保存すべきテスト観点 / Test cases to reproduce

Windows 版では、`iio_attr` を偽の実装に差し替えたヘッドレステストで次を確認した。  
On Windows these were checked with a headless test that replaces `iio_attr` with a fake.

1. 連続: 3周以上続き、勝手に止まらない / Repeat: runs for 3+ passes and never stops by itself.
2. 1回: 1周(測定7回 + 終わりの検出1回)で自動停止 / Once: stops automatically after one pass.
3. 連続の検索中に「1回」へ切り替え: その周回の終わりで止まる / Switch to Once during a Repeat search: stops at the end of that pass.
4. 「検索停止」で停止し、ボタン表示が「検索開始」に戻る / "Stop Search" stops and the button returns to "Start Search".
5. 画面を離れる(`on_hide`)と停止し、タイマーも止まる / Leaving the screen stops the search and its timer.
6. 3回連続でクリックしても、Plutoへの反映は250ms後に1回だけ(`gain_control_mode` と `hardwaregain`)/ Three quick taps produce one push after 250 ms.
7. 検索中もゲイン操作が有効で、変更すると周回が最初からやり直される / Gain controls stay enabled during a search and a change restarts the pass.
8. AGC ON: `slow_attack` を設定し、−/+ が無効。OFF: `manual` + `hardwaregain` / AGC on disables −/+ and sets `slow_attack`; off sets `manual` + `hardwaregain`.
9. ゲインは 0〜73 dB にクランプ / Gain is clamped to 0–73 dB.
10. Pluto に届かない場合(タイムアウト)でも落ちず、周回もやり直さない / An unreachable Pluto neither crashes nor restarts the pass.
11. 設定ファイルに `rssi_repeat_scan` が無くても「連続」で読み込む / A settings file without `rssi_repeat_scan` loads as Repeat.

## 8. 移植手順 / How to port

- **Pi 5 版(Python/PyQt5、同じコードベース)/ Pi 5 edition (same Python/PyQt5 code base):** このフォルダの差分を適用する。
  このリポジトリでは `app/` だが、Pi 5 版のリポジトリでは `pi5/` の場合がある。  
  Apply the patch in this folder. It uses `app/`; a Pi 5 repository may use `pi5/` instead.
  ```powershell
  git apply --directory=pi5 docs/rssi-measurement/rssi-changes.patch   # pi5/ の場合 / for a pi5/ layout
  ```
  適用後、`rssi.py` 内の `Pluto+` 表記など版ごとの差異は手で合わせる。  
  After applying, reconcile edition-specific differences by hand.
- **Android / iPad 版:** 3〜5章の動作をそのまま実装する。UI は各プラットフォームの部品で構わない。設定は `rssi_repeat_scan`
  (Boolean、既定 true)を追加し、RXゲインは既存の設定値を共有する。Pluto の操作は6章の属性を libiio 経由で行う。  
  Implement chapters 3–5 as described; the UI may use each platform's own widgets. Add the `rssi_repeat_scan` Boolean setting (default true),
  share the existing RX gain settings, and access Pluto through libiio using the attributes in chapter 6.
- **操作説明書 / Manuals:** 「検索方法」「RXゲイン」の説明を追加し、「新中心周波数」の記述を削除する。文言は
  [`manual_content_win.py`](../../app/gui/manual_content_win.py) と [`manual_content_win_en.py`](../../app/gui/manual_content_win_en.py) のRSSI測定の章を参照。  
  Add descriptions of "Search Mode" and "RX Gain" and remove the "Set as Center" text; see the RSSI Measurement chapter of the two files above for the wording.
