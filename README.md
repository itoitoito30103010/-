# 競合ホテル料金 自動調査ツール

エリア（または施設番号）と日付を指定すると、複数ホテルの**客室タイプ別（T1〜T4グレード）
販売単価（税・サービス料込み総額）**を、楽天トラベル公式APIで自動収集し、Excel/CSVに出力します。

アップロードされた「競合ホテル料金調査：自動データ取得プロトコル」の条件
（大人2名・素泊まり優先・返金不可除外・満室N/A・2泊縛りフォールバック等）を、
そのまま設定として実装しています。

## なぜスクレイピングではなくAPIか
サイトのHTMLスクレイピングは利用規約に抵触するおそれがあり、画面変更で壊れやすく不安定です。
本ツールは楽天が公式提供する **楽天トラベル空室検索API (VacantHotelSearch)** を使うため、
規約に準拠しつつ、部屋・プラン単位の税サ込み総額を安定して取得できます。

> 楽天APIは客室タイプでの絞り込みができないため、**部屋名称の文字列でT1〜T4を判定**します
> （`config.yaml` の `grades` でキーワード調整可能）。

## セットアップ

```bash
pip install -r requirements.txt
```

1. 楽天ウェブサービスで無料のアプリを作成し、**アプリID**と**アクセスキー**を取得
   → https://webservice.rakuten.co.jp/app/create
2. 認証情報を環境変数に設定（推奨。コード直書き不要）
   ```bash
   export RAKUTEN_APP_ID="あなたのアプリID"
   export RAKUTEN_ACCESS_KEY="あなたのアクセスキー"
   ```
   （または `config.yaml` の `credentials` に記入）

## 使い方

```bash
# ① まず動作確認（API不要・サンプルデータでロジックを検証）
python survey.py --dry-run

# ② 施設番号を名前から検索して config.yaml に転記（最も確実な取得方法）
python find_hotel_no.py

# ③ 本番調査（config.yaml の全日程・全ホテル）
python survey.py

# ④ 単発調査（日付を指定して即実行）
python survey.py --checkin 2026-08-07 --label W1
```

出力: `outputs/competitor_rates_YYYYMMDD_HHMMSS.xlsx` および `.csv`

出力列は調査プロトコル準拠:
`日程区分 / ホテル名 / グレード / 客室タイプ名 / 総額料金(2名) / プラン名 / 備考`

## カスタマイズ（config.yaml）

| 項目 | 内容 |
|---|---|
| `dates` | 調査日程（W1/W2/W3…）。ラベル・チェックイン日・泊数 |
| `hotels` | 対象ホテル。`hotel_no` があれば最優先で使用 |
| `area` | 施設番号未設定時のエリア一括検索（地区コード） |
| `grades` | T1〜T4の判定キーワード（上から順に評価） |
| `search.meal_preference` | `room_only`（素泊まり優先）/ `breakfast` |
| `search.exclude_non_refundable` | 返金不可プランを可能な範囲で除外 |
| `search.two_night_fallback` | 1泊満室時に2泊で再検索し1泊平均を算出 |

## 別エリアへの展開
`config.yaml` の `area`（地区コード）と `hotels`（対象施設）を差し替えるだけで、
沖縄以外のどのエリアにも適用できます。地区コードは
[地区コードAPI](https://webservice.rakuten.co.jp/explorer/api/Travel/GetAreaClass) で確認できます。

## Claude Cowork との連携
`cowork_task.md` を参照。フォルダごと Cowork に渡せば、
実行→Excel要約→前回との差分比較→レポート化までエージェントに任せられます。

## 制限事項
- 「返金不可」除外はプラン名/部屋名の文言ベースの best-effort です。
  APIはキャンセル規定を構造化フィールドで返さないため、100%の除外は保証されません。
- 楽天トラベルに掲載のない（＝他OTA専売の）在庫・料金は取得できません。
- 短時間の大量リクエストは429エラーになります（`request_interval_sec`で調整）。
