-- Migration 006: Add admin users table for web panel authentication
-- This enables user management with roles instead of a single API token

CREATE TABLE IF NOT EXISTS admin_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    must_change_password BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login TIMESTAMP WITH TIME ZONE,
    created_by VARCHAR(50)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_admin_users_username ON admin_users(username);

-- Insert default admin user (password: admin) - MUST be changed on first login
-- Password hash is bcrypt hash of 'admin'
INSERT INTO admin_users (username, password_hash, role, must_change_password, created_by)
VALUES ('admin', '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.mqOKZqPBXWqCKm', 'admin', true, 'system')
ON CONFLICT (username) DO NOTHING;

-- Grant permissions
GRANT ALL PRIVILEGES ON TABLE admin_users TO luminisbot;
GRANT USAGE, SELECT ON SEQUENCE admin_users_id_seq TO luminisbot;

-- Add comment
COMMENT ON TABLE admin_users IS 'Admin users for web panel authentication with role-based access';
COMMENT ON COLUMN admin_users.role IS 'User role: admin (full access) or user (read-only)';
COMMENT ON COLUMN admin_users.must_change_password IS 'If true, user must change password on next login';
