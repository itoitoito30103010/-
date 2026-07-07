---
name: hotel-survey
description: 競合ホテル料金調査を実行するスキル。楽天トラベルAPIで config.yaml に設定したホテルの客室タイプ別（T1〜T4）料金を収集し、Excel/CSV に出力します。--dry-run でAPIなしの動作確認も可能。
---

# 競合ホテル料金調査スキル

## 前提条件

- Python パッケージ: `pyyaml`, `requests`, `openpyxl`
- 環境変数:
  - `RAKUTEN_APP_ID`: 楽天ウェブサービスのアプリID（UUID形式）
  - `RAKUTEN_ACCESS_KEY`: アクセスキー（`pk_...`形式）

## 実行手順

### 1. 依存パッケージの確認・インストール

```bash
pip install pyyaml requests openpyxl
```

### 2. 動作確認（APIキー不要）

```bash
python survey.py --dry-run
```

サンプルデータで T1〜T4 のグレード分類・出力ロジックを検証する。

### 3. 本番調査（config.yaml の全日程・全ホテル）

```bash
python survey.py
```

### 4. 単発調査（日付指定）

```bash
python survey.py --checkin 2026-08-07 --label W1
```

## API仕様（2026年対応済み）

- エンドポイント: `https://openapi.rakuten.co.jp/engine/api/Travel/`
- 必須ヘッダー: `Origin: https://localhost`（`config.yaml` の `credentials.origin` で変更可）
- アプリID形式: UUID（例: `5b5296f8-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）
- アクセスキー形式: `pk_...`

> **注意**: 2026年5月に旧エンドポイント（`app.rakuten.co.jp`）は廃止。  
> Travel API の VacantHotelSearch/KeywordHotelSearch が新ドメインで 503 を返す場合は、楽天ウェブサービスのサポートへ問い合わせること。

## 設定ファイル（config.yaml）

### 調査対象ホテル（hotel_no 確定済み）

| ホテル | hotel_no |
|---|---|
| ハレクラニ沖縄 | 172611 |
| ルネッサンス リゾート オキナワ | 54315 |
| シェラトン沖縄サンマリーナリゾート | 13554 |
| ANAインターコンチネンタル万座ビーチリゾート | 16123 |
| カフーリゾート フチャク コンド・ホテル | 78239 |
| ムーンビーチ | 15483 |
| ホテルモントレ沖縄 | 141596 |
| ハイアットリージェンシー瀬良垣アイランド沖縄 | 166320 |

### 調査日程

| ラベル | チェックイン | 区分 |
|---|---|---|
| W1 | 2026-08-07 | ピーク |
| W2 | 2026-10-14 | ショルダー |
| W3 | 2026-12-09 | オフ |

### 主要パラメータ

- 大人2名・素泊まり優先・返金不可除外・1泊満室時は2泊フォールバック
- `request_interval_sec: 1.0`（429対策）

## 出力

`outputs/competitor_rates_YYYYMMDD_HHMMSS.xlsx` および `.csv`

列: `日程区分 / ホテル名 / グレード / 客室タイプ名 / 総額料金(2名) / プラン名 / 備考`

## ホテル番号の追加・変更

新しいホテルを追加する場合は楽天トラベルのホテルページURL（`travel.rakuten.co.jp/HOTEL/[番号]/`）から `hotel_no` を確認し、`config.yaml` の `hotels` セクションに追記する。

## トラブルシューティング

| エラー | 原因 | 対処 |
|---|---|---|
| `wrong_parameter` / `specify valid applicationId` | 旧エンドポイント使用 | `rakuten_client.py` のエンドポイントが `openapi.rakuten.co.jp` になっているか確認 |
| 503 on new endpoint | Travel API が新ドメイン未対応の可能性 | 楽天サポートに問い合わせ |
| 403 (proxy) | Cloud環境のネットワーク制限 | ローカルPCで実行 |
| 429 | レートリミット | `config.yaml` の `request_interval_sec` を増やす |
