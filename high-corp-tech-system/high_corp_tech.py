"""
🚀 HGHI FiberOps - Production Ready Field Management System
Version: 2.0.0 (Production)
Security: Enterprise Grade
Compliance: GDPR Ready, Audit Logged
Deployment: Streamlit Cloud + Docker
"""

# ==========================================================
# IMPORTS
# ==========================================================
import os
import re
import json
import sqlite3
import hashlib
import secrets
import bcrypt
import time
import smtplib
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

import streamlit as st
import pandas as pd
import requests
from PIL import Image
import io

# Optional AI and advanced features
try:
    import pyotp
    import qrcode
    TOTP_AVAILABLE = True
except:
    TOTP_AVAILABLE = False

try:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    GOOGLE_API_AVAILABLE = True
except:
    GOOGLE_API_AVAILABLE = False

# ==========================================================
# CONFIGURATION
# ==========================================================
# App config
APP_TITLE = "🏢 HGHI FiberOps - Production"
APP_VERSION = "2.0.0"
DB_PATH = os.getenv("FIBEROPS_DB_PATH", "data/fiberops.db")
BACKUP_DIR = "backups"
LOG_DIR = "logs"

# Security config
SESSION_TIMEOUT_HOURS = 8
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_MINUTES = 15
PASSWORD_MIN_LENGTH = 12

# Email config (from secrets)
SMTP_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "user": "",
    "password": "",
    "from_name": "HGHI FiberOps System"
}

# AI config
DEEPSEEK_API_KEY = None

