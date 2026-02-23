-- Central DB schema (PostgreSQL). One admin ↔ their users; multiple admins supported.
-- Run this on your PostgreSQL server once (e.g. psql -f central_schema.sql).

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Admins: from Admin Panel (bot_id + api_key). is_admin = true for all rows here.
-- admin_access_code: unique per admin; use in Android app to identify admin (generated on first save).
CREATE TABLE IF NOT EXISTS admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255),
    email VARCHAR(255),
    bot_id VARCHAR(255) NOT NULL,
    api_key VARCHAR(255) NOT NULL,
    admin_access_code VARCHAR(32) UNIQUE,
    connection_code VARCHAR(32) UNIQUE,
    fcm_token VARCHAR(255),
    is_admin BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(bot_id, api_key)
);

-- If table already exists without admin_access_code, run: ALTER TABLE admins ADD COLUMN IF NOT EXISTS admin_access_code VARCHAR(32) UNIQUE;
-- If table already exists without connection_code, run: ALTER TABLE admins ADD COLUMN IF NOT EXISTS connection_code VARCHAR(32) UNIQUE;

-- Users: from app (bot_id + api_key). Many users can link to one admin (by connection_code).
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    name VARCHAR(255),
    bot_id VARCHAR(255) NOT NULL,
    api_key VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    fcm_token VARCHAR(255),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(bot_id, api_key)
);

CREATE INDEX IF NOT EXISTS idx_users_admin_id ON users(admin_id);

-- If you had UNIQUE(admin_id) and need many users per admin, run:
-- ALTER TABLE users DROP CONSTRAINT IF EXISTS users_admin_id_key;
-- ALTER TABLE users ADD CONSTRAINT users_bot_id_api_key_key UNIQUE (bot_id, api_key);

CREATE TABLE IF NOT EXISTS medicines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    box_id VARCHAR(10),
    dosage VARCHAR(100),
    times JSONB NOT NULL DEFAULT '[]',
    low_stock INT DEFAULT 5,
    quantity INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- If table already exists without quantity: ALTER TABLE medicines ADD COLUMN IF NOT EXISTS quantity INT DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_medicines_user_id ON medicines(user_id);

CREATE TABLE IF NOT EXISTS dose_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    medicine_id UUID REFERENCES medicines(id) ON DELETE SET NULL,
    box_id VARCHAR(10),
    taken_at TIMESTAMPTZ DEFAULT NOW(),
    source VARCHAR(20) DEFAULT 'desktop',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dose_logs_user_id ON dose_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_dose_logs_taken_at ON dose_logs(taken_at);

CREATE TABLE IF NOT EXISTS alert_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    settings JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);

CREATE INDEX IF NOT EXISTS idx_alert_settings_user_id ON alert_settings(user_id);

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    admin_id UUID NOT NULL REFERENCES admins(id) ON DELETE CASCADE,
    type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    sent_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS sync_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device VARCHAR(50) NOT NULL,
    user_id UUID REFERENCES users(id),
    last_sync TIMESTAMPTZ DEFAULT NOW()
);
