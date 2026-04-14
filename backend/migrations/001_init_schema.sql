-- SalesPilot CRM - MySQL 8 schema
-- Metadata-driven CRM base tables

SET NAMES utf8mb4;

CREATE TABLE users (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    email           VARCHAR(255) NOT NULL UNIQUE,
    username        VARCHAR(100) NOT NULL,
    hashed_pwd      VARCHAR(255) NOT NULL,
    role            ENUM('admin', 'manager', 'sales') NOT NULL DEFAULT 'sales',
    avatar_url      VARCHAR(500) NULL,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    INDEX idx_users_email (email),
    INDEX idx_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE accounts (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name            VARCHAR(255) NOT NULL,
    industry        VARCHAR(100) NULL,
    size            VARCHAR(50) NULL,
    annual_revenue  DECIMAL(15, 2) NULL,
    website         VARCHAR(500) NULL,
    owner_id        CHAR(36) NULL,
    custom_fields   JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_accounts_owner FOREIGN KEY (owner_id) REFERENCES users(id),
    INDEX idx_accounts_owner (owner_id),
    INDEX idx_accounts_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE contacts (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name            VARCHAR(255) NOT NULL,
    title           VARCHAR(200) NULL,
    email           VARCHAR(255) NULL,
    phone           VARCHAR(50) NULL,
    account_id      CHAR(36) NULL,
    owner_id        CHAR(36) NULL,
    custom_fields   JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_contacts_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    CONSTRAINT fk_contacts_owner FOREIGN KEY (owner_id) REFERENCES users(id),
    INDEX idx_contacts_account (account_id),
    INDEX idx_contacts_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE leads (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name            VARCHAR(255) NOT NULL,
    company         VARCHAR(255) NULL,
    email           VARCHAR(255) NULL,
    phone           VARCHAR(50) NULL,
    source          VARCHAR(100) NULL,
    status          ENUM('New', 'Working', 'Nurturing', 'Converted', 'Disqualified') DEFAULT 'New',
    score           SMALLINT DEFAULT 0,
    owner_id        CHAR(36) NULL,
    converted_to    CHAR(36) NULL,
    custom_fields   JSON NOT NULL DEFAULT (JSON_OBJECT()),
    ai_extracted    JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_leads_owner FOREIGN KEY (owner_id) REFERENCES users(id),
    INDEX idx_leads_owner (owner_id),
    INDEX idx_leads_status (status),
    INDEX idx_leads_score (score),
    CONSTRAINT chk_leads_score CHECK (score BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE opportunities (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name            VARCHAR(500) NOT NULL,
    account_id      CHAR(36) NULL,
    contact_id      CHAR(36) NULL,
    owner_id        CHAR(36) NULL,
    stage           ENUM('初步接触', '方案报价', '合同谈判', '赢单', '输单') NOT NULL DEFAULT '初步接触',
    amount          DECIMAL(15, 2) NULL,
    probability     SMALLINT DEFAULT 20,
    close_date      DATE NULL,
    source          VARCHAR(100) NULL,
    ai_confidence   DECIMAL(4, 3) NULL,
    ai_raw_text     TEXT NULL,
    ai_extracted    JSON NOT NULL DEFAULT (JSON_OBJECT()),
    custom_fields   JSON NOT NULL DEFAULT (JSON_OBJECT()),
    stage_history   JSON NOT NULL DEFAULT (JSON_ARRAY()),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    closed_at       DATETIME(6) NULL,
    CONSTRAINT fk_opps_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE SET NULL,
    CONSTRAINT fk_opps_contact FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE SET NULL,
    CONSTRAINT fk_opps_owner FOREIGN KEY (owner_id) REFERENCES users(id),
    INDEX idx_opps_owner (owner_id),
    INDEX idx_opps_stage (stage),
    INDEX idx_opps_close_date (close_date),
    INDEX idx_opps_amount (amount),
    CONSTRAINT chk_opps_probability CHECK (probability BETWEEN 0 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE activities (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    type            VARCHAR(50) NOT NULL,
    subject         VARCHAR(500) NULL,
    description     TEXT NULL,
    owner_id        CHAR(36) NULL,
    opp_id          CHAR(36) NULL,
    lead_id         CHAR(36) NULL,
    account_id      CHAR(36) NULL,
    due_date        DATETIME(6) NULL,
    completed_at    DATETIME(6) NULL,
    custom_fields   JSON NOT NULL DEFAULT (JSON_OBJECT()),
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    CONSTRAINT fk_activities_owner FOREIGN KEY (owner_id) REFERENCES users(id),
    CONSTRAINT fk_activities_opp FOREIGN KEY (opp_id) REFERENCES opportunities(id) ON DELETE CASCADE,
    CONSTRAINT fk_activities_lead FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
    CONSTRAINT fk_activities_account FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    INDEX idx_activities_owner (owner_id),
    INDEX idx_activities_opp (opp_id),
    INDEX idx_activities_lead (lead_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE metadata_fields (
    id              CHAR(36) PRIMARY KEY DEFAULT (UUID()),
    object_name     VARCHAR(100) NOT NULL,
    field_name      VARCHAR(100) NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    field_type      VARCHAR(50) NOT NULL,
    options         JSON NULL,
    is_required     BOOLEAN DEFAULT FALSE,
    is_visible      BOOLEAN DEFAULT TRUE,
    sort_order      INT DEFAULT 0,
    created_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    UNIQUE KEY uq_metadata_fields_object_field (object_name, field_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO metadata_fields (object_name, field_name, display_name, field_type, is_required, is_visible, sort_order) VALUES
('Opportunity', 'customer_name', '客户名称', 'String', TRUE, TRUE, 1),
('Opportunity', 'deal_value', '预计金额', 'Currency', TRUE, TRUE, 2),
('Opportunity', 'stage', '商机阶段', 'Enum', TRUE, TRUE, 3),
('Opportunity', 'close_date', '预计结单', 'Date', FALSE, TRUE, 4),
('Opportunity', 'probability', '赢单概率', 'Percent', FALSE, TRUE, 5),
('Opportunity', 'source', '来源渠道', 'Enum', FALSE, TRUE, 6),
('Opportunity', 'ai_confidence', 'AI置信度', 'Float', FALSE, TRUE, 7),
('Lead', 'name', '姓名', 'String', TRUE, TRUE, 1),
('Lead', 'company', '公司', 'String', TRUE, TRUE, 2),
('Lead', 'status', '状态', 'Enum', TRUE, TRUE, 3),
('Lead', 'score', '线索评分', 'Number', FALSE, TRUE, 4),
('Lead', 'source', '来源', 'Enum', FALSE, TRUE, 5);

-- 用户账号不再预置演示数据。
-- 首个管理员请在数据库初始化完成后，通过以下命令创建：
-- python create_admin.py --email admin@example.com --username 系统管理员 --password StrongPass123
