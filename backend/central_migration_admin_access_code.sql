-- Migration: add admin_access_code to admins (run once if admins table already exists).
ALTER TABLE admins ADD COLUMN IF NOT EXISTS admin_access_code VARCHAR(32) UNIQUE;
