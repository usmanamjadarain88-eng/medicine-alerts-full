-- One admin per email (case-insensitive). Empty email allowed for multiple admins.
CREATE UNIQUE INDEX IF NOT EXISTS admins_email_unique
ON admins (LOWER(TRIM(email)))
WHERE TRIM(email) != '';