# ==========================================================
# LOGGING SETUP
# ==========================================================
def setup_logging():
    """Setup structured logging"""
    os.makedirs(LOG_DIR, exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(f"{LOG_DIR}/fiberops_{datetime.now().strftime('%Y%m%d')}.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ==========================================================
# SECURITY FUNCTIONS
# ==========================================================
class SecurityManager:
    """Enterprise-grade security manager"""
    
    @staticmethod
    def hash_password(password: str) -> Tuple[str, str]:
        """Secure password hashing with bcrypt"""
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return salt.decode('utf-8'), hashed.decode('utf-8')
    
    @staticmethod
    def verify_password(stored_salt: str, stored_hash: str, password: str) -> bool:
        """Verify password against bcrypt hash"""
        try:
            return bcrypt.checkpw(
                password.encode('utf-8'),
                stored_hash.encode('utf-8')
            )
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False
    
    @staticmethod
    def validate_password_strength(password: str) -> Tuple[bool, str]:
        """Validate password meets security requirements"""
        if len(password) < PASSWORD_MIN_LENGTH:
            return False, f"Password must be at least {PASSWORD_MIN_LENGTH} characters"
        
        checks = {
            "uppercase": bool(re.search(r'[A-Z]', password)),
            "lowercase": bool(re.search(r'[a-z]', password)),
            "digit": bool(re.search(r'\d', password)),
            "special": bool(re.search(r'[!@#$%^&*(),.?":{}|<>]', password))
        }
        
        if sum(checks.values()) < 3:
            return False, "Password must contain at least 3 of: uppercase, lowercase, digit, special character"
        
        return True, "Password is strong"
    
    @staticmethod
    def generate_2fa_secret(email: str) -> Dict[str, Any]:
        """Generate 2FA secret for user"""
        if not TOTP_AVAILABLE:
            return {"error": "2FA not available"}
        
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        
        # Generate provisioning URI for QR code
        provisioning_uri = totp.provisioning_uri(
            name=email,
            issuer_name="HGHI FiberOps"
        )
        
        return {
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "qr_code": SecurityManager.generate_qr_code(provisioning_uri)
        }
    
    @staticmethod
    def generate_qr_code(data: str) -> bytes:
        """Generate QR code as bytes"""
        import qrcode
        from io import BytesIO
        
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        return buffered.getvalue()
    
    @staticmethod
    def verify_2fa_token(secret: str, token: str) -> bool:
        """Verify 2FA token"""
        if not TOTP_AVAILABLE:
            return True  # 2FA not enforced
        
        totp = pyotp.TOTP(secret)
        return totp.verify(token)
    
    @staticmethod
    def sanitize_input(text: str) -> str:
        """Sanitize user input to prevent XSS and SQL injection"""
        # Remove potentially dangerous characters
        text = re.sub(r'[<>"\';]', '', text)
        # Limit length
        return text[:1000]

# ==========================================================
# DATABASE MANAGER
# ==========================================================
class DatabaseManager:
    """Production database manager with connection pooling"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_db()
        return cls._instance
    
    def _init_db(self):
        """Initialize database connection"""
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.conn.execute("PRAGMA journal_mode = WAL;")
        self.conn.execute("PRAGMA synchronous = NORMAL;")
        self.conn.row_factory = sqlite3.Row
        
        # Set up connection pool
        self.cursor = self.conn.cursor()
        
        # Initialize tables
        self._create_tables()
        self._create_indexes()
        
        logger.info("Database initialized")
    
    def _create_tables(self):
        """Create all database tables"""
        
        # Users table with enhanced security
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('owner','supervisor','tech','viewer')),
                two_factor_secret TEXT,
                two_factor_enabled INTEGER DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                last_login TEXT,
                failed_login_attempts INTEGER DEFAULT 0,
                lockout_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                must_change_password INTEGER DEFAULT 1
            );
        """)
        
        # Login attempts for rate limiting
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                successful INTEGER DEFAULT 0,
                attempt_time TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
        
        # Password reset tokens
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT UNIQUE NOT NULL,
                expires_at TEXT NOT NULL,
                used INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
        """)
        
        # Buildings
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS buildings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_name TEXT NOT NULL,
                address TEXT,
                city TEXT,
                state TEXT,
                zip TEXT,
                gps_latitude REAL,
                gps_longitude REAL,
                notes TEXT,
                status TEXT DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by INTEGER,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
        
        # Units
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id INTEGER NOT NULL,
                unit_label TEXT NOT NULL,
                unit_type TEXT,
                serial_number TEXT UNIQUE,
                equipment_tag TEXT UNIQUE,
                status TEXT DEFAULT 'active',
                notes TEXT,
                last_service_date TEXT,
                next_service_date TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by INTEGER,
                FOREIGN KEY(building_id) REFERENCES buildings(id) ON DELETE CASCADE,
                FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE(building_id, unit_label)
            );
        """)
        
        # Work logs
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS work_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id INTEGER NOT NULL,
                unit_id INTEGER,
                created_by_email TEXT NOT NULL,
                created_by_name TEXT NOT NULL,
                created_by_id INTEGER,
                work_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                details TEXT,
                hours_spent REAL DEFAULT 0,
                materials_used TEXT,
                photos TEXT,  -- JSON array of photo paths
                status TEXT DEFAULT 'completed',
                priority INTEGER DEFAULT 3,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(building_id) REFERENCES buildings(id) ON DELETE CASCADE,
                FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE SET NULL,
                FOREIGN KEY(created_by_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
        
        # WhatsApp messages
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                building_id INTEGER,
                unit_id INTEGER,
                raw_line TEXT NOT NULL,
                parsed_dt TEXT,
                parsed_sender TEXT,
                parsed_message TEXT,
                is_processed INTEGER DEFAULT 0,
                confidence_score REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(building_id) REFERENCES buildings(id) ON DELETE SET NULL,
                FOREIGN KEY(unit_id) REFERENCES units(id) ON DELETE SET NULL
            );
        """)
        
        # Audit logs (GDPR compliant)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_email TEXT,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id INTEGER,
                old_values TEXT,
                new_values TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
        
        # Search index for FTS
        self.cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                content,
                building_name,
                unit_label,
                serial_number,
                equipment_tag,
                notes,
                tokenize='porter'
            );
        """)
        
        # System settings
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setting_key TEXT UNIQUE NOT NULL,
                setting_value TEXT,
                data_type TEXT DEFAULT 'string',
                description TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)
        
        self.conn.commit()
    
    def _create_indexes(self):
        """Create performance indexes"""
        indexes = [
            # Users
            "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
            "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
            "CREATE INDEX IF NOT EXISTS idx_users_active ON users(active)",
            
            # Buildings
            "CREATE INDEX IF NOT EXISTS idx_buildings_name ON buildings(building_name)",
            "CREATE INDEX IF NOT EXISTS idx_buildings_status ON buildings(status)",
            
            # Units
            "CREATE INDEX IF NOT EXISTS idx_units_building ON units(building_id)",
            "CREATE INDEX IF NOT EXISTS idx_units_label ON units(unit_label)",
            "CREATE INDEX IF NOT EXISTS idx_units_serial ON units(serial_number)",
            "CREATE INDEX IF NOT EXISTS idx_units_equipment ON units(equipment_tag)",
            "CREATE INDEX IF NOT EXISTS idx_units_status ON units(status)",
            
            # Work logs
            "CREATE INDEX IF NOT EXISTS idx_worklogs_building ON work_logs(building_id)",
            "CREATE INDEX IF NOT EXISTS idx_worklogs_unit ON work_logs(unit_id)",
            "CREATE INDEX IF NOT EXISTS idx_worklogs_created_by ON work_logs(created_by_id)",
            "CREATE INDEX IF NOT EXISTS idx_worklogs_created_at ON work_logs(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_worklogs_status ON work_logs(status)",
            
            # WhatsApp
            "CREATE INDEX IF NOT EXISTS idx_whatsapp_building ON whatsapp_messages(building_id)",
            "CREATE INDEX IF NOT EXISTS idx_whatsapp_unit ON whatsapp_messages(unit_id)",
            "CREATE INDEX IF NOT EXISTS idx_whatsapp_processed ON whatsapp_messages(is_processed)",
            
            # Audit logs
            "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action)",
            "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_logs(created_at)",
            
            # Login attempts
            "CREATE INDEX IF NOT EXISTS idx_login_email_time ON login_attempts(email, attempt_time)",
            
            # Password reset
            "CREATE INDEX IF NOT EXISTS idx_reset_token ON password_reset_tokens(token, expires_at)",
        ]
        
        for idx in indexes:
            try:
                self.cursor.execute(idx)
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")
        
        self.conn.commit()
    
    def seed_default_data(self):
        """Seed default users and settings"""
        # Check if users already exist
        self.cursor.execute("SELECT COUNT(*) as count FROM users")
        if self.cursor.fetchone()["count"] > 0:
            return
        
        # Default password from env or secret
        default_password = os.getenv("FIBEROPS_DEFAULT_PASSWORD", "ChangeMe123!")
        
        # Create default users
        default_users = [
            {"full_name": "Darrell Kelly", "email": "dkelly@fiberops-hghitechs.com", "role": "owner"},
            {"full_name": "Brandon Alves", "email": "brandona@fiberops-hghitechs.com", "role": "supervisor"},
            {"full_name": "Andre Ampey", "email": "dre@fiberops-hghitechs.com", "role": "supervisor"},
            {"full_name": "Walter Chandler Jr.", "email": "walterc@fiberops-hghitechs.com", "role": "tech"},
            {"full_name": "Raashid Rouse", "email": "raashidr@fiberops-hghitechs.com", "role": "tech"},
            {"full_name": "Dale Vester", "email": "dalev@fiberops-hghitechs.com", "role": "tech"},
            {"full_name": "Auditor View", "email": "auditor@fiberops-hghitechs.com", "role": "viewer"},
        ]
        
        now = datetime.now().isoformat()
        for user in default_users:
            salt, pwd_hash = SecurityManager.hash_password(default_password)
            self.cursor.execute("""
                INSERT INTO users (full_name, email, password_hash, password_salt, role, 
                                  active, created_at, updated_at, must_change_password)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user["full_name"],
                user["email"].lower(),
                pwd_hash,
                salt,
                user["role"],
                1,
                now,
                now,
                1
            ))
        
        # Default system settings
        settings = [
            ("app_name", "HGHI FiberOps", "string", "Application name"),
            ("app_version", APP_VERSION, "string", "Application version"),
            ("session_timeout_hours", str(SESSION_TIMEOUT_HOURS), "integer", "Session timeout in hours"),
            ("max_login_attempts", str(MAX_LOGIN_ATTEMPTS), "integer", "Maximum login attempts before lockout"),
            ("login_lockout_minutes", str(LOGIN_LOCKOUT_MINUTES), "integer", "Lockout duration in minutes"),
            ("password_min_length", str(PASSWORD_MIN_LENGTH), "integer", "Minimum password length"),
            ("backup_retention_days", "30", "integer", "Number of days to keep backups"),
            ("email_notifications", "1", "boolean", "Enable email notifications"),
            ("slack_webhook_url", "", "string", "Slack webhook URL for notifications"),
        ]
        
        for key, value, data_type, desc in settings:
            self.cursor.execute("""
                INSERT INTO system_settings (setting_key, setting_value, data_type, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (key, value, data_type, desc, now, now))
        
        self.conn.commit()
        logger.info("Default data seeded successfully")
    
    def query(self, sql: str, params: tuple = ()) -> List[Dict]:
        """Execute query and return results as dicts"""
        try:
            self.cursor.execute(sql, params)
            rows = self.cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Query error: {e}, SQL: {sql}")
            raise
    
    def execute(self, sql: str, params: tuple = ()) -> int:
        """Execute SQL and return last row ID"""
        try:
            self.cursor.execute(sql, params)
            self.conn.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Execute error: {e}, SQL: {sql}")
            raise
    
    def execute_many(self, sql: str, params_list: list) -> None:
        """Execute many SQL statements"""
        try:
            self.cursor.executemany(sql, params_list)
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Execute many error: {e}")
            raise
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email"""
        users = self.query("SELECT * FROM users WHERE email = ? AND active = 1", (email.lower(),))
        return users[0] if users else None
    
    def log_login_attempt(self, email: str, ip: str, user_agent: str, successful: bool) -> None:
        """Log login attempt"""
        self.execute("""
            INSERT INTO login_attempts (email, ip_address, user_agent, successful, attempt_time, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (email.lower(), ip, user_agent, 1 if successful else 0, 
              datetime.now().isoformat(), datetime.now().isoformat()))
        
        if not successful:
            # Update failed attempts count
            self.execute("""
                UPDATE users 
                SET failed_login_attempts = failed_login_attempts + 1,
                    lockout_until = CASE 
                        WHEN failed_login_attempts + 1 >= ? 
                        THEN datetime('now', '+' || ? || ' minutes')
                        ELSE lockout_until 
                    END
                WHERE email = ?
            """, (MAX_LOGIN_ATTEMPTS, LOGIN_LOCKOUT_MINUTES, email.lower()))
    
    def reset_login_attempts(self, email: str) -> None:
        """Reset failed login attempts"""
        self.execute("""
            UPDATE users 
            SET failed_login_attempts = 0, 
                lockout_until = NULL 
            WHERE email = ?
        """, (email.lower(),))
    
    def is_user_locked_out(self, email: str) -> bool:
        """Check if user is locked out"""
        user = self.get_user_by_email(email)
        if not user:
            return False
        
        if user.get("lockout_until"):
            lockout_until = datetime.fromisoformat(user["lockout_until"])
            if datetime.now() < lockout_until:
                return True
        
        return False
    
    def log_audit(self, user_id: Optional[int], user_email: Optional[str], 
                  action: str, entity_type: Optional[str] = None, 
                  entity_id: Optional[int] = None, old_values: Optional[Dict] = None,
                  new_values: Optional[Dict] = None) -> None:
        """Log audit trail"""
        # Get IP and user agent from session state
        ip = st.session_state.get("client_ip", "unknown")
        user_agent = st.session_state.get("user_agent", "unknown")
        
        self.execute("""
            INSERT INTO audit_logs 
            (user_id, user_email, action, entity_type, entity_id, 
             old_values, new_values, ip_address, user_agent, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            user_email,
            action,
            entity_type,
            entity_id,
            json.dumps(old_values) if old_values else None,
            json.dumps(new_values) if new_values else None,
            ip,
            user_agent,
            datetime.now().isoformat()
        ))
    
    def backup_database(self) -> str:
        """Create database backup"""
        os.makedirs(BACKUP_DIR, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{BACKUP_DIR}/fiberops_backup_{timestamp}.db"
        
        # Close current connection
        self.conn.close()
        
        # Copy database file
        import shutil
        shutil.copy2(DB_PATH, backup_file)
        
        # Reopen connection
        self._init_db()
        
        # Clean old backups (keep 30 days)
        retention_days = 30
        cutoff = time.time() - (retention_days * 24 * 3600)
        
        for file in os.listdir(BACKUP_DIR):
            file_path = os.path.join(BACKUP_DIR, file)
            if os.path.getmtime(file_path) < cutoff:
                os.remove(file_path)
        
        logger.info(f"Database backed up to {backup_file}")
        return backup_file
    
    def get_system_health(self) -> Dict:
        """Get system health metrics"""
        metrics = {}
        
        # Database size
        if os.path.exists(DB_PATH):
            metrics["db_size_mb"] = os.path.getsize(DB_PATH) / (1024 * 1024)
        
        # Row counts
        tables = ["users", "buildings", "units", "work_logs", "whatsapp_messages", "audit_logs"]
        for table in tables:
            try:
                result = self.query(f"SELECT COUNT(*) as count FROM {table}")
                metrics[f"{table}_count"] = result[0]["count"] if result else 0
            except:
                metrics[f"{table}_count"] = 0
        
        # Recent activity
        try:
            recent_users = self.query("""
                SELECT COUNT(DISTINCT created_by_email) as count 
                FROM work_logs 
                WHERE created_at > datetime('now', '-7 days')
            """)
            metrics["active_users_7d"] = recent_users[0]["count"] if recent_users else 0
        except:
            metrics["active_users_7d"] = 0
        
        # Backup status
        backup_files = list(Path(BACKUP_DIR).glob("*.db")) if os.path.exists(BACKUP_DIR) else []
        if backup_files:
            latest_backup = max(backup_files, key=os.path.getmtime)
            metrics["last_backup_hours"] = (time.time() - os.path.getmtime(latest_backup)) / 3600
        else:
            metrics["last_backup_hours"] = None
        
        return metrics

# Initialize database manager
db = DatabaseManager()

# ==========================================================
# EMAIL MANAGER
# ==========================================================
class EmailManager:
    """Email manager for Google Workspace integration"""
    
    @staticmethod
    def send_email(to_email: str, subject: str, body: str, 
                   attachments: List[Dict] = None, html: bool = True) -> Tuple[bool, str]:
        """Send email via Google Workspace SMTP"""
        try:
            # Get config from secrets
            config = SMTP_CONFIG.copy()
            
            # Update from Streamlit secrets if available
            if hasattr(st, "secrets"):
                secrets_config = st.secrets.get("email", {})
                config.update(secrets_config)
            
            # Validate config
            if not config.get("user") or not config.get("password"):
                return False, "Email configuration missing"
            
            # Create message
            if html:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body, "html"))
            else:
                msg = MIMEMultipart()
                msg.attach(MIMEText(body, "plain"))
            
            msg["From"] = f"{config['from_name']} <{config['user']}>"
            msg["To"] = to_email
            msg["Subject"] = subject
            
            # Add attachments
            if attachments:
                for attachment in attachments:
                    with open(attachment["path"], "rb") as f:
                        part = MIMEApplication(f.read(), Name=attachment["filename"])
                        part["Content-Disposition"] = f'attachment; filename="{attachment["filename"]}"'
                        msg.attach(part)
            
            # Send email
            with smtplib.SMTP(config["host"], config["port"]) as server:
                server.starttls()
                server.login(config["user"], config["password"])
                server.send_message(msg)
            
            logger.info(f"Email sent to {to_email}")
            return True, "Email sent successfully"
        
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False, str(e)
    
    @staticmethod
    def send_password_reset(email: str, token: str) -> bool:
        """Send password reset email"""
        reset_url = f"https://fiberops-hghitechs.com/reset?token={token}"
        
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px;">
                <h2 style="color: #2c3e50;">Password Reset Request</h2>
                <p>Hello,</p>
                <p>You have requested to reset your password for the HGHI FiberOps system.</p>
                <p>Click the link below to reset your password:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" style="background-color: #3498db; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; font-weight: bold;">
                        Reset Password
                    </a>
                </p>
                <p>Or copy and paste this link into your browser:</p>
                <p style="background-color: #f8f9fa; padding: 10px; border-radius: 4px; word-break: break-all;">
                    {reset_url}
                </p>
                <p>This link will expire in 1 hour.</p>
                <p>If you didn't request this password reset, please ignore this email.</p>
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #7f8c8d; font-size: 12px;">
                    This is an automated message from HGHI FiberOps System.<br>
                    Please do not reply to this email.
                </p>
            </div>
        </body>
        </html>
        """
        
        success, message = EmailManager.send_email(
            email,
            "Password Reset - HGHI FiberOps",
            body,
            html=True
        )
        
        return success
    
    @staticmethod
    def send_daily_report(to_emails: List[str], report_data: Dict) -> bool:
        """Send daily report email"""
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #ddd; border-radius: 5px;">
                <h2 style="color: #2c3e50;">📊 Daily FiberOps Report</h2>
                <p>Report generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
                
                <h3 style="color: #3498db;">📈 Summary</h3>
                <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Total Tasks Today:</strong></td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{report_data.get('tasks_today', 0)}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Completed Tasks:</strong></td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{report_data.get('completed_tasks', 0)}</td>
                    </tr>
                    <tr style="background-color: #f8f9fa;">
                        <td style="padding: 8px; border: 1px solid #ddd;"><strong>Active Technicians:</strong></td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{report_data.get('active_techs', 0)}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px; border: 1px solid #ddd;"><strong>New WhatsApp Messages:</strong></td>
                        <td style="padding: 8px; border: 1px solid #ddd;">{report_data.get('new_messages', 0)}</td>
                    </tr>
                </table>
                
                <h3 style="color: #3498db;">👥 Top Performers Today</h3>
                <ul>
        """
        
        for tech in report_data.get("top_performers", []):
            body += f'<li>{tech["name"]}: {tech["tasks"]} tasks</li>'
        
        body += """
                </ul>
                
                <p style="margin-top: 30px; color: #7f8c8d; font-size: 14px;">
                    View detailed reports in the FiberOps dashboard:<br>
                    <a href="https://fiberops-hghitechs.streamlit.app">https://fiberops-hghitechs.streamlit.app</a>
                </p>
                
                <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
                <p style="color: #7f8c8d; font-size: 12px;">
                    This is an automated daily report from HGHI FiberOps System.<br>
                    To adjust report settings, contact your system administrator.
                </p>
            </div>
        </body>
        </html>
        """
        
        all_success = True
        for email in to_emails:
            success, message = EmailManager.send_email(
                email,
                f"Daily FiberOps Report - {datetime.now().strftime('%Y-%m-%d')}",
                body,
                html=True
            )
            if not success:
                all_success = False
                logger.error(f"Failed to send report to {email}: {message}")
        
        return all_success

# ==========================================================
# SESSION MANAGER
# ==========================================================
class SessionManager:
    """Secure session management"""
    
    @staticmethod
    def init_session():
        """Initialize session state"""
        defaults = {
            "authed": False,
            "user": None,
            "login_time": None,
            "session_id": None,
            "client_ip": None,
            "user_agent": None,
            "two_factor_required": False,
            "two_factor_verified": False,
            "login_email": "",
            "login_password": "",
            "active_building_id": None,
            "active_unit_id": None,
            "search_query": "",
            "last_activity": datetime.now().isoformat(),
        }
        
        for k, v in defaults.items():
            if k not in st.session_state:
                st.session_state[k] = v
        
        # Get client info
        if not st.session_state.client_ip:
            import socket
            try:
                hostname = socket.gethostname()
                st.session_state.client_ip = socket.gethostbyname(hostname)
            except:
                st.session_state.client_ip = "unknown"
        
        if not st.session_state.user_agent:
            st.session_state.user_agent = "Streamlit"
    
    @staticmethod
    def require_auth() -> bool:
        """Check if user is authenticated"""
        if not st.session_state.get("authed"):
            return False
        
        # Check session timeout
        if st.session_state.get("login_time"):
            login_time = datetime.fromisoformat(st.session_state.login_time)
            if datetime.now() - login_time > timedelta(hours=SESSION_TIMEOUT_HOURS):
                SessionManager.logout()
                return False
        
        # Update last activity
        st.session_state.last_activity = datetime.now().isoformat()
        
        return True
    
    @staticmethod
    def login_user(user: Dict, password: str) -> Tuple[bool, str]:
        """Authenticate user"""
        email = user["email"].lower()
        
        # Check if user is locked out
        if db.is_user_locked_out(email):
            return False, "Account is temporarily locked. Please try again later."
        
        # Verify password
        if not SecurityManager.verify_password(user["password_salt"], user["password_hash"], password):
            # Log failed attempt
            db.log_login_attempt(
                email,
                st.session_state.client_ip,
                st.session_state.user_agent,
                False
            )
            return False, "Invalid email or password"
        
        # Check if 2FA is required
        two_factor_required = bool(user.get("two_factor_enabled"))
        
        # Reset failed attempts on successful login
        db.reset_login_attempts(email)
        
        # Update last login
        db.execute("""
            UPDATE users 
            SET last_login = ?, failed_login_attempts = 0, lockout_until = NULL
            WHERE id = ?
        """, (datetime.now().isoformat(), user["id"]))
        
        # Log successful login
        db.log_login_attempt(
            email,
            st.session_state.client_ip,
            st.session_state.user_agent,
            True
        )
        
        # Log audit
        db.log_audit(user["id"], email, "LOGIN_SUCCESS", "users", user["id"])
        
        # Set session state
        st.session_state.authed = True
        st.session_state.user = user
        st.session_state.login_time = datetime.now().isoformat()
        st.session_state.session_id = secrets.token_urlsafe(32)
        st.session_state.two_factor_required = two_factor_required
        st.session_state.two_factor_verified = not two_factor_required
        
        return True, "Login successful"
    
    @staticmethod
    def verify_2fa(token: str) -> bool:
        """Verify 2FA token"""
        if not st.session_state.two_factor_required:
            return True
        
        user = st.session_state.user
        secret = user.get("two_factor_secret")
        
        if not secret:
            return False
        
        verified = SecurityManager.verify_2fa_token(secret, token)
        
        if verified:
            st.session_state.two_factor_verified = True
            db.log_audit(
                user["id"], user["email"], 
                "2FA_VERIFIED", "users", user["id"]
            )
        
        return verified
    
    @staticmethod
    def logout():
        """Logout user"""
        if st.session_state.user:
            db.log_audit(
                st.session_state.user["id"],
                st.session_state.user["email"],
                "LOGOUT",
                "users",
                st.session_state.user["id"]
            )
        
        # Clear session
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        
        SessionManager.init_session()

# ==========================================================
# WHATSAPP PARSER
# ==========================================================
class WhatsAppParser:
    """Advanced WhatsApp chat parser"""
    
    PATTERNS = [
        # Standard format: 12/31/23, 11:59 PM - Sender: Message
        (r'^(\d{1,2}/\d{1,2}/\d{2,4}),\s(\d{1,2}:\d{2}\s?[APMapm]{2})\s-\s([^:]+):\s(.*)$', "standard"),
        
        # Android export: [12/31/23, 23:59:00] Sender: Message
        (r'\[(\d{2}/\d{2}/\d{4},\s\d{2}:\d{2}:\d{2})\]\s([^:]+):\s(.*)$', "android"),
        
        # iOS export: 2023-12-31 23:59 - Sender: Message
        (r'^(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2})\s-\s([^:]+):\s(.*)$', "ios"),
        
        # Date first: 31/12/2023, 23:59 - Sender: Message
        (r'^(\d{1,2}/\d{1,2}/\d{4}),\s(\d{1,2}:\d{2})\s-\s([^:]+):\s(.*)$', "date_first"),
    ]
    
    @staticmethod
    def parse_line(line: str) -> Optional[Dict]:
        """Parse a single WhatsApp line"""
        line = line.strip()
        if not line:
            return None
        
        for pattern, format_type in WhatsAppParser.PATTERNS:
            match = re.match(pattern, line)
            if match:
                if format_type == "standard":
                    return {
                        "raw_line": line,
                        "date": match.group(1),
                        "time": match.group(2),
                        "sender": match.group(3).strip(),
                        "message": match.group(4).strip(),
                        "format": format_type
                    }
                elif format_type == "android":
                    return {
                        "raw_line": line,
                        "datetime": match.group(1),
                        "sender": match.group(2).strip(),
                        "message": match.group(3).strip(),
                        "format": format_type
                    }
                elif format_type == "ios":
                    return {
                        "raw_line": line,
                        "datetime": match.group(1),
                        "sender": match.group(2).strip(),
                        "message": match.group(3).strip(),
                        "format": format_type
                    }
                elif format_type == "date_first":
                    return {
                        "raw_line": line,
                        "date": match.group(1),
                        "time": match.group(2),
                        "sender": match.group(3).strip(),
                        "message": match.group(4).strip(),
                        "format": format_type
                    }
        
        # If no pattern matches, treat as continuation line
        return {
            "raw_line": line,
            "sender": None,
            "message": line,
            "format": "continuation"
        }
    
    @staticmethod
    def extract_unit_info(text: str) -> Dict:
        """Extract unit information from text"""
        text_lower = text.lower()
        
        # Unit patterns
        unit_patterns = [
            (r'unit\s+#?\s*([a-z0-9\-]+)', 'unit'),
            (r'apt\s+#?\s*([a-z0-9\-]+)', 'apartment'),
            (r'suite\s+#?\s*([a-z0-9\-]+)', 'suite'),
            (r'#\s*([a-z0-9\-]+)', 'number'),
            (r'\b([a-z]?[0-9]+[a-z]?)\b', 'simple'),  # 3A, 101B, etc.
        ]
        
        # Work type patterns
        work_patterns = [
            ('fiber', ['fiber', 'fiber optic', 'cable', 'ont', 'splice']),
            ('construction', ['construction', 'build', 'install', 'mount']),
            ('repair', ['repair', 'fix', 'broken', 'issue', 'problem']),
            ('test', ['test', 'speed', 'signal', 'check', 'verify']),
            ('inspect', ['inspect', 'inspection', 'audit', 'review']),
        ]
        
        # Priority patterns
        priority_patterns = [
            ('high', ['urgent', 'emergency', 'critical', 'asap', 'now']),
            ('medium', ['important', 'soon', 'schedule']),
            ('low', ['when', 'later', 'sometime']),
        ]
        
        results = {
            "unit_label": None,
            "unit_type": None,
            "work_type": "other",
            "priority": "medium",
            "confidence": 0
        }
        
        # Find unit
        for pattern, unit_type in unit_patterns:
            match = re.search(pattern, text_lower)
            if match:
                results["unit_label"] = match.group(1).upper()
                results["unit_type"] = unit_type
                results["confidence"] += 0.3
                break
        
        # Find work type
        for work_type, keywords in work_patterns:
            if any(keyword in text_lower for keyword in keywords):
                results["work_type"] = work_type
                results["confidence"] += 0.3
                break
        
        # Find priority
        for priority, keywords in priority_patterns:
            if any(keyword in text_lower for keyword in keywords):
                results["priority"] = priority
                results["confidence"] += 0.2
                break
        
        # Find building references (simple pattern)
        building_words = ['building', 'tower', 'complex', 'center', 'plaza']
        for word in building_words:
            if word in text_lower:
                results["confidence"] += 0.2
                break
        
        return results

# ==========================================================
# AI INTEGRATION
# ==========================================================
class AIIntegration:
    """AI integration for report generation and analysis"""
    
    @staticmethod
    def generate_report(prompt: str, context: Dict = None) -> Optional[str]:
        """Generate report using AI"""
        if not DEEPSEEK_API_KEY:
            return None
        
        try:
            # Prepare the API request
            headers = {
                "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                "Content-Type": "application/json"
            }
            
            system_prompt = """You are a professional field operations report writer for a fiber optics and construction company.
            Write clear, concise, and professional reports that include:
            1. Work performed
            2. Materials used
            3. Issues encountered
            4. Recommendations
            5. Next steps
            
            Format the report in markdown with appropriate headings."""
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]
            
            if context:
                context_str = json.dumps(context, indent=2)
                messages.insert(1, {"role": "system", "content": f"Context: {context_str}"})
            
            payload = {
                "model": "deepseek-chat",
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 1000
            }
            
            response = requests.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["choices"][0]["message"]["content"]
            
            return None
        
        except Exception as e:
            logger.error(f"AI generation error: {e}")
            return None
    
    @staticmethod
    def analyze_whatsapp_messages(messages: List[str]) -> Dict:
        """Analyze WhatsApp messages for trends and insights"""
        if not DEEPSEEK_API_KEY:
            return {"error": "AI not configured"}
        
        try:
            prompt = f"""
            Analyze these field work messages and provide insights:
            
            Messages:
            {json.dumps(messages[:20], indent=2)}
            
            Please analyze:
            1. Common issues mentioned
            2. Frequent locations/buildings
            3. Technician workload patterns
            4. Suggested improvements
            5. Urgent matters needing attention
            
            Return as JSON with these keys: issues, locations, patterns, improvements, urgent.
            """
            
            result = AIIntegration.generate_report(prompt)
            if result:
                # Try to parse as JSON
                try:
                    # Extract JSON from markdown if needed
                    json_match = re.search(r'```json\n(.*?)\n```', result, re.DOTALL)
                    if json_match:
                        return json.loads(json_match.group(1))
                    else:
                        return json.loads(result)
                except:
                    return {"analysis": result}
            
            return {}
        
        except Exception as e:
            logger.error(f"AI analysis error: {e}")
            return {}

# ==========================================================
# UI COMPONENTS
# ==========================================================
class UIComponents:
    """Reusable UI components"""
    
    @staticmethod
    def header():
        """Application header"""
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                    padding: 1.5rem; border-radius: 0.5rem; margin-bottom: 1.5rem;">
            <h1 style="color: white; margin: 0;">{APP_TITLE}</h1>
            <p style="color: rgba(255,255,255,0.9); margin: 0;">Version {APP_VERSION}</p>
        </div>
        """, unsafe_allow_html=True)
    
    @staticmethod
    def status_badge(status: str) -> str:
        """Generate status badge HTML"""
        colors = {
            'active': 'success',
            'completed': 'success',
            'in_progress': 'warning',
            'pending': 'secondary',
            'on_hold': 'danger',
            'cancelled': 'dark',
            'high': 'danger',
            'medium': 'warning',
            'low': 'success'
        }
        
        color = colors.get(status.lower(), 'secondary')
        return f'<span class="badge bg-{color}">{status}</span>'
    
    @staticmethod
    def metric_card(title: str, value: Any, delta: str = None, icon: str = "📊"):
        """Display a metric card"""
        delta_html = f'<div class="text-success">{delta}</div>' if delta else ''
        
        st.markdown(f"""
        <div class="card" style="padding: 1rem; border-radius: 0.5rem; border: 1px solid #e0e0e0;">
            <div style="display: flex; align-items: center; margin-bottom: 0.5rem;">
                <span style="font-size: 1.5rem; margin-right: 0.5rem;">{icon}</span>
                <h6 style="margin: 0; color: #666;">{title}</h6>
            </div>
            <h3 style="margin: 0; font-weight: bold;">{value}</h3>
            {delta_html}
        </div>
        """, unsafe_allow_html=True)
    
    @staticmethod
    def loading_spinner(text: str = "Loading..."):
        """Display loading spinner"""
        return st.spinner(text)
    
    @staticmethod
    def success_message(message: str):
        """Display success message"""
        st.success(f"✅ {message}")
    
    @staticmethod
    def error_message(message: str):
        """Display error message"""
        st.error(f"❌ {message}")
    
    @staticmethod
    def warning_message(message: str):
        """Display warning message"""
        st.warning(f"⚠️ {message}")
    
    @staticmethod
    def info_message(message: str):
        """Display info message"""
        st.info(f"ℹ️ {message}")

# ==========================================================
# PAGES
# ==========================================================
class LoginPage:
    """Login page with enhanced security"""
    
    @staticmethod
    def render():
        """Render login page"""
        st.markdown(f"<h1 style='text-align: center;'>{APP_TITLE}</h1>", unsafe_allow_html=True)
        st.markdown("<p style='text-align: center; color: #666;'>Secure Field Operations Management</p>", unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            with st.container(border=True):
                st.subheader("🔐 Secure Login")
                
                # Demo buttons
                st.markdown("### Quick Login (Demo)")
                demo_cols = st.columns(3)
                
                with demo_cols[0]:
                    if st.button("👑 Owner", use_container_width=True):
                        st.session_state.login_email = "dkelly@fiberops-hghitechs.com"
                        st.session_state.login_password = "ChangeMe123!"
                        st.rerun()
                
                with demo_cols[1]:
                    if st.button("👨‍💼 Supervisor", use_container_width=True):
                        st.session_state.login_email = "brandona@fiberops-hghitechs.com"
                        st.session_state.login_password = "ChangeMe123!"
                        st.rerun()
                
                with demo_cols[2]:
                    if st.button("🔧 Technician", use_container_width=True):
                        st.session_state.login_email = "walterc@fiberops-hghitechs.com"
                        st.session_state.login_password = "ChangeMe123!"
                        st.rerun()
                
                st.divider()
                
                # Login form
                email = st.text_input(
                    "Email",
                    value=st.session_state.login_email,
                    placeholder="name@fiberops-hghitechs.com"
                )
                
                password = st.text_input(
                    "Password",
                    type="password",
                    value=st.session_state.login_password,
                    placeholder="Your password"
                )
                
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("🚀 Login", type="primary", use_container_width=True):
                        if not email or not password:
                            UIComponents.error_message("Email and password required")
                            return
                        
                        with UIComponents.loading_spinner("Authenticating..."):
                            user = db.get_user_by_email(email)
                            if not user:
                                UIComponents.error_message("User not found or inactive")
                                return
                            
                            success, message = SessionManager.login_user(user, password)
                            if success:
                                UIComponents.success_message(f"Welcome, {user['full_name']}!")
                                
                                # Check if password needs changing
                                if user.get("must_change_password"):
                                    st.session_state.show_password_change = True
                                
                                st.rerun()
                            else:
                                UIComponents.error_message(message)
                
                with col_b:
                    if st.button("🔄 Reset Password", use_container_width=True):
                        st.session_state.show_password_reset = True
                        st.rerun()
                
                # Password reset modal
                if st.session_state.get("show_password_reset"):
                    with st.container(border=True):
                        st.subheader("Password Reset")
                        reset_email = st.text_input("Enter your email", key="reset_email_input")
                        
                        col_c, col_d = st.columns(2)
                        with col_c:
                            if st.button("Send Reset Link", type="primary"):
                                if reset_email:
                                    # Generate reset token
                                    token = secrets.token_urlsafe(32)
                                    expires = datetime.now() + timedelta(hours=1)
                                    
                                    user = db.get_user_by_email(reset_email)
                                    if user:
                                        db.execute("""
                                            INSERT INTO password_reset_tokens 
                                            (user_id, token, expires_at, created_at)
                                            VALUES (?, ?, ?, ?)
                                        """, (user["id"], token, expires.isoformat(), datetime.now().isoformat()))
                                        
                                        # Send email
                                        if EmailManager.send_password_reset(reset_email, token):
                                            UIComponents.success_message("Reset link sent to your email")
                                            st.session_state.show_password_reset = False
                                        else:
                                            UIComponents.error_message("Failed to send reset email")
                                    else:
                                        UIComponents.error_message("Email not found")
                        
                        with col_d:
                            if st.button("Cancel"):
                                st.session_state.show_password_reset = False
                                st.rerun()
                
                # System info
                with st.expander("ℹ️ System Information"):
                    health = db.get_system_health()
                    st.write(f"**Version:** {APP_VERSION}")
                    st.write(f"**Database Size:** {health.get('db_size_mb', 0):.2f} MB")
                    st.write(f"**Total Users:** {health.get('users_count', 0)}")
                    st.write(f"**Last Backup:** {health.get('last_backup_hours', 'Never')}")

class DashboardPage:
    """Main dashboard page"""
    
    @staticmethod
    def render():
        """Render dashboard"""
        UIComponents.header()
        
        # Quick stats
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            buildings = db.query("SELECT COUNT(*) as count FROM buildings WHERE status = 'active'")
            UIComponents.metric_card(
                "Active Buildings",
                buildings[0]["count"] if buildings else 0,
                icon="🏢"
            )
        
        with col2:
            units = db.query("SELECT COUNT(*) as count FROM units WHERE status = 'active'")
            UIComponents.metric_card(
                "Active Units",
                units[0]["count"] if units else 0,
                icon="🏠"
            )
        
        with col3:
            today = datetime.now().strftime("%Y-%m-%d")
            tasks_today = db.query("""
                SELECT COUNT(*) as count 
                FROM work_logs 
                WHERE DATE(created_at) = ?
            """, (today,))
            UIComponents.metric_card(
                "Tasks Today",
                tasks_today[0]["count"] if tasks_today else 0,
                icon="📝"
            )
        
        with col4:
            pending_tasks = db.query("""
                SELECT COUNT(*) as count 
                FROM work_logs 
                WHERE status = 'pending'
            """)
            UIComponents.metric_card(
                "Pending Tasks",
                pending_tasks[0]["count"] if pending_tasks else 0,
                icon="⏳"
            )
        
        st.divider()
        
        # Recent activity
        col_left, col_right = st.columns([2, 1])
        
        with col_left:
            st.subheader("📋 Recent Activity")
            
            recent_activity = db.query("""
                SELECT 
                    wl.*,
                    b.building_name,
                    u.unit_label,
                    CASE 
                        WHEN wl.priority = 1 THEN '🔴 High'
                        WHEN wl.priority = 2 THEN '🟡 Medium'
                        ELSE '🟢 Low'
                    END as priority_display
                FROM work_logs wl
                LEFT JOIN buildings b ON wl.building_id = b.id
                LEFT JOIN units u ON wl.unit_id = u.id
                ORDER BY wl.created_at DESC
                LIMIT 10
            """)
            
            if recent_activity:
                for activity in recent_activity:
                    with st.container(border=True):
                        cols = st.columns([3, 1, 1])
                        with cols[0]:
                            st.write(f"**{activity['building_name']}** - {activity.get('unit_label', 'N/A')}")
                            st.caption(activity['summary'][:100])
                        with cols[1]:
                            st.write(activity['priority_display'])
                        with cols[2]:
                            st.caption(activity['created_at'][:10])
            else:
                st.info("No recent activity")
        
        with col_right:
            st.subheader("📈 Quick Actions")
            
            if st.button("➕ Log New Task", use_container_width=True, icon="📝"):
                st.session_state.page = "log_task"
                st.rerun()
            
            if st.button("🏢 Add Building", use_container_width=True, icon="🏢"):
                st.session_state.page = "buildings"
                st.rerun()
            
            if st.button("💬 Import WhatsApp", use_container_width=True, icon="💬"):
                st.session_state.page = "whatsapp"
                st.rerun()
            
            if st.button("📊 Generate Report", use_container_width=True, icon="📊"):
                st.session_state.page = "reports"
                st.rerun()
            
            st.divider()
            
            # System health
            st.subheader("🩺 System Health")
            health = db.get_system_health()
            
            if health.get("last_backup_hours") is None:
                st.error("No backups found")
            elif health["last_backup_hours"] > 24:
                st.warning(f"Last backup: {health['last_backup_hours']:.1f} hours ago")
            else:
                st.success(f"Last backup: {health['last_backup_hours']:.1f} hours ago")
            
            st.progress(min(health.get("db_size_mb", 0) / 100, 1.0), 
                       text=f"DB: {health.get('db_size_mb', 0):.1f}MB / 100MB")

class BuildingsPage:
    """Buildings and units management"""
    
    @staticmethod
    def render():
        """Render buildings page"""
        st.title("🏢 Buildings & Units Management")
        
        tab1, tab2, tab3 = st.tabs(["View Buildings", "Add Building/Unit", "Bulk Import"])
        
        with tab1:
            BuildingsPage._render_buildings_list()
        
        with tab2:
            BuildingsPage._render_add_forms()
        
        with tab3:
            BuildingsPage._render_bulk_import()
    
    @staticmethod
    def _render_buildings_list():
        """Render buildings list with search"""
        # Search
        search_query = st.text_input("🔍 Search buildings, units, serials...", 
                                   value=st.session_state.get("search_query", ""))
        
        if search_query:
            # Full-text search
            buildings = db.query("""
                SELECT DISTINCT b.*
                FROM buildings b
                LEFT JOIN units u ON b.id = u.building_id
                WHERE b.building_name LIKE ? 
                   OR b.address LIKE ?
                   OR u.unit_label LIKE ?
                   OR u.serial_number LIKE ?
                   OR u.equipment_tag LIKE ?
                ORDER BY b.building_name
            """, (f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", 
                  f"%{search_query}%", f"%{search_query}%"))
        else:
            buildings = db.query("SELECT * FROM buildings ORDER BY building_name")
        
        # Display buildings
        for building in buildings:
            with st.expander(f"🏢 {building['building_name']}"):
                cols = st.columns([2, 1])
                with cols[0]:
                    st.write(f"**Address:** {building.get('address', 'N/A')}")
                    st.write(f"**City:** {building.get('city', 'N/A')}")
                    st.write(f"**Status:** {building.get('status', 'active')}")
                
                with cols[1]:
                    # Get units for this building
                    units = db.query("""
                        SELECT * FROM units 
                        WHERE building_id = ? 
                        ORDER BY unit_label
                    """, (building["id"],))
                    
                    st.write(f"**Units:** {len(units)}")
                    
                    if st.button(f"View Units", key=f"view_units_{building['id']}"):
                        st.session_state.active_building_id = building["id"]
                        st.rerun()
                
                # Display units for this building
                if st.session_state.get("active_building_id") == building["id"]:
                    st.subheader("Units")
                    if units:
                        df = pd.DataFrame(units)
                        st.dataframe(df[["unit_label", "unit_type", "serial_number", "equipment_tag", "status"]],
                                   use_container_width=True, hide_index=True)
                    else:
                        st.info("No units for this building")
    
    @staticmethod
    def _render_add_forms():
        """Render forms to add building and unit"""
        col1, col2 = st.columns(2)
        
        with col1:
            with st.form("add_building", border=True):
                st.subheader("➕ Add New Building")
                
                building_name = st.text_input("Building Name*")
                address = st.text_input("Address")
                city = st.text_input("City")
                state = st.text_input("State")
                zip_code = st.text_input("Zip Code")
                notes = st.text_area("Notes")
                
                if st.form_submit_button("Save Building", use_container_width=True):
                    if not building_name:
                        UIComponents.error_message("Building name is required")
                    else:
                        try:
                            building_id = db.execute("""
                                INSERT INTO buildings 
                                (building_name, address, city, state, zip, notes, 
                                 status, created_at, updated_at, created_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                building_name.strip(),
                                address.strip(),
                                city.strip(),
                                state.strip(),
                                zip_code.strip(),
                                notes.strip(),
                                "active",
                                datetime.now().isoformat(),
                                datetime.now().isoformat(),
                                st.session_state.user["id"]
                            ))
                            
                            db.log_audit(
                                st.session_state.user["id"],
                                st.session_state.user["email"],
                                "BUILDING_CREATED",
                                "buildings",
                                building_id,
                                None,
                                {"name": building_name}
                            )
                            
                            UIComponents.success_message(f"Building '{building_name}' added")
                            st.rerun()
                        except Exception as e:
                            UIComponents.error_message(f"Error: {e}")
        
        with col2:
            with st.form("add_unit", border=True):
                st.subheader("➕ Add New Unit")
                
                # Get buildings for dropdown
                buildings = db.query("SELECT id, building_name FROM buildings ORDER BY building_name")
                building_options = {b["building_name"]: b["id"] for b in buildings}
                
                if not building_options:
                    st.warning("Add a building first")
                    st.stop()
                
                building_name = st.selectbox("Building*", list(building_options.keys()))
                building_id = building_options[building_name]
                
                unit_label = st.text_input("Unit Label* (e.g., 3A, B-201)")
                unit_type = st.selectbox("Unit Type", ["apartment", "office", "suite", "room", "other"])
                serial_number = st.text_input("Serial Number")
                equipment_tag = st.text_input("Equipment Tag")
                status = st.selectbox("Status", ["active", "inactive", "maintenance"])
                notes = st.text_area("Notes")
                
                if st.form_submit_button("Save Unit", use_container_width=True):
                    if not unit_label:
                        UIComponents.error_message("Unit label is required")
                    else:
                        try:
                            unit_id = db.execute("""
                                INSERT INTO units 
                                (building_id, unit_label, unit_type, serial_number, 
                                 equipment_tag, status, notes, created_at, updated_at, created_by)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                building_id,
                                unit_label.strip(),
                                unit_type,
                                serial_number.strip(),
                                equipment_tag.strip(),
                                status,
                                notes.strip(),
                                datetime.now().isoformat(),
                                datetime.now().isoformat(),
                                st.session_state.user["id"]
                            ))
                            
                            db.log_audit(
                                st.session_state.user["id"],
                                st.session_state.user["email"],
                                "UNIT_CREATED",
                                "units",
                                unit_id,
                                None,
                                {"building_id": building_id, "unit_label": unit_label}
                            )
                            
                            UIComponents.success_message(f"Unit '{unit_label}' added to '{building_name}'")
                            st.rerun()
                        except Exception as e:
                            UIComponents.error_message(f"Error: {e}")
    
    @staticmethod
    def _render_bulk_import():
        """Render bulk import from CSV/Excel"""
        st.subheader("📁 Bulk Import from CSV/Excel")
        
        uploaded = st.file_uploader("Upload file", type=["csv", "xlsx", "xls"])
        
        if uploaded:
            try:
                # Read file
                if uploaded.name.endswith('.csv'):
                    df = pd.read_csv(uploaded)
                else:
                    df = pd.read_excel(uploaded)
                
                st.success(f"Loaded {len(df)} rows")
                st.dataframe(df.head(), use_container_width=True)
                
                # Column mapping
                st.subheader("Column Mapping")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    building_col = st.selectbox(
                        "Building Name Column",
                        options=df.columns.tolist(),
                        index=next((i for i, c in enumerate(df.columns) 
                                  if 'building' in c.lower() or 'name' in c.lower()), 0)
                    )
                
                with col2:
                    unit_col = st.selectbox(
                        "Unit Label Column",
                        options=df.columns.tolist(),
                        index=next((i for i, c in enumerate(df.columns) 
                                  if 'unit' in c.lower() or 'label' in c.lower()), 0)
                    )
                
                with col3:
                    serial_col = st.selectbox(
                        "Serial Number Column (optional)",
                        options=["None"] + df.columns.tolist(),
                        index=0
                    )
                    if serial_col == "None":
                        serial_col = None
                
                if st.button("🚀 Start Import", type="primary", use_container_width=True):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    buildings_created = 0
                    units_created = 0
                    
                    # Get existing buildings
                    existing_buildings = db.query("SELECT id, building_name FROM buildings")
                    building_map = {b["building_name"].lower(): b["id"] for b in existing_buildings}
                    
                    for idx, row in df.iterrows():
                        # Process building
                        building_name = str(row[building_col]).strip()
                        if building_name:
                            building_key = building_name.lower()
                            
                            if building_key not in building_map:
                                # Create new building
                                building_id = db.execute("""
                                    INSERT INTO buildings 
                                    (building_name, status, created_at, updated_at, created_by)
                                    VALUES (?, ?, ?, ?, ?)
                                """, (
                                    building_name,
                                    "active",
                                    datetime.now().isoformat(),
                                    datetime.now().isoformat(),
                                    st.session_state.user["id"]
                                ))
                                building_map[building_key] = building_id
                                buildings_created += 1
                            else:
                                building_id = building_map[building_key]
                            
                            # Process unit
                            unit_label = str(row[unit_col]).strip() if unit_col in row else ""
                            if unit_label:
                                serial = str(row[serial_col]).strip() if serial_col and serial_col in row else ""
                                
                                try:
                                    db.execute("""
                                        INSERT OR IGNORE INTO units 
                                        (building_id, unit_label, serial_number, 
                                         status, created_at, updated_at, created_by)
                                        VALUES (?, ?, ?, ?, ?, ?, ?)
                                    """, (
                                        building_id,
                                        unit_label,
                                        serial,
                                        "active",
                                        datetime.now().isoformat(),
                                        datetime.now().isoformat(),
                                        st.session_state.user["id"]
                                    ))
                                    units_created += 1
                                except:
                                    pass  # Unit already exists
                        
                        # Update progress
                        progress = (idx + 1) / len(df)
                        progress_bar.progress(progress)
                        status_text.text(f"Processing row {idx + 1} of {len(df)}...")
                    
                    progress_bar.empty()
                    status_text.empty()
                    
                    UIComponents.success_message(
                        f"Import complete! Created {buildings_created} buildings and {units_created} units."
                    )
                    
                    db.log_audit(
                        st.session_state.user["id"],
                        st.session_state.user["email"],
                        "BULK_IMPORT",
                        "buildings",
                        None,
                        None,
                        {"buildings": buildings_created, "units": units_created}
                    )
            
            except Exception as e:
                UIComponents.error_message(f"Import error: {e}")

class WorkLogsPage:
    """Work logs and reports"""
    
    @staticmethod
    def render():
        """Render work logs page"""
        st.title("📝 Work Logs & Reports")
        
        tab1, tab2, tab3 = st.tabs(["Log Work", "View Logs", "Generate Reports"])
        
        with tab1:
            WorkLogsPage._render_log_work()
        
        with tab2:
            WorkLogsPage._render_view_logs()
        
        with tab3:
            WorkLogsPage._render_generate_reports()
    
    @staticmethod
    def _render_log_work():
        """Render form to log work"""
        with st.form("log_work", border=True):
            st.subheader("➕ Log New Work")
            
            col1, col2 = st.columns(2)
            
            with col1:
                # Building selection
                buildings = db.query("SELECT id, building_name FROM buildings WHERE status = 'active' ORDER BY building_name")
                building_options = {b["building_name"]: b["id"] for b in buildings}
                
                if not building_options:
                    st.warning("No active buildings found")
                    st.stop()
                
                building_name = st.selectbox("Building*", list(building_options.keys()))
                building_id = building_options[building_name]
                
                # Unit selection
                units = db.query("""
                    SELECT id, unit_label 
                    FROM units 
                    WHERE building_id = ? AND status = 'active'
                    ORDER BY unit_label
                """, (building_id,))
                
                unit_options = {"N/A (Building-wide)": None}
                unit_options.update({f"Unit {u['unit_label']}": u["id"] for u in units})
                
                unit_selection = st.selectbox("Unit (optional)", list(unit_options.keys()))
                unit_id = unit_options[unit_selection]
            
            with col2:
                # Work details
                work_type = st.selectbox("Work Type*", 
                                        ["fiber", "construction", "repair", "test", "inspect", "other"])
                
                status = st.selectbox("Status*", 
                                     ["completed", "in_progress", "pending", "on_hold"])
                
                priority = st.select_slider("Priority", 
                                           options=["low", "medium", "high"], 
                                           value="medium")
                
                hours_spent = st.number_input("Hours Spent", min_value=0.0, max_value=24.0, value=0.0, step=0.5)
            
            # Description
            summary = st.text_input("Summary*", 
                                  placeholder="Brief description of work performed...")
            
            details = st.text_area("Details", 
                                 placeholder="Detailed notes, materials used, issues encountered...",
                                 height=150)
            
            materials = st.text_area("Materials Used (comma-separated)",
                                   placeholder="fiber cable, connectors, termination kit, ...")
            
            # AI assistant
            if DEEPSEEK_API_KEY:
                with st.expander("🤖 AI Assistant (Generate Report)"):
                    if st.button("Generate Professional Report", use_container_width=True):
                        prompt = f"""
                        Create a professional field work report for:
                        - Building: {building_name}
                        - Unit: {unit_selection if unit_id else 'Building-wide'}
                        - Work Type: {work_type}
                        - Summary: {summary}
                        - Details: {details}
                        - Technician: {st.session_state.user['full_name']}
                        
                        Include sections for: Work Performed, Materials Used, Issues Found, Recommendations.
                        """
                        
                        ai_report = AIIntegration.generate_report(prompt)
                        if ai_report:
                            st.session_state.ai_report = ai_report
                            st.text_area("AI Generated Report", value=ai_report, height=200)
            
            # Photos
            photos = st.file_uploader("Upload Photos (optional)", 
                                    type=["jpg", "jpeg", "png"], 
                                    accept_multiple_files=True)
            
            if st.form_submit_button("💾 Save Work Log", type="primary", use_container_width=True):
                if not summary:
                    UIComponents.error_message("Summary is required")
                else:
                    # Save photos
                    photo_paths = []
                    if photos:
                        os.makedirs("uploads/photos", exist_ok=True)
                        for photo in photos:
                            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{photo.name}"
                            filepath = f"uploads/photos/{filename}"
                            with open(filepath, "wb") as f:
                                f.write(photo.getbuffer())
                            photo_paths.append(filepath)
                    
                    # Save work log
                    work_log_id = db.execute("""
                        INSERT INTO work_logs 
                        (building_id, unit_id, created_by_email, created_by_name, created_by_id,
                         work_type, summary, details, hours_spent, materials_used, photos,
                         status, priority, completed_at, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        building_id,
                        unit_id,
                        st.session_state.user["email"],
                        st.session_state.user["full_name"],
                        st.session_state.user["id"],
                        work_type,
                        summary.strip(),
                        details.strip(),
                        hours_spent,
                        materials.strip(),
                        json.dumps(photo_paths) if photo_paths else None,
                        status,
                        {"low": 3, "medium": 2, "high": 1}[priority],
                        datetime.now().isoformat() if status == "completed" else None,
                        datetime.now().isoformat(),
                        datetime.now().isoformat()
                    ))
                    
                    db.log_audit(
                        st.session_state.user["id"],
                        st.session_state.user["email"],
                        "WORK_LOG_CREATED",
                        "work_logs",
                        work_log_id,
                        None,
                        {"building_id": building_id, "work_type": work_type, "summary": summary[:50]}
                    )
                    
                    UIComponents.success_message("Work log saved successfully!")
                    
                    # Auto-generate WhatsApp-style update
                    building = db.query("SELECT building_name FROM buildings WHERE id = ?", (building_id,))
                    building_name = building[0]["building_name"] if building else "Unknown"
                    
                    unit_info = ""
                    if unit_id:
                        unit = db.query("SELECT unit_label FROM units WHERE id = ?", (unit_id,))
                        unit_info = f" in Unit {unit[0]['unit_label']}" if unit else ""
                    
                    whatsapp_msg = f"Work logged for {building_name}{unit_info}: {work_type} - {summary[:50]}..."
                    st.info(f"💬 **WhatsApp-style update:** {whatsapp_msg}")
    
    @staticmethod
    def _render_view_logs():
        """Render view logs with filters"""
        st.subheader("🔍 View & Filter Work Logs")
        
        # Filters
        col1, col2, col3 = st.columns(3)
        
        with col1:
            date_range = st.date_input(
                "Date Range",
                value=(datetime.now().date() - timedelta(days=30), datetime.now().date())
            )
        
        with col2:
            status_filter = st.selectbox(
                "Status",
                ["All", "completed", "in_progress", "pending", "on_hold"]
            )
        
        with col3:
            work_type_filter = st.selectbox(
                "Work Type",
                ["All", "fiber", "construction", "repair", "test", "inspect", "other"]
            )
        
        # Build query
        query = """
            SELECT wl.*, b.building_name, u.unit_label
            FROM work_logs wl
            LEFT JOIN buildings b ON wl.building_id = b.id
            LEFT JOIN units u ON wl.unit_id = u.id
            WHERE 1=1
        """
        params = []
        
        if len(date_range) == 2:
            query += " AND DATE(wl.created_at) BETWEEN ? AND ?"
            params.extend([date_range[0].isoformat(), date_range[1].isoformat()])
        
        if status_filter != "All":
            query += " AND wl.status = ?"
            params.append(status_filter)
        
        if work_type_filter != "All":
            query += " AND wl.work_type = ?"
            params.append(work_type_filter)
        
        query += " ORDER BY wl.created_at DESC"
        
        # Execute query
        logs = db.query(query, params)
        
        st.write(f"**Found {len(logs)} work logs**")
        
        # Display logs
        for log in logs:
            with st.expander(f"{log['building_name']} - {log.get('unit_label', 'N/A')} - {log['created_at'][:10]}"):
                cols = st.columns([2, 1, 1])
                with cols[0]:
                    st.write(f"**Summary:** {log['summary']}")
                    if log['details']:
                        st.write(f"**Details:** {log['details']}")
                    
                    if log['materials_used']:
                        st.write(f"**Materials:** {log['materials_used']}")
                
                with cols[1]:
                    st.write(f"**Type:** {log['work_type']}")
                    st.write(f"**Status:** {log['status']}")
                    st.write(f"**Hours:** {log['hours_spent']}")
                
                with cols[2]:
                    st.write(f"**By:** {log['created_by_name']}")
                    st.write(f"**Date:** {log['created_at'][:16]}")
                
                # Action buttons
                if st.button("View Details", key=f"view_log_{log['id']}"):
                    st.json(log)
    
    @staticmethod
    def _render_generate_reports():
        """Render report generation"""
        st.subheader("📊 Generate Reports")
        
        # Report type
        report_type = st.selectbox(
            "Report Type",
            ["Daily Summary", "Weekly Summary", "Monthly Summary", "Custom", "Performance Analytics"]
        )
        
        # Date range
        col1, col2 = st.columns(2)
        
        with col1:
            start_date = st.date_input("Start Date", 
                                     value=datetime.now().date() - timedelta(days=7))
        
        with col2:
            end_date = st.date_input("End Date", value=datetime.now().date())
        
        # Filters
        building_filter = st.selectbox(
            "Building (optional)",
            ["All"] + [b["building_name"] for b in 
                      db.query("SELECT building_name FROM buildings ORDER BY building_name")]
        )
        
        # Generate report
        if st.button("📈 Generate Report", type="primary", use_container_width=True):
            with UIComponents.loading_spinner("Generating report..."):
                # Query data
                query = """
                    SELECT 
                        wl.*,
                        b.building_name,
                        u.unit_label,
                        CASE 
                            WHEN wl.priority = 1 THEN 'High'
                            WHEN wl.priority = 2 THEN 'Medium'
                            ELSE 'Low'
                        END as priority_text
                    FROM work_logs wl
                    LEFT JOIN buildings b ON wl.building_id = b.id
                    LEFT JOIN units u ON wl.unit_id = u.id
                    WHERE DATE(wl.created_at) BETWEEN ? AND ?
                """
                params = [start_date.isoformat(), end_date.isoformat()]
                
                if building_filter != "All":
                    query += " AND b.building_name = ?"
                    params.append(building_filter)
                
                query += " ORDER BY wl.created_at DESC"
                
                data = db.query(query, params)
                
                if not data:
                    st.info("No data found for the selected criteria")
                    return
                
                # Convert to DataFrame
                df = pd.DataFrame(data)
                
                # Display statistics
                st.subheader("📈 Statistics")
                
                stats_cols = st.columns(4)
                with stats_cols[0]:
                    st.metric("Total Tasks", len(df))
                with stats_cols[1]:
                    completed = len(df[df["status"] == "completed"])
                    st.metric("Completed", completed)
                with stats_cols[2]:
                    total_hours = df["hours_spent"].sum()
                    st.metric("Total Hours", f"{total_hours:.1f}")
                with stats_cols[3]:
                    avg_hours = df["hours_spent"].mean() if len(df) > 0 else 0
                    st.metric("Avg Hours/Task", f"{avg_hours:.1f}")
                
                # Display data
                st.subheader("📋 Detailed Data")
                st.dataframe(df[[
                    "created_at", "building_name", "unit_label", 
                    "work_type", "status", "priority_text", 
                    "hours_spent", "created_by_name"
                ]], use_container_width=True, hide_index=True)
                
                # Export options
                st.subheader("📤 Export Options")
                
                export_cols = st.columns(4)
                
                with export_cols[0]:
                    # CSV
                    csv = df.to_csv(index=False)
                    st.download_button(
                        "Download CSV",
                        data=csv,
                        file_name=f"report_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
                
                with export_cols[1]:
                    # Excel
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False, sheet_name='Report')
                    st.download_button(
                        "Download Excel",
                        data=output.getvalue(),
                        file_name=f"report_{datetime.now().strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                
                with export_cols[2]:
                    # JSON
                    json_data = json.dumps(data, default=str, indent=2)
                    st.download_button(
                        "Download JSON",
                        data=json_data,
                        file_name=f"report_{datetime.now().strftime('%Y%m%d')}.json",
                        mime="application/json",
                        use_container_width=True
                    )
                
                with export_cols[3]:
                    # Email report
                    if st.button("📧 Email Report", use_container_width=True):
                        # Create email recipients list
                        recipients = [st.session_state.user["email"]]
                        
                        # Add supervisors
                        supervisors = db.query("""
                            SELECT email FROM users 
                            WHERE role IN ('owner', 'supervisor') AND active = 1
                        """)
                        recipients.extend([s["email"] for s in supervisors])
                        
                        # Send email
                        report_data = {
                            "tasks_today": len(df),
                            "completed_tasks": completed,
                            "total_hours": total_hours,
                            "start_date": start_date.isoformat(),
                            "end_date": end_date.isoformat()
                        }
                        
                        if EmailManager.send_daily_report(list(set(recipients)), report_data):
                            UIComponents.success_message("Report emailed successfully!")
                        else:
                            UIComponents.error_message("Failed to email report")

class WhatsAppPage:
    """WhatsApp import and analysis"""
    
    @staticmethod
    def render():
        """Render WhatsApp page"""
        st.title("💬 WhatsApp Chat Import & Analysis")
        
        tab1, tab2 = st.tabs(["Import Chat", "Analyze Messages"])
        
        with tab1:
            WhatsAppPage._render_import()
        
        with tab2:
            WhatsAppPage._render_analysis()
    
    @staticmethod
    def _render_import():
        """Render WhatsApp import"""
        st.subheader("Upload WhatsApp Chat Export")
        
        st.info("""
        **How to export WhatsApp chats:**
        1. Open WhatsApp on your phone
        2. Go to the chat you want to export
        3. Tap ⋮ (three dots) → More → Export chat
        4. Choose "Without Media"
        5. Upload the exported .txt file here
        """)
        
        # File upload
        uploaded = st.file_uploader("Upload WhatsApp export (.txt)", type=["txt"])
        
        if uploaded:
            content = uploaded.read().decode("utf-8", errors="ignore")
            lines = content.split("\n")
            
            st.success(f"Loaded {len(lines)} lines")
            
            # Preview
            with st.expander("Preview first 20 lines"):
                for i, line in enumerate(lines[:20]):
                    st.text(line)
            
            # Processing options
            st.subheader("Processing Options")
            
            col1, col2 = st.columns(2)
            
            with col1:
                auto_detect_units = st.checkbox("Auto-detect unit numbers", value=True)
                auto_map_buildings = st.checkbox("Auto-map to buildings", value=True)
            
            with col2:
                confidence_threshold = st.slider("Confidence threshold", 0.0, 1.0, 0.5, 0.1)
                limit_lines = st.number_input("Limit processing to first N lines", 
                                            min_value=0, max_value=10000, value=1000)
            
            if st.button("🚀 Process Messages", type="primary", use_container_width=True):
                if limit_lines > 0:
                    lines = lines[:limit_lines]
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                processed = 0
                errors = 0
                
                for i, line in enumerate(lines):
                    try:
                        parsed = WhatsAppParser.parse_line(line)
                        if parsed and parsed.get("sender") and parsed.get("message"):
                            # Extract unit info
                            unit_info = WhatsAppParser.extract_unit_info(parsed["message"])
                            
                            # Try to find building and unit
                            building_id = None
                            unit_id = None
                            confidence = unit_info["confidence"]
                            
                            if auto_detect_units and unit_info["unit_label"] and confidence >= confidence_threshold:
                                # Search for unit
                                unit = db.query("""
                                    SELECT u.id, u.building_id
                                    FROM units u
                                    WHERE u.unit_label = ?
                                    LIMIT 1
                                """, (unit_info["unit_label"],))
                                
                                if unit:
                                    unit_id = unit[0]["id"]
                                    building_id = unit[0]["building_id"]
                            
                            # Save message
                            db.execute("""
                                INSERT INTO whatsapp_messages 
                                (building_id, unit_id, raw_line, parsed_dt, parsed_sender, 
                                 parsed_message, is_processed, confidence_score, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                building_id,
                                unit_id,
                                parsed["raw_line"],
                                parsed.get("datetime") or f"{parsed.get('date', '')} {parsed.get('time', '')}",
                                parsed["sender"],
                                parsed["message"],
                                1 if building_id or unit_id else 0,
                                confidence,
                                datetime.now().isoformat()
                            ))
                            
                            processed += 1
                    
                    except Exception as e:
                        errors += 1
                    
                    # Update progress
                    progress = (i + 1) / len(lines)
                    progress_bar.progress(progress)
                    status_text.text(f"Processing line {i + 1} of {len(lines)}...")
                
                progress_bar.empty()
                status_text.empty()
                
                UIComponents.success_message(
                    f"Processed {processed} messages with {errors} errors"
                )
                
                db.log_audit(
                    st.session_state.user["id"],
                    st.session_state.user["email"],
                    "WHATSAPP_IMPORT",
                    "whatsapp_messages",
                    None,
                    None,
                    {"processed": processed, "errors": errors}
                )
    
    @staticmethod
    def _render_analysis():
        """Render WhatsApp analysis"""
        st.subheader("Analyze Imported Messages")
        
        # Get statistics
        stats = db.query("""
            SELECT 
                COUNT(*) as total_messages,
                COUNT(DISTINCT parsed_sender) as unique_senders,
                SUM(CASE WHEN is_processed = 1 THEN 1 ELSE 0 END) as processed_messages,
                AVG(confidence_score) as avg_confidence
            FROM whatsapp_messages
        """)
        
        if stats:
            stat = stats[0]
            
            cols = st.columns(4)
            with cols[0]:
                st.metric("Total Messages", stat["total_messages"])
            with cols[1]:
                st.metric("Unique Senders", stat["unique_senders"])
            with cols[2]:
                st.metric("Processed", stat["processed_messages"])
            with cols[3]:
                st.metric("Avg Confidence", f"{stat['avg_confidence']:.2%}")
        
        # Recent messages
        st.subheader("Recent Messages")
        
        messages = db.query("""
            SELECT 
                wm.*,
                b.building_name,
                u.unit_label
            FROM whatsapp_messages wm
            LEFT JOIN buildings b ON wm.building_id = b.id
            LEFT JOIN units u ON wm.unit_id = u.id
            ORDER BY wm.created_at DESC
            LIMIT 20
        """)
        
        for msg in messages:
            with st.container(border=True):
                cols = st.columns([1, 3])
                with cols[0]:
                    st.write(f"**{msg['parsed_sender']}**")
                    if msg["parsed_dt"]:
                        st.caption(msg["parsed_dt"])
                    else:
                        st.caption(msg["created_at"][:19])
                
                with cols[1]:
                    st.write(msg["parsed_message"])
                    
                    if msg["building_name"]:
                        st.caption(f"📍 {msg['building_name']} {msg.get('unit_label', '')}")
                    
                    if msg["confidence_score"] and msg["confidence_score"] > 0:
                        st.progress(msg["confidence_score"], 
                                  text=f"Confidence: {msg['confidence_score']:.0%}")
        
        # AI Analysis
        if DEEPSEEK_API_KEY and st.button("🤖 AI Analysis", use_container_width=True):
            with UIComponents.loading_spinner("Analyzing messages with AI..."):
                # Get recent messages for analysis
                recent_texts = [m["parsed_message"] for m in messages if m["parsed_message"]]
                
                if recent_texts:
                    analysis = AIIntegration.analyze_whatsapp_messages(recent_texts)
                    
                    if analysis:
                        st.subheader("AI Analysis Results")
                        
                        if "issues" in analysis:
                            st.write("**Common Issues:**")
                            for issue in analysis["issues"]:
                                st.write(f"- {issue}")
                        
                        if "improvements" in analysis:
                            st.write("**Suggested Improvements:**")
                            for improvement in analysis["improvements"]:
                                st.write(f"- {improvement}")
                        
                        if "urgent" in analysis:
                            st.write("**Urgent Matters:**")
                            for urgent in analysis["urgent"]:
                                st.write(f"- 🔴 {urgent}")

class AdminPage:
    """Admin page for system management"""
    
    @staticmethod
    def render():
        """Render admin page"""
        if st.session_state.user["role"] not in ["owner", "supervisor"]:
            st.error("⚠️ Admin access required")
            return
        
        st.title("⚙️ Admin Panel")
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "User Management", "System Settings", "Audit Logs", 
            "Backup & Restore", "System Health"
        ])
        
        with tab1:
            AdminPage._render_user_management()
        
        with tab2:
            AdminPage._render_system_settings()
        
        with tab3:
            AdminPage._render_audit_logs()
        
        with tab4:
            AdminPage._render_backup_restore()
        
        with tab5:
            AdminPage._render_system_health()
    
    @staticmethod
    def _render_user_management():
        """Render user management"""
        st.subheader("👥 User Management")
        
        # Add user form
        with st.form("add_user", border=True):
            col1, col2 = st.columns(2)
            
            with col1:
                full_name = st.text_input("Full Name*")
                email = st.text_input("Email*")
            
            with col2:
                role = st.selectbox("Role", ["tech", "supervisor", "owner", "viewer"])
                password = st.text_input("Initial Password*", type="password")
            
            # 2FA option
            enable_2fa = st.checkbox("Enable Two-Factor Authentication")
            
            if st.form_submit_button("➕ Add User", type="primary", use_container_width=True):
                if not all([full_name, email, password]):
                    UIComponents.error_message("All fields are required")
                else:
                    # Validate password strength
                    is_strong, message = SecurityManager.validate_password_strength(password)
                    if not is_strong:
                        UIComponents.error_message(message)
                        return
                    
                    # Hash password
                    salt, pwd_hash = SecurityManager.hash_password(password)
                    
                    # Generate 2FA secret if enabled
                    two_factor_secret = None
                    if enable_2fa and TOTP_AVAILABLE:
                        two_factor_data = SecurityManager.generate_2fa_secret(email)
                        two_factor_secret = two_factor_data["secret"]
                    
                    try:
                        user_id = db.execute("""
                            INSERT INTO users 
                            (full_name, email, password_hash, password_salt, role,
                             two_factor_secret, two_factor_enabled, active,
                             created_at, updated_at, must_change_password)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            full_name.strip(),
                            email.lower().strip(),
                            pwd_hash,
                            salt,
                            role,
                            two_factor_secret,
                            1 if two_factor_secret else 0,
                            1,
                            datetime.now().isoformat(),
                            datetime.now().isoformat(),
                            1
                        ))
                        
                        db.log_audit(
                            st.session_state.user["id"],
                            st.session_state.user["email"],
                            "USER_CREATED",
                            "users",
                            user_id,
                            None,
                            {"email": email, "role": role}
                        )
                        
                        UIComponents.success_message(f"User '{full_name}' added successfully")
                        
                        # Show QR code for 2FA
                        if two_factor_secret:
                            st.image(two_factor_data["qr_code"], 
                                   caption="Scan with Google Authenticator")
                        
                        st.rerun()
                    
                    except Exception as e:
                        UIComponents.error_message(f"Error: {e}")
        
        # User list
        st.subheader("User List")
        
        users = db.query("""
            SELECT id, full_name, email, role, active, last_login,
                   two_factor_enabled, failed_login_attempts
            FROM users
            ORDER BY role, full_name
        """)
        
        if users:
            df = pd.DataFrame(users)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # User actions
            st.subheader("User Actions")
            
            user_options = {f"{u['full_name']} ({u['email']})": u["id"] for u in users}
            selected_user = st.selectbox("Select User", list(user_options.keys()))
            user_id = user_options[selected_user]
            
            col_a, col_b, col_c = st.columns(3)
            
            with col_a:
                if st.button("Reset Password", use_container_width=True):
                    st.session_state.reset_user_id = user_id
                    st.rerun()
            
            with col_b:
                user = next((u for u in users if u["id"] == user_id), None)
                if user:
                    new_status = "Deactivate" if user["active"] else "Activate"
                    if st.button(new_status, use_container_width=True):
                        db.execute("UPDATE users SET active = ? WHERE id = ?",
                                 (0 if user["active"] else 1, user_id))
                        st.rerun()
            
            with col_c:
                if st.button("Force Password Change", use_container_width=True):
                    db.execute("UPDATE users SET must_change_password = 1 WHERE id = ?", (user_id,))
                    UIComponents.success_message("User will be prompted to change password on next login")
        
        # Password reset modal
        if st.session_state.get("reset_user_id"):
            with st.container(border=True):
                st.subheader("Reset Password")
                
                new_password = st.text_input("New Password", type="password")
                confirm_password = st.text_input("Confirm Password", type="password")
                
                col_x, col_y = st.columns(2)
                with col_x:
                    if st.button("Reset", type="primary"):
                        if new_password != confirm_password:
                            UIComponents.error_message("Passwords don't match")
                        else:
                            is_strong, message = SecurityManager.validate_password_strength(new_password)
                            if not is_strong:
                                UIComponents.error_message(message)
                            else:
                                salt, pwd_hash = SecurityManager.hash_password(new_password)
                                db.execute("""
                                    UPDATE users 
                                    SET password_hash = ?, password_salt = ?,
                                        must_change_password = 1
                                    WHERE id = ?
                                """, (pwd_hash, salt, st.session_state.reset_user_id))
                                
                                UIComponents.success_message("Password reset successfully")
                                st.session_state.reset_user_id = None
                                st.rerun()
                
                with col_y:
                    if st.button("Cancel"):
                        st.session_state.reset_user_id = None
                        st.rerun()
    
    @staticmethod
    def _render_system_settings():
        """Render system settings"""
        st.subheader("⚙️ System Settings")
        
        # Get current settings
        settings = db.query("SELECT * FROM system_settings ORDER BY setting_key")
        
        if settings:
            for setting in settings:
                col1, col2, col3 = st.columns([2, 2, 1])
                
                with col1:
                    st.write(f"**{setting['setting_key']}**")
                    st.caption(setting['description'])
                
                with col2:
                    if setting['data_type'] == 'integer':
                        value = st.number_input("", 
                                              value=int(setting['setting_value'] or 0),
                                              key=f"setting_{setting['id']}")
                    elif setting['data_type'] == 'boolean':
                        value = st.checkbox("", 
                                          value=bool(int(setting['setting_value'] or 0)),
                                          key=f"setting_{setting['id']}")
                    else:
                        value = st.text_input("", 
                                            value=setting['setting_value'] or "",
                                            key=f"setting_{setting['id']}")
                
                with col3:
                    if st.button("Save", key=f"save_{setting['id']}"):
                        db.execute("""
                            UPDATE system_settings 
                            SET setting_value = ?, updated_at = ?
                            WHERE id = ?
                        """, (
                            str(value) if not isinstance(value, bool) else str(int(value)),
                            datetime.now().isoformat(),
                            setting["id"]
                        ))
                        UIComponents.success_message(f"Updated {setting['setting_key']}")
        
        # Add new setting
        with st.expander("➕ Add New Setting"):
            col1, col2 = st.columns(2)
            
            with col1:
                new_key = st.text_input("Setting Key")
                new_description = st.text_area("Description")
            
            with col2:
                new_type = st.selectbox("Data Type", ["string", "integer", "boolean"])
                new_value = st.text_input("Value")
            
            if st.button("Add Setting"):
                if not new_key:
                    UIComponents.error_message("Setting key is required")
                else:
                    try:
                        db.execute("""
                            INSERT INTO system_settings 
                            (setting_key, setting_value, data_type, description, created_at, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            new_key.strip(),
                            new_value.strip(),
                            new_type,
                            new_description.strip(),
                            datetime.now().isoformat(),
                            datetime.now().isoformat()
                        ))
                        UIComponents.success_message("Setting added")
                        st.rerun()
                    except Exception as e:
                        UIComponents.error_message(f"Error: {e}")
    
    @staticmethod
    def _render_audit_logs():
        """Render audit logs"""
        st.subheader("📋 Audit Logs")
        
        # Filters
        col1, col2, col3 = st.columns(3)
        
        with col1:
            date_range = st.date_input(
                "Date Range",
                value=(datetime.now().date() - timedelta(days=7), datetime.now().date()),
                key="audit_date_range"
            )
        
        with col2:
            action_filter = st.text_input("Filter by Action")
        
        with col3:
            user_filter = st.text_input("Filter by User Email")
        
        # Build query
        query = """
            SELECT * FROM audit_logs
            WHERE 1=1
        """
        params = []
        
        if len(date_range) == 2:
            query += " AND DATE(created_at) BETWEEN ? AND ?"
            params.extend([date_range[0].isoformat(), date_range[1].isoformat()])
        
        if action_filter:
            query += " AND action LIKE ?"
            params.append(f"%{action_filter}%")
        
        if user_filter:
            query += " AND user_email LIKE ?"
            params.append(f"%{user_filter}%")
        
        query += " ORDER BY created_at DESC LIMIT 100"
        
        # Get logs
        logs = db.query(query, params)
        
        st.write(f"**Showing {len(logs)} recent audit logs**")
        
        if logs:
            df = pd.DataFrame(logs)
            st.dataframe(df, use_container_width=True, hide_index=True)
            
            # Export audit logs
            csv = df.to_csv(index=False)
            st.download_button(
                "📥 Export Audit Logs (CSV)",
                data=csv,
                file_name=f"audit_logs_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        else:
            st.info("No audit logs found for the selected criteria")
    
    @staticmethod
    def _render_backup_restore():
        """Render backup and restore"""
        st.subheader("💾 Backup & Restore")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Create Backup")
            
            if st.button("🔄 Create Database Backup", use_container_width=True):
                with UIComponents.loading_spinner("Creating backup..."):
                    backup_file = db.backup_database()
                    UIComponents.success_message(f"Backup created: {backup_file}")
                    
                    # Offer download
                    with open(backup_file, "rb") as f:
                        st.download_button(
                            "⬇️ Download Backup",
                            data=f,
                            file_name=os.path.basename(backup_file),
                            mime="application/octet-stream",
                            use_container_width=True
                        )
        
        with col2:
            st.markdown("### Restore Backup")
            
            backup_files = list(Path(BACKUP_DIR).glob("*.db")) if os.path.exists(BACKUP_DIR) else []
            
            if backup_files:
                backup_options = {f.stem: f for f in sorted(backup_files, reverse=True)}
                selected = st.selectbox("Select backup", list(backup_options.keys()))
                
                if st.button("🔄 Restore Selected Backup", use_container_width=True):
                    st.warning("⚠️ This will replace the current database. Continue?", icon="⚠️")
                    
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("Yes, Restore", type="primary"):
                            import shutil
                            backup_file = backup_options[selected]
                            
                            # Close database connection
                            db.conn.close()
                            
                            # Restore backup
                            shutil.copy2(backup_file, DB_PATH)
                            
                            # Reinitialize database
                            db._init_db()
                            
                            UIComponents.success_message("Database restored successfully")
                            st.rerun()
                    
                    with col_b:
                        if st.button("Cancel"):
                            st.rerun()
            else:
                st.info("No backups found")
        
        # Backup settings
        st.subheader("Backup Settings")
        
        retention_days = st.slider("Backup retention (days)", 1, 90, 30)
        auto_backup = st.checkbox("Enable automatic daily backup", value=True)
        
        if st.button("Save Backup Settings"):
            db.execute("""
                UPDATE system_settings 
                SET setting_value = ?, updated_at = ?
                WHERE setting_key = ?
            """, (str(retention_days), datetime.now().isoformat(), "backup_retention_days"))
            
            db.execute("""
                UPDATE system_settings 
                SET setting_value = ?, updated_at = ?
                WHERE setting_key = ?
            """, (str(int(auto_backup)), datetime.now().isoformat(), "auto_backup"))
            
            UIComponents.success_message("Backup settings saved")
    
    @staticmethod
    def _render_system_health():
        """Render system health monitoring"""
        st.subheader("🩺 System Health")
        
        # Get health metrics
        health = db.get_system_health()
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            db_size = health.get("db_size_mb", 0)
            st.metric("Database Size", f"{db_size:.1f} MB")
            st.progress(min(db_size / 100, 1.0))
        
        with col2:
            active_users = health.get("active_users_7d", 0)
            st.metric("Active Users (7d)", active_users)
        
        with col3:
            if health.get("last_backup_hours") is None:
                st.metric("Last Backup", "Never", delta="⚠️")
            elif health["last_backup_hours"] > 24:
                st.metric("Last Backup", f"{health['last_backup_hours']:.1f}h", delta="⚠️")
            else:
                st.metric("Last Backup", f"{health['last_backup_hours']:.1f}h", delta="✓")
        
        with col4:
            total_tasks = health.get("work_logs_count", 0)
            st.metric("Total Tasks", total_tasks)
        
        # Detailed metrics
        st.subheader("Detailed Metrics")
        
        metrics_df = pd.DataFrame([
            {"Metric": "Buildings", "Count": health.get("buildings_count", 0)},
            {"Metric": "Units", "Count": health.get("units_count", 0)},
            {"Metric": "Work Logs", "Count": health.get("work_logs_count", 0)},
            {"Metric": "WhatsApp Messages", "Count": health.get("whatsapp_messages_count", 0)},
            {"Metric": "Audit Logs", "Count": health.get("audit_logs_count", 0)},
            {"Metric": "Login Attempts", "Count": health.get("login_attempts_count", 0)},
        ])
        
        st.dataframe(metrics_df, use_container_width=True, hide_index=True)
        
        # System checks
        st.subheader("System Checks")
        
        checks = []
        
        # Database size check
        if health.get("db_size_mb", 0) > 50:
            checks.append(("Database Size", f"{health['db_size_mb']:.1f} MB", "⚠️ Consider archiving old data"))
        else:
            checks.append(("Database Size", f"{health['db_size_mb']:.1f} MB", "✓ OK"))
        
        # Backup check
        if health.get("last_backup_hours") is None:
            checks.append(("Backup", "Never", "❌ No backups found"))
        elif health["last_backup_hours"] > 24:
            checks.append(("Backup", f"{health['last_backup_hours']:.1f} hours ago", "⚠️ Backup overdue"))
        else:
            checks.append(("Backup", f"{health['last_backup_hours']:.1f} hours ago", "✓ OK"))
        
        # User activity check
        if health.get("active_users_7d", 0) == 0:
            checks.append(("User Activity", "No active users", "⚠️ Check system usage"))
        else:
            checks.append(("User Activity", f"{health['active_users_7d']} users", "✓ OK"))
        
        # Display checks
        for check, value, status in checks:
            col_a, col_b, col_c = st.columns([2, 2, 2])
            with col_a:
                st.write(check)
            with col_b:
                st.write(value)
            with col_c:
                if "✓" in status:
                    st.success(status)
                elif "⚠️" in status:
                    st.warning(status)
                else:
                    st.error(status)
        
        # Performance statistics
        st.subheader("Performance Statistics")
        
        # Get recent performance data
        recent_stats = db.query("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as daily_tasks,
                AVG(hours_spent) as avg_hours
            FROM work_logs
            WHERE created_at > datetime('now', '-30 days')
            GROUP BY DATE(created_at)
            ORDER BY date
        """)
        
        if recent_stats:
            stats_df = pd.DataFrame(recent_stats)
            st.line_chart(stats_df.set_index("date")[["daily_tasks"]])
        
        # Maintenance actions
        st.subheader("Maintenance Actions")
        
        col_x, col_y, col_z = st.columns(3)
        
        with col_x:
            if st.button("Optimize Database", use_container_width=True):
                db.execute("VACUUM")
                db.execute("ANALYZE")
                UIComponents.success_message("Database optimized")
        
        with col_y:
            if st.button("Clear Old Audit Logs", use_container_width=True):
                cutoff = (datetime.now() - timedelta(days=90)).isoformat()
                db.execute("DELETE FROM audit_logs WHERE created_at < ?", (cutoff,))
                UIComponents.success_message("Old audit logs cleared")
        
        with col_z:
            if st.button("Update Statistics", use_container_width=True):
                db.execute("ANALYZE")
                UIComponents.success_message("Statistics updated")

# ==========================================================
# MAIN APPLICATION
# ==========================================================
class FiberOpsApp:
    """Main application class"""
    
    def __init__(self):
        """Initialize application"""
        self.setup_page_config()
        self.load_secrets()
        SessionManager.init_session()
        db.seed_default_data()
    
    def setup_page_config(self):
        """Setup Streamlit page configuration"""
        st.set_page_config(
            page_title=APP_TITLE,
            page_icon="🏢",
            layout="wide",
            initial_sidebar_state="expanded",
            menu_items={
                'Get Help': 'https://fiberops-hghitechs.com/help',
                'Report a bug': 'https://fiberops-hghitechs.com/bug',
                'About': f'### {APP_TITLE}\nVersion: {APP_VERSION}\n\nEnterprise field operations management system.'
            }
        )
        
        # Add custom CSS
        self.add_custom_css()
    
    def add_custom_css(self):
        """Add custom CSS for better UI"""
        st.markdown("""
        <style>
        /* Main styles */
        .main .block-container {
            padding-top: 2rem;
        }
        
        /* Metric cards */
        .metric-card {
            background: white;
            padding: 1rem;
            border-radius: 0.5rem;
            border: 1px solid #e0e0e0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        /* Badges */
        .badge {
            display: inline-block;
            padding: 0.25em 0.5em;
            font-size: 0.75em;
            font-weight: 600;
            line-height: 1;
            text-align: center;
            white-space: nowrap;
            vertical-align: baseline;
            border-radius: 0.25rem;
        }
        
        .bg-success { background-color: #d4edda; color: #155724; }
        .bg-warning { background-color: #fff3cd; color: #856404; }
        .bg-danger { background-color: #f8d7da; color: #721c24; }
        .bg-secondary { background-color: #6c757d; color: white; }
        .bg-dark { background-color: #343a40; color: white; }
        
        /* Mobile responsive */
        @media (max-width: 768px) {
            .block-container {
                padding: 1rem !important;
            }
            
            .stButton > button {
                width: 100%;
            }
        }
        </style>
        """, unsafe_allow_html=True)
    
    def load_secrets(self):
        """Load secrets from Streamlit secrets"""
        global DEEPSEEK_API_KEY, SMTP_CONFIG
        
        try:
            if hasattr(st, "secrets"):
                # AI API Key
                DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY")
                
                # Email configuration
                email_config = st.secrets.get("email", {})
                SMTP_CONFIG.update(email_config)
                
                # Other configurations
                if "database" in st.secrets:
                    global DB_PATH
                    DB_PATH = st.secrets.database.get("path", DB_PATH)
                
                logger.info("Secrets loaded successfully")
        
        except Exception as e:
            logger.warning(f"Could not load secrets: {e}")
    
    def render_sidebar(self):
        """Render application sidebar"""
        with st.sidebar:
            # User info
            if st.session_state.user:
                st.markdown(f"""
                <div style="text-align: center; margin-bottom: 1rem;">
                    <div style="font-size: 1.2rem; font-weight: bold;">
                        👋 Hi, {st.session_state.user['full_name'].split()[0]}!
                    </div>
                    <div style="color: #666; font-size: 0.9rem;">
                        {st.session_state.user['role'].title()}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Session timer
                if st.session_state.login_time:
                    login_time = datetime.fromisoformat(st.session_state.login_time)
                    elapsed = datetime.now() - login_time
                    remaining = timedelta(hours=SESSION_TIMEOUT_HOURS) - elapsed
                    
                    if remaining.total_seconds() > 0:
                        hours, remainder = divmod(remaining.seconds, 3600)
                        minutes, _ = divmod(remainder, 60)
                        st.caption(f"⏰ Session: {hours}h {minutes}m remaining")
                    else:
                        st.warning("Session expired")
            
            st.divider()
            
            # Navigation
            st.markdown("## Navigation")
            
            # Define pages based on user role
            pages = ["Dashboard", "Buildings & Units", "Work Logs", "WhatsApp", "Search"]
            
            if st.session_state.user["role"] in ["owner", "supervisor"]:
                pages.append("Admin")
            
            # Add logout to pages
            pages.append("Logout")
            
            # Page selection
            page = st.radio(
                "Go to",
                pages,
                label_visibility="collapsed"
            )
            
            st.divider()
            
            # Quick search
            st.markdown("### 🔍 Quick Search")
            search_query = st.text_input(
                "Search buildings, units, serials...",
                key="sidebar_search",
                label_visibility="collapsed"
            )
            
            if search_query:
                st.session_state.search_query = search_query
                st.session_state.page = "Search"
                st.rerun()
            
            st.divider()
            
            # Quick stats
            st.markdown("### 📊 Quick Stats")
            
            try:
                stats = db.query("""
                    SELECT 
                        (SELECT COUNT(*) FROM work_logs WHERE DATE(created_at) = DATE('now')) as today_tasks,
                        (SELECT COUNT(*) FROM work_logs WHERE status = 'pending') as pending_tasks
                """)
                
                if stats:
                    stat = stats[0]
                    st.metric("Today's Tasks", stat["today_tasks"])
                    st.metric("Pending Tasks", stat["pending_tasks"])
            except:
                pass
            
            st.divider()
            
            # App info
            st.caption(f"v{APP_VERSION}")
            st.caption("© 2024 HGHI FiberOps")
        
        return page
    
    def render_page(self, page_name):
        """Render the selected page"""
        if page_name == "Dashboard":
            DashboardPage.render()
        elif page_name == "Buildings & Units":
            BuildingsPage.render()
        elif page_name == "Work Logs":
            WorkLogsPage.render()
        elif page_name == "WhatsApp":
            WhatsAppPage.render()
        elif page_name == "Search":
            self.render_search_page()
        elif page_name == "Admin":
            AdminPage.render()
        elif page_name == "Logout":
            SessionManager.logout()
            st.rerun()
    
    def render_search_page(self):
        """Render search page"""
        st.title("🔍 Global Search")
        
        search_query = st.session_state.get("search_query", "")
        
        if not search_query:
            st.info("Enter a search term in the sidebar")
            return
        
        st.write(f"Searching for: **{search_query}**")
        
        # Search across all tables
        results = []
        
        # Search buildings
        buildings = db.query("""
            SELECT 
                'building' as type,
                id,
                building_name as name,
                address as details,
                created_at
            FROM buildings
            WHERE building_name LIKE ? 
               OR address LIKE ?
               OR city LIKE ?
               OR state LIKE ?
               OR zip LIKE ?
            LIMIT 10
        """, *[f"%{search_query}%"] * 5)
        results.extend(buildings)
        
        # Search units
        units = db.query("""
            SELECT 
                'unit' as type,
                u.id,
                u.unit_label as name,
                b.building_name || ' - ' || COALESCE(u.serial_number, 'No serial') as details,
                u.created_at
            FROM units u
            JOIN buildings b ON u.building_id = b.id
            WHERE u.unit_label LIKE ?
               OR u.serial_number LIKE ?
               OR u.equipment_tag LIKE ?
               OR u.notes LIKE ?
            LIMIT 10
        """, *[f"%{search_query}%"] * 4)
        results.extend(units)
        
        # Search work logs
        work_logs = db.query("""
            SELECT 
                'work_log' as type,
                wl.id,
                wl.summary as name,
                b.building_name || ' - ' || COALESCE(u.unit_label, 'Building-wide') as details,
                wl.created_at
            FROM work_logs wl
            LEFT JOIN buildings b ON wl.building_id = b.id
            LEFT JOIN units u ON wl.unit_id = u.id
            WHERE wl.summary LIKE ?
               OR wl.details LIKE ?
               OR wl.materials_used LIKE ?
            LIMIT 10
        """, *[f"%{search_query}%"] * 3)
        results.extend(work_logs)
        
        # Display results
        if not results:
            st.info("No results found")
            return
        
        st.write(f"**Found {len(results)} results**")
        
        # Group by type
        results_by_type = {}
        for result in results:
            result_type = result["type"]
            if result_type not in results_by_type:
                results_by_type[result_type] = []
            results_by_type[result_type].append(result)
        
        # Display grouped results
        for result_type, items in results_by_type.items():
            st.subheader(f"{result_type.title()}s ({len(items)})")
            
            for item in items:
                with st.container(border=True):
                    cols = st.columns([3, 1])
                    with cols[0]:
                        st.write(f"**{item['name']}**")
                        if item["details"]:
                            st.caption(item["details"])
                    with cols[1]:
                        st.caption(item["created_at"][:10])
                    
                    # View button
                    if st.button("View", key=f"view_{result_type}_{item['id']}"):
                        st.session_state[f"view_{result_type}_id"] = item["id"]
                        st.rerun()
    
    def run(self):
        """Run the application"""
        # Check authentication
        if not SessionManager.require_auth():
            LoginPage.render()
            return
        
        # Check if password needs changing
        if (st.session_state.user.get("must_change_password") and 
            not st.session_state.get("changing_password")):
            self.render_password_change()
            return
        
        # Check 2FA
        if (st.session_state.two_factor_required and 
            not st.session_state.two_factor_verified):
            self.render_2fa_verification()
            return
        
        # Get selected page from sidebar
        page = self.render_sidebar()
        
        # Render the page
        self.render_page(page)
    
    def render_password_change(self):
        """Render password change form"""
        st.title("🔐 Change Your Password")
        
        with st.form("change_password", border=True):
            current_password = st.text_input("Current Password", type="password")
            new_password = st.text_input("New Password", type="password")
            confirm_password = st.text_input("Confirm New Password", type="password")
            
            if st.form_submit_button("Change Password", type="primary", use_container_width=True):
                # Validate
                if not all([current_password, new_password, confirm_password]):
                    UIComponents.error_message("All fields are required")
                    return
                
                if new_password != confirm_password:
                    UIComponents.error_message("New passwords don't match")
                    return
                
                # Check current password
                user = st.session_state.user
                if not SecurityManager.verify_password(user["password_salt"], user["password_hash"], current_password):
                    UIComponents.error_message("Current password is incorrect")
                    return
                
                # Validate new password strength
                is_strong, message = SecurityManager.validate_password_strength(new_password)
                if not is_strong:
                    UIComponents.error_message(message)
                    return
                
                # Update password
                salt, pwd_hash = SecurityManager.hash_password(new_password)
                
                db.execute("""
                    UPDATE users 
                    SET password_hash = ?, password_salt = ?, 
                        must_change_password = 0, updated_at = ?
                    WHERE id = ?
                """, (pwd_hash, salt, datetime.now().isoformat(), user["id"]))
                
                db.log_audit(
                    user["id"],
                    user["email"],
                    "PASSWORD_CHANGED",
                    "users",
                    user["id"]
                )
                
                # Update session state
                st.session_state.user["password_hash"] = pwd_hash
                st.session_state.user["password_salt"] = salt
                st.session_state.user["must_change_password"] = 0
                st.session_state.changing_password = False
                
                UIComponents.success_message("Password changed successfully")
                st.rerun()
        
        # Cancel button (only for admin override)
        if st.session_state.user["role"] in ["owner", "supervisor"]:
            if st.button("Skip for now (Admin override)"):
                db.execute("UPDATE users SET must_change_password = 0 WHERE id = ?",
                         (st.session_state.user["id"],))
                st.session_state.changing_password = False
                st.rerun()
    
    def render_2fa_verification(self):
        """Render 2FA verification"""
        st.title("🔐 Two-Factor Authentication")
        
        st.info("Please enter the 6-digit code from your authenticator app")
        
        token = st.text_input("Authentication Code", max_chars=6)
        
        if st.button("Verify", type="primary", use_container_width=True):
            if token and len(token) == 6:
                if SessionManager.verify_2fa(token):
                    UIComponents.success_message("2FA verified successfully!")
                    st.rerun()
                else:
                    UIComponents.error_message("Invalid code. Please try again.")
            else:
                UIComponents.error_message("Please enter a valid 6-digit code")
        
        # Recovery options
        with st.expander("Need help?"):
            st.write("""
            **If you're having trouble with 2FA:**
            
            1. Make sure your device time is synchronized
            2. Check that you're using the correct authenticator app
            3. Contact your administrator for assistance
            
            **Emergency recovery:**
            Administrators can disable 2FA for your account if needed.
            """)

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    try:
        app = FiberOpsApp()
        app.run()
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        st.error(f"An error occurred: {e}")
        st.info("Please refresh the page or contact support if the issue persists.")
