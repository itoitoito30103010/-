# Claude Cowork タスク指示書 ― 競合ホテル料金 定期調査

このプロジェクト一式（hotel-rate-survey フォルダ）を Claude Cowork に渡し、
以下をそのまま指示として貼り付けると、Cowork がエージェントとして
調査〜要約〜差分比較まで実行できます。

---

## 貼り付け用プロンプト（例）

> 添付の `hotel-rate-survey` フォルダは、楽天トラベル空室検索APIで競合ホテルの
> 客室タイプ別（T1〜T4）料金を収集するツールです。以下を順に実行してください。
>
> 1. `requirements.txt` の依存をインストール。
> 2. 環境変数 `RAKUTEN_APP_ID` と `RAKUTEN_ACCESS_KEY` を（私が別途伝える値で）設定。
> 3. まだ `config.yaml` の各ホテルに `hotel_no` が入っていなければ、
>    `python find_hotel_no.py` を実行し、候補から正しい施設番号を `config.yaml` に転記。
> 4. `python survey.py` を実行し、`outputs/` に Excel と CSV を生成。
> 5. 生成された Excel を読み、**日程区分ごとの価格帯サマリー**（各グレードの最安・
>    中央値・最高、および前回調査ファイルがあればその差分）を Markdown で報告。
> 6. N/A（満室/該当なし）が多いホテル・グレードがあれば、`config.yaml` の
>    `grades[].any_keywords` の調整案、または `two_night_fallback` の活用を提案。

---

## Cowork に任せると便利な発展タスク

- **定期実行**: 「毎週月曜にこの調査を実行し、前回との差分を要約して」
- **アラート**: 「競合の T2（オーシャンビュー）が自社より安い日程だけ抜き出して」
- **レポート化**: 「結果を Word の週次レポートに整形して」
  （※Word 生成は Cowork 側の文書作成機能に引き継げます）
- **エリア拡張**: 「宮古島エリアも同じ枠組みで追加調査して」
  → `config.yaml` の `area` と `hotels` を編集して再実行するだけ。

## 注意（Cowork 実行時）
- 認証情報はコード直書きせず、Cowork の環境変数機能に設定してください。
- 短時間の大量リクエストは 429（Too Many Requests）になります。
  `config.yaml` の `request_interval_sec` は 1.0 秒以上を推奨。
