-- =====================================================================
-- Hotel Competitive Intelligence Platform (HCIP)
-- データベース設計書 (Version 1.0)
-- =====================================================================

-- 既存テーブルの削除（初期化・再ラン用）
DROP TABLE IF EXISTS sys_execution_logs CASCADE;
DROP TABLE IF EXISTS trn_room_prices CASCADE;
DROP TABLE IF EXISTS mst_survey_dates CASCADE;
DROP TABLE IF EXISTS mst_hotels CASCADE;

-- ---------------------------------------------------------------------
-- 1. ホテルマスタ (mst_hotels)
-- ---------------------------------------------------------------------
CREATE TABLE mst_hotels (
    hotel_id SERIAL PRIMARY KEY,
    hotel_name VARCHAR(255) NOT NULL,
    brand_name VARCHAR(100),
    location_address VARCHAR(255),
    is_target BOOLEAN DEFAULT TRUE NOT NULL, -- 調査対象かどうかのフラグ
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- コメント追加
COMMENT ON TABLE mst_hotels IS '調査対象ホテルおよび自社ホテルのマスタ情報を管理するテーブル';

-- ---------------------------------------------------------------------
-- 2. 調査日マスタ (mst_survey_dates)
-- ---------------------------------------------------------------------
CREATE TABLE mst_survey_dates (
    date_id SERIAL PRIMARY KEY,
    target_date DATE NOT NULL UNIQUE,
    season_type VARCHAR(20) NOT NULL CHECK (season_type IN ('Peak', 'Shoulder', 'Off')),
    is_active BOOLEAN DEFAULT TRUE NOT NULL, -- 現在有効な調査日か
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE mst_survey_dates IS '調査対象となる宿泊日（シーズン分類含む）を管理するテーブル';

-- ---------------------------------------------------------------------
-- 3. 料金取得トランザクション (trn_room_prices)
-- ---------------------------------------------------------------------
CREATE TABLE trn_room_prices (
    price_snapshot_id BIGSERIAL PRIMARY KEY,
    hotel_id INT NOT NULL REFERENCES mst_hotels(hotel_id) ON DELETE CASCADE,
    ota_name VARCHAR(50) NOT NULL, -- 'Booking.com', 'Expedia', '一休.com', '楽天トラベル', '公式サイト'
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL, -- 取得日時
    checkin_date DATE NOT NULL, -- 宿泊日
    room_name_raw VARCHAR(255) NOT NULL, -- 部屋名称（スクレイピング生データ）
    room_category VARCHAR(10) NOT NULL CHECK (room_category IN ('T1', 'T2', 'T3', 'T4')), -- 自動分類結果
    price_amount NUMERIC(12, 2) NOT NULL, -- 販売価格
    currency VARCHAR(10) DEFAULT 'JPY' NOT NULL, -- 通貨
    is_tax_included BOOLEAN DEFAULT TRUE NOT NULL, -- 税情報
    cancellation_policy TEXT, -- キャンセル条件
    meal_condition VARCHAR(100), -- 食事条件（'素泊まり', '朝食付き' など）
    availability_status VARCHAR(20) NOT NULL CHECK (availability_status IN ('Available', 'SoldOut', 'Unknown')), -- 販売状況
    source_url TEXT, -- 取得URL
    screenshot_path VARCHAR(512), -- スクリーンショット保存先パス
    html_path VARCHAR(512), -- HTML保存先パス
    notes TEXT, -- 備考・取得結果（エラー内容など）
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE trn_room_prices IS '各サイトから取得した競合ホテルの料金履歴を永続保存するトランザクションテーブル';

-- ---------------------------------------------------------------------
-- 4. システム実行ログ (sys_execution_logs)
-- ---------------------------------------------------------------------
CREATE TABLE sys_execution_logs (
    log_id BIGSERIAL PRIMARY KEY,
    executed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    log_level VARCHAR(10) NOT NULL CHECK (log_level IN ('INFO', 'WARN', 'ERROR', 'FATAL')),
    module_name VARCHAR(100) NOT NULL, -- 'Scraper', 'Analyzer', 'Reporter' など
    message TEXT NOT NULL,
    stack_trace TEXT,
    hotel_id INT REFERENCES mst_hotels(hotel_id) ON DELETE SET NULL, -- 特定ホテル処理中のエラー用
    ota_name VARCHAR(50)
);

COMMENT ON TABLE sys_execution_logs IS 'スクレイピング巡回ログやシステムエラーを記録するログテーブル';

-- =====================================================================
-- パフォーマンス最適化（インデックス定義）
-- =====================================================================

-- 料金分析（ADR/RevPAR算出）、トレンド検索、推移表示で最も多用される複合インデックス
CREATE INDEX idx_trn_room_prices_analysis
ON trn_room_prices (hotel_id, checkin_date, ota_name, room_category);

-- 特定の取得バッチや最新データを絞り込むためのインデックス
CREATE INDEX idx_trn_room_prices_fetched_at
ON trn_room_prices (fetched_at);

-- 日次・月次処理で調査日マスタを高速参照するためのインデックス
CREATE INDEX idx_mst_survey_dates_query
ON mst_survey_dates (target_date) WHERE is_active = TRUE;
