-- 007_add_checkins_table.sql
-- 添加打卡记录表

CREATE TABLE IF NOT EXISTS checkins (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    opportunity_id VARCHAR(36),
    latitude DECIMAL(10, 7) NOT NULL,
    longitude DECIMAL(10, 7) NOT NULL,
    address VARCHAR(500),
    location_name VARCHAR(255),
    checkin_type VARCHAR(30) NOT NULL DEFAULT 'visit',
    remark TEXT,
    customer_name VARCHAR(255),
    images JSON,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_checkins_user_id (user_id),
    INDEX idx_checkins_opportunity_id (opportunity_id),
    INDEX idx_checkins_created_at (created_at),
    CONSTRAINT fk_checkins_user FOREIGN KEY (user_id) REFERENCES users(id),
    CONSTRAINT fk_checkins_opportunity FOREIGN KEY (opportunity_id) REFERENCES opportunities(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
