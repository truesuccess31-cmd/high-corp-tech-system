# ============================================================
# HGHI TECH FIELD MANAGEMENT SYSTEM (Streamlit) - ENHANCED
# - Login + Contractor Registration (pending approval)
# - Time Clock (Clock in/out)
# - Ticket Manager (Email parser + manual ticket)
# - Unit Explorer (service history + equipment + notes)
# - DeepSeek AI integration (email parsing, reports, assistant)
# - ENHANCED: Session timeout, audit logs, backups, batch ops
#
# IMPORTANT:
# - Put DeepSeek key in Streamlit Secrets:
#   DEEPSEEK_API_KEY = "sk-..."
# ============================================================

import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import json
import time
import re
import base64
import io
import requests
import shutil
import os
import string
from datetime import datetime, timedelta
from PIL import Image

# ----------------------------
# COMPANY CONSTANTS
# ----------------------------
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]

DB_PATH = "field_management.db"
BACKUP_DIR = "database_backups"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Session timeout (minutes)
SESSION_TIMEOUT_MINUTES = 30

# Read secrets safely
DEEPSEEK_API_KEY = ""
try:
    if "DEEPSEEK_API_KEY" in st.secrets:
        DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except Exception:
    DEEPSEEK_API_KEY = ""

# ----------------------------
# HELPERS
# ----------------------------
def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def connect_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def export_to_excel(data_df, filename_prefix="report"):
    """Export DataFrame to Excel file"""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        data_df.to_excel(writer, index=False, sheet_name='Data')
    output.seek(0)
    return output

def backup_database():
    """Create backup of SQLite database"""
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
    
    backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_name)
    shutil.copy2(DB_PATH, backup_path)
    
    # Keep only last 10 backups
    backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')])
    if len(backups) > 10:
        for old_backup in backups[:-10]:
            os.remove(os.path.join(BACKUP_DIR, old_backup))
    
    return backup_path

def restore_database(backup_file):
    """Restore database from backup"""
    try:
        shutil.copy2(backup_file, DB_PATH)
        return True, "Database restored successfully"
    except Exception as e:
        return False, f"Restore failed: {str(e)}"

def validate_password(password):
    """Check password complexity requirements"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in string.punctuation for c in password)
    
    if not (has_upper and has_lower and has_digit and has_special):
        return False, "Password must include uppercase, lowercase, digit, and special character"
    
    return True, "Password valid"

def validate_parsed_data(data: dict) -> dict:
    """Validate and clean parsed email data"""
    required = ["issue_description"]
    for field in required:
        if field not in data or not str(data[field]).strip():
            data[field] = "Not specified"
    
    # Clean priority
    priority = str(data.get("priority", "normal")).lower()
    if priority not in ["urgent", "high", "normal"]:
        data["priority"] = "normal"
    else:
        data["priority"] = priority
    
    # Clean ticket ID format
    if "ticket_id" in data and data["ticket_id"]:
        data["ticket_id"] = data["ticket_id"].strip().upper()
    
    return data

def log_audit(user_id, action, details=""):
    """Log audit trail entry"""
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO audit_log (user_id, action, details, timestamp)
        VALUES (?, ?, ?, ?)
    """, (user_id, action, details, now_str()))
    conn.commit()
    conn.close()

def check_session_timeout():
    """Check if session has timed out"""
    if "last_activity" not in st.session_state:
        st.session_state.last_activity = datetime.now()
        return False
    
    elapsed = datetime.now() - st.session_state.last_activity
    if elapsed.total_seconds() > SESSION_TIMEOUT_MINUTES * 60:
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.clocked_in = False
        st.session_state.current_time_entry = None
        st.success("Session timed out due to inactivity")
        time.sleep(1)
        st.rerun()
    
    st.session_state.last_activity = datetime.now()
    return False

def add_indexes():
    """Add performance indexes to database"""
    conn = connect_db()
    c = conn.cursor()
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_time_contractor ON time_entries(contractor_id)",
        "CREATE INDEX IF NOT EXISTS idx_work_orders_status ON work_orders(status)",
        "CREATE INDEX IF NOT EXISTS idx_work_orders_contractor ON work_orders(contractor_id)",
        "CREATE INDEX IF NOT EXISTS idx_units_building ON units(building_id)",
        "CREATE INDEX IF NOT EXISTS idx_service_unit ON service_history(unit_id)",
        "CREATE INDEX IF NOT EXISTS idx_service_date ON service_history(service_date)",
        "CREATE INDEX IF NOT EXISTS idx_contractors_status ON contractors(status)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read)",
        "CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp)",
    ]
    
    for idx in indexes:
        try:
            c.execute(idx)
        except Exception as e:
            print(f"Index creation failed: {e}")
    
    conn.commit()
    conn.close()

# ----------------------------
# SIMPLE FALLBACK PARSER
# ----------------------------
def simple_parse_email(email_text: str):
    patterns = {
        "ticket_id": r"(T[-_ ]?\d{5,7})",
        "property_code": r"\[([A-Z0-9]{4,})\]",
        "unit_number": r"\[([A-Z]-?\d{2,4})\]",
        "resident_name": r"(?:Resident|Tenant)[:\s]+([A-Za-z\s\-\']+)",
        "issue_description": r"(?:Issue|Problem|Description)[:\s]+(.+)"
    }

    results = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, email_text, re.IGNORECASE)
        if match:
            results[key] = match.group(1).strip()

    lower = email_text.lower()
    if "urgent" in lower or "asap" in lower:
        results["priority"] = "urgent"
    elif "high" in lower or "priority" in lower:
        results["priority"] = "high"
    else:
        results["priority"] = "normal"

    if "issue_description" not in results:
        # fallback: use first 200 chars
        results["issue_description"] = email_text.strip()[:200]

    return validate_parsed_data(results)

# ----------------------------
# DEEPSEEK AI FUNCTIONS
# ----------------------------
def deepseek_call(messages, temperature=0.2, max_tokens=600):
    if not DEEPSEEK_API_KEY:
        return None, "No API key"

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }

    try:
        r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            return None, f"DeepSeek error {r.status_code}"
        data = r.json()
        return data["choices"][0]["message"]["content"], None
    except Exception as e:
        return None, str(e)

def deepseek_parse_email(email_text: str):
    if not DEEPSEEK_API_KEY:
        return simple_parse_email(email_text)

    system_prompt = """
You are an AI assistant for a fiber field management system.
Parse an Elauwit work order email and return ONLY valid JSON with:
{
  "ticket_id": "T-109040 or null",
  "property_code": "ARVA1850 or similar",
  "unit_number": "C-508 or similar",
  "resident_name": "Name or null",
  "issue_description": "Detailed issue description",
  "priority": "urgent/high/normal",
  "extracted_notes": "Any extra notes"
}
Return JSON only. No markdown.
""".strip()

    user_prompt = f"EMAIL:\n{email_text}\n\nReturn the JSON now."

    content, err = deepseek_call(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=500,
    )

    if not content:
        return simple_parse_email(email_text)

    # Extract JSON block
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return simple_parse_email(email_text)

    try:
        parsed = json.loads(m.group(0))
        validated = validate_parsed_data(parsed)
        return {"success": True, "data": validated, "source": "deepseek_ai"}
    except Exception:
        return simple_parse_email(email_text)

def deepseek_generate_report(report_data: dict):
    if not DEEPSEEK_API_KEY:
        return "AI not enabled. Add DEEPSEEK_API_KEY in Streamlit Secrets."

    prompt = f"""
Generate a professional HGHI Tech performance report.

DATA (JSON):
{json.dumps(report_data, indent=2)}

Include:
1) Executive Summary
2) Key Metrics
3) Notable Issues / Patterns
4) Recommendations
5) Next Steps

Use headings and bullet points.
""".strip()

    content, err = deepseek_call(
        [{"role": "user", "content": prompt}],
        temperature=0.25,
        max_tokens=900,
    )
    return content if content else f"AI report failed: {err}"

# ----------------------------
# BATCH OPERATIONS
# ----------------------------
def batch_assign_tickets(ticket_ids, contractor_id):
    """Assign multiple tickets to a contractor"""
    conn = connect_db()
    c = conn.cursor()
    success_count = 0
    
    for ticket_id in ticket_ids:
        try:
            c.execute("""
                UPDATE work_orders 
                SET contractor_id=?, assigned_date=?, status='in_progress'
                WHERE ticket_id=?
            """, (contractor_id, now_str(), ticket_id.strip()))
            success_count += 1
            
            # Log audit
            log_audit(
                st.session_state.user["id"],
                "BATCH_ASSIGN",
                f"Assigned ticket {ticket_id} to contractor {contractor_id}"
            )
        except Exception as e:
            print(f"Failed to assign {ticket_id}: {e}")
    
    conn.commit()
    conn.close()
    return success_count

def batch_approve_time_entries(entry_ids):
    """Approve multiple time entries"""
    conn = connect_db()
    c = conn.cursor()
    success_count = 0
    
    for entry_id in entry_ids:
        try:
            c.execute("""
                UPDATE time_entries 
                SET approved=1, verified=1
                WHERE id=?
            """, (entry_id,))
            success_count += 1
            
            # Log audit
            log_audit(
                st.session_state.user["id"],
                "BATCH_APPROVE_TIME",
                f"Approved time entry {entry_id}"
            )
        except Exception as e:
            print(f"Failed to approve entry {entry_id}: {e}")
    
    conn.commit()
    conn.close()
    return success_count

# ----------------------------
# DATABASE INIT + SEED USERS
# ----------------------------
def init_database():
    conn = connect_db()
    c = conn.cursor()

    # contractors
    c.execute("""
    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        phone TEXT,
        hourly_rate REAL DEFAULT 35.00,
        role TEXT DEFAULT 'pending',
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_by INTEGER,
        approved_at TIMESTAMP
    )
    """)

    # time entries
    c.execute("""
    CREATE TABLE IF NOT EXISTS time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        clock_in TIMESTAMP NOT NULL,
        clock_out TIMESTAMP,
        location TEXT,
        hours_worked REAL,
        verified BOOLEAN DEFAULT 0,
        approved BOOLEAN DEFAULT 0,
        FOREIGN KEY(contractor_id) REFERENCES contractors(id)
    )
    """)

    # buildings
    c.execute("""
    CREATE TABLE IF NOT EXISTS buildings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        property_manager TEXT,
        total_units INTEGER,
        status TEXT DEFAULT 'active'
    )
    """)

    # units
    c.execute("""
    CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        building_id INTEGER NOT NULL,
        unit_number TEXT NOT NULL,
        resident_name TEXT,
        unit_type TEXT,
        status TEXT DEFAULT 'occupied',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(building_id) REFERENCES buildings(id)
    )
    """)

    # work orders
    c.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT UNIQUE,
        unit_id INTEGER NOT NULL,
        contractor_id INTEGER,
        description TEXT NOT NULL,
        priority TEXT DEFAULT 'normal',
        status TEXT DEFAULT 'open',
        created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        assigned_date TIMESTAMP,
        completed_date TIMESTAMP,
        email_text TEXT,
        FOREIGN KEY(unit_id) REFERENCES units(id),
        FOREIGN KEY(contractor_id) REFERENCES contractors(id)
    )
    """)

    # service history
    c.execute("""
    CREATE TABLE IF NOT EXISTS service_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER NOT NULL,
        contractor_id INTEGER NOT NULL,
        work_order_id INTEGER,
        service_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        service_type TEXT,
        equipment_serial TEXT,
        notes TEXT,
        speed_test_download REAL,
        speed_test_upload REAL,
        speed_test_ping REAL,
        FOREIGN KEY(unit_id) REFERENCES units(id),
        FOREIGN KEY(contractor_id) REFERENCES contractors(id),
        FOREIGN KEY(work_order_id) REFERENCES work_orders(id)
    )
    """)

    # equipment
    c.execute("""
    CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER NOT NULL,
        equipment_type TEXT,
        serial_number TEXT UNIQUE,
        manufacturer TEXT,
        model TEXT,
        installation_date DATE,
        last_service_date DATE,
        status TEXT DEFAULT 'active',
        notes TEXT,
        FOREIGN KEY(unit_id) REFERENCES units(id)
    )
    """)

    # unit notes
    c.execute("""
    CREATE TABLE IF NOT EXISTS unit_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER NOT NULL,
        contractor_id INTEGER,
        note_type TEXT,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(unit_id) REFERENCES units(id),
        FOREIGN KEY(contractor_id) REFERENCES contractors(id)
    )
    """)

    # notifications
    c.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        type TEXT DEFAULT 'info',
        read BOOLEAN DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES contractors(id)
    )
    """)

    # payroll
    c.execute("""
    CREATE TABLE IF NOT EXISTS payroll (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        period_start DATE NOT NULL,
        period_end DATE NOT NULL,
        total_hours REAL DEFAULT 0,
        total_pay REAL DEFAULT 0,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_by INTEGER,
        paid_date DATE,
        FOREIGN KEY(contractor_id) REFERENCES contractors(id)
    )
    """)

    # AUDIT LOG TABLE (NEW)
    c.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        details TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES contractors(id)
    )
    """)

    # ----------------------------
    # SEED: REAL TEAM USERS
    # ----------------------------
    # Store demo credentials in environment-friendly way
    demo_users = {
        "darrell@hghitech.com": "owner123",
        "brandon@hghitech.com": "super123", 
        "andre@hghitech.com": "super123",
        "walter@hghitech.com": "tech123",
        "rasheed@hghitech.com": "tech123",
        "dale@hghitech.com": "tech123",
        "tuesuccess3@gmail.com": "admin123"
    }
    
    users = [
        # name, email, password, role, status, rate
        ("Darrell Kelly",  "darrell@hghitech.com",  demo_users.get("darrell@hghitech.com", "owner123"), "owner",      "active", 0),
        ("Brandon Alves",  "brandon@hghitech.com",  demo_users.get("brandon@hghitech.com", "super123"), "supervisor", "active", 0),
        ("Andre Ampey",    "andre@hghitech.com",    demo_users.get("andre@hghitech.com", "super123"),   "supervisor", "active", 0),
        ("Walter Chandler","walter@hghitech.com",   demo_users.get("walter@hghitech.com", "tech123"),   "technician", "active", 40.00),
        ("Rasheed Rouse",  "rasheed@hghitech.com",  demo_users.get("rasheed@hghitech.com", "tech123"),  "technician", "active", 40.00),
        ("Dale Vester",    "dale@hghitech.com",     demo_users.get("dale@hghitech.com", "tech123"),     "technician", "active", 40.00),
        ("Admin",          "tuesuccess3@gmail.com", demo_users.get("tuesuccess3@gmail.com", "admin123"), "admin",      "active", 0),
    ]

    for name, email, password, role, status, rate in users:
        c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email,))
        if c.fetchone()[0] == 0:
            c.execute("""
                INSERT INTO contractors (name, email, password_hash, role, status, hourly_rate, approved_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, email, hash_password(password), role, status, float(rate), 1))

    # Seed sample buildings/units if empty
    c.execute("SELECT COUNT(*) FROM buildings")
    if c.fetchone()[0] == 0:
        sample_buildings = [
            ("ARVA1850 - Cortland on Pike", "1234 Pike Street, Arlington, VA", "Elauwit", 350),
            ("Tysons Corner Plaza", "5678 Tysons Blvd, McLean, VA", "Elauwit", 200),
            ("Ballston Commons", "9010 Wilson Blvd, Arlington, VA", "Verizon", 180),
        ]
        for b in sample_buildings:
            c.execute("INSERT INTO buildings (name, address, property_manager, total_units) VALUES (?, ?, ?, ?)", b)
            building_id = c.lastrowid
            # small demo units
            for floor in range(1, 4):
                for unit in range(1, 11):
                    unit_num = f"{chr(64+floor)}-{unit:03d}"
                    c.execute("""
                        INSERT INTO units (building_id, unit_number, resident_name, unit_type)
                        VALUES (?, ?, ?, ?)
                    """, (building_id, unit_num, f"Resident {floor}{unit:02d}", "apartment"))

    conn.commit()
    conn.close()
    
    # Add indexes after table creation
    add_indexes()

# ----------------------------
# AUTH / USERS
# ----------------------------
def verify_login(email, password):
    conn = connect_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, name, role, hourly_rate, status
        FROM contractors
        WHERE email=? AND password_hash=?
    """, (email.strip().lower(), hash_password(password)))
    row = c.fetchone()
    conn.close()

    if not row:
        return None, "Invalid credentials"

    user = {"id": row[0], "name": row[1], "role": row[2], "hourly_rate": row[3], "status": row[4]}
    if user["status"] == "pending":
        return None, "Account pending approval. Contact supervisor."
    if user["status"] == "inactive":
        return None, "Account inactive. Contact supervisor."
    
    # Log successful login
    log_audit(user["id"], "LOGIN", f"User logged in from IP")
    return user, "Success"

def register_contractor(name, email, password, phone, hourly_rate):
    conn = connect_db()
    c = conn.cursor()

    email_norm = email.strip().lower()

    c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email_norm,))
    if c.fetchone()[0] > 0:
        conn.close()
        return False, "Email already registered"

    # Validate password complexity
    is_valid, msg = validate_password(password)
    if not is_valid:
        conn.close()
        return False, msg

    rate = safe_float(hourly_rate, 0)
    if rate < 15 or rate > 100:
        conn.close()
        return False, "Hourly rate must be between $15 and $100"

    c.execute("""
        INSERT INTO contractors (name, email, password_hash, phone, hourly_rate, role, status)
        VALUES (?, ?, ?, ?, ?, 'technician', 'pending')
    """, (name.strip(), email_norm, hash_password(password), phone.strip(), rate))

    # notify supervisors + owner
    c.execute("SELECT id FROM contractors WHERE role IN ('supervisor','owner','admin')")
    for (uid,) in c.fetchall():
        c.execute("""
            INSERT INTO notifications (user_id, message, type)
            VALUES (?, ?, 'warning')
        """, (uid, f"New contractor registration: {name} (${rate:.2f}/hr)"))

    conn.commit()
    conn.close()
    return True, "Registration submitted for supervisor approval"

# ----------------------------
# PAYROLL
# ----------------------------
def calculate_payroll(contractor_id, start_date, end_date):
    conn = connect_db()
    q = """
    SELECT te.clock_in, te.clock_out, te.hours_worked, te.approved, c.hourly_rate
    FROM time_entries te
    JOIN contractors c ON te.contractor_id = c.id
    WHERE te.contractor_id=?
      AND DATE(te.clock_in) BETWEEN ? AND ?
      AND te.clock_out IS NOT NULL
    ORDER BY te.clock_in
    """
    df = pd.read_sql_query(q, conn, params=(contractor_id, start_date, end_date))
    conn.close()
    if df.empty:
        return None

    total_hours = float(df["hours_worked"].sum())
    rate = float(df["hourly_rate"].iloc[0])

    regular = min(total_hours, 40.0)
    overtime = max(total_hours - 40.0, 0.0)

    regular_pay = regular * rate
    overtime_pay = overtime * rate * 1.5
    total_pay = regular_pay + overtime_pay

    return {
        "total_hours": total_hours,
        "regular_hours": regular,
        "overtime_hours": overtime,
        "hourly_rate": rate,
        "regular_pay": regular_pay,
        "overtime_pay": overtime_pay,
        "total_pay": total_pay,
        "period": f"{start_date} to {end_date}",
    }

# ----------------------------
# UNIT HISTORY
# ----------------------------
def get_unit_service_history(unit_id):
    conn = connect_db()
    q = """
    SELECT sh.service_date, sh.service_type, sh.equipment_serial, sh.notes,
           sh.speed_test_download, sh.speed_test_upload, sh.speed_test_ping,
           c.name as contractor_name, wo.ticket_id
    FROM service_history sh
    LEFT JOIN contractors c ON sh.contractor_id = c.id
    LEFT JOIN work_orders wo ON sh.work_order_id = wo.id
    WHERE sh.unit_id=?
    ORDER BY sh.service_date DESC
    """
    df = pd.read_sql_query(q, conn, params=(unit_id,))
    conn.close()
    return df

def get_unit_equipment(unit_id):
    conn = connect_db()
    q = """
    SELECT id, equipment_type, serial_number, manufacturer, model,
           installation_date, last_service_date, status, notes
    FROM equipment
    WHERE unit_id=?
    ORDER BY equipment_type
    """
    df = pd.read_sql_query(q, conn, params=(unit_id,))
    conn.close()
    return df

def get_unit_notes(unit_id):
    conn = connect_db()
    q = """
    SELECT un.note_type, un.content, un.created_at, c.name as contractor_name
    FROM unit_notes un
    LEFT JOIN contractors c ON un.contractor_id = c.id
    WHERE un.unit_id=?
    ORDER BY un.created_at DESC
    """
    df = pd.read_sql_query(q, conn, params=(unit_id,))
    conn.close()
    return df

# ----------------------------
# REAL-TIME NOTIFICATIONS
# ----------------------------
def get_realtime_updates(user_id):
    """Check for new tickets, messages, approvals"""
    conn = connect_db()
    
    # Get unread notifications
    c = conn.cursor()
    c.execute("""
        SELECT COUNT(*) as unread_count 
        FROM notifications 
        WHERE user_id=? AND read=0
    """, (user_id,))
    unread = c.fetchone()[0]
    
    # Get recent tickets assigned
    c.execute("""
        SELECT COUNT(*) as new_tickets
        FROM work_orders 
        WHERE contractor_id=? AND status='open' 
        AND assigned_date > datetime('now', '-1 hour')
    """, (user_id,))
    new_tickets = c.fetchone()[0]
    
    conn.close()
    
    return {
        "unread_notifications": unread,
        "new_tickets_last_hour": new_tickets
    }

# ============================================================
# STREAMLIT APP START
# ============================================================

st.set_page_config(
    page_title=f"{COMPANY_NAME} Field System",
    page_icon="🏢",
    layout="wide"
)

# Initialize DB once
init_database()

# ----------------------------
# SESSION STATE DEFAULTS
# ----------------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None
if "clocked_in" not in st.session_state:
    st.session_state.clocked_in = False
if "current_time_entry" not in st.session_state:
    st.session_state.current_time_entry = None
if "show_registration" not in st.session_state:
    st.session_state.show_registration = False
if "current_page" not in st.session_state:
    st.session_state.current_page = "dashboard"
if "ai_enabled" not in st.session_state:
    st.session_state.ai_enabled = bool(DEEPSEEK_API_KEY)
if "last_activity" not in st.session_state:
    st.session_state.last_activity = datetime.now()
if "real_time_updates" not in st.session_state:
    st.session_state.real_time_updates = {"last_check": datetime.now()}

# IMPORTANT: These keys are NOT bound to widgets directly
# so we can safely change them from demo buttons.
if "prefill_email" not in st.session_state:
    st.session_state.prefill_email = ""
if "prefill_password" not in st.session_state:
    st.session_state.prefill_password = ""

# Check session timeout
check_session_timeout()

# ----------------------------
# STYLE
# ----------------------------
st.markdown("""
<style>
.hct-header{
    background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
    color: white;
    padding: 22px;
    border-radius: 14px;
    margin-bottom: 16px;
}
.role-badge{
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.85rem;
    font-weight: 700;
    display: inline-block;
}
.role-owner{ background:#fef3c7; color:#92400e; }
.role-supervisor{ background:#dbeafe; color:#1e40af; }
.role-admin{ background:#ede9fe; color:#5b21b6; }
.role-technician{ background:#d1fae5; color:#065f46; }
.role-pending{ background:#f3f4f6; color:#6b7280; }
.ticket-card{
    background:white;
    border:1px solid #e5e7eb;
    border-radius: 10px;
    padding: 14px;
    margin: 10px 0;
}
.ai-box{
    background:#f0f9ff;
    border-left: 4px solid #3b82f6;
    border-radius: 8px;
    padding: 12px;
}
/* Mobile responsive */
@media (max-width: 768px) {
    .mobile-stack { flex-direction: column !important; }
    .mobile-full { width: 100% !important; }
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# LOGIN / REGISTRATION
# ============================================================
if not st.session_state.logged_in:

    st.markdown(f"""
    <div class="hct-header" style="text-align:center;">
        <h1>🏢 {COMPANY_NAME} Tech Field System</h1>
        <h3>Login</h3>
    </div>
    """, unsafe_allow_html=True)

    colA, colB, colC = st.columns([1, 1.2, 1])

    with colB:
        if st.session_state.show_registration:
            st.subheader("🆕 Contractor Registration")

            with st.form("reg_form"):
                name = st.text_input("Full Name")
                email = st.text_input("Email")
                phone = st.text_input("Phone")
                hourly_rate = st.number_input("Desired Hourly Rate ($)", min_value=15.0, max_value=100.0, value=35.0, step=0.5)
                password = st.text_input("Password (min 8 chars, include uppercase, lowercase, number, special)", type="password")
                confirm = st.text_input("Confirm Password", type="password")
                submit = st.form_submit_button("Submit Registration", use_container_width=True)

            if submit:
                if not all([name, email, phone, password, confirm]):
                    st.error("Please fill all fields.")
                elif password != confirm:
                    st.error("Passwords do not match.")
                else:
                    ok, msg = register_contractor(name, email, password, phone, hourly_rate)
                    if ok:
                        st.success(msg)
                        st.info("A supervisor/owner will approve your account.")
                        st.session_state.show_registration = False
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(msg)

            if st.button("← Back to Login", use_container_width=True):
                st.session_state.show_registration = False
                st.rerun()

        else:
            st.subheader("🔐 Login")

            # Widgets use separate keys. We prefill from session_state.prefill_*
            email_input = st.text_input("Email", key="email_input", value=st.session_state.prefill_email)
            pass_input = st.text_input("Password", type="password", key="pass_input", value=st.session_state.prefill_password)

            col1, col2 = st.columns(2)
            with col1:
                if st.button("Login", type="primary", use_container_width=True):
                    user, msg = verify_login(email_input, pass_input)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.user = user
                        st.session_state.last_activity = datetime.now()

                        # Check if clocked in already
                        conn = connect_db()
                        c = conn.cursor()
                        c.execute("""
                            SELECT id, clock_in FROM time_entries
                            WHERE contractor_id=? AND clock_out IS NULL
                            ORDER BY id DESC LIMIT 1
                        """, (user["id"],))
                        row = c.fetchone()
                        conn.close()

                        if row:
                            st.session_state.clocked_in = True
                            st.session_state.current_time_entry = {
                                "id": row[0],
                                "clock_in": datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S"),
                            }

                        st.success(f"Welcome, {user['name']}!")
                        time.sleep(0.6)
                        st.rerun()
                    else:
                        st.error(msg)

            with col2:
                if st.button("New Contractor", use_container_width=True):
                    st.session_state.show_registration = True
                    st.rerun()

            st.divider()
            st.caption("Demo accounts (click to autofill):")

            # ✅ FIXED: no session_state crash because we prefill into different keys
            demo_cols = st.columns([1, 1, 1])
            with demo_cols[0]:
                if st.button("Owner Demo", use_container_width=True):
                    st.session_state.prefill_email = "darrell@hghitech.com"
                    st.session_state.prefill_password = "owner123"
                    st.rerun()

            with demo_cols[1]:
                if st.button("Supervisor Demo", use_container_width=True):
                    st.session_state.prefill_email = "brandon@hghitech.com"
                    st.session_state.prefill_password = "super123"
                    st.rerun()

            with demo_cols[2]:
                if st.button("Tech Demo", use_container_width=True):
                    st.session_state.prefill_email = "walter@hghitech.com"
                    st.session_state.prefill_password = "tech123"
                    st.rerun()

    st.stop()

# ============================================================
# MAIN APP (LOGGED IN)
# ============================================================
user = st.session_state.user
role = user["role"]
role_class = f"role-{role}" if role in ["owner", "supervisor", "technician", "admin"] else "role-pending"

# Update session activity
st.session_state.last_activity = datetime.now()

# Check for real-time updates (every 30 seconds)
current_time = datetime.now()
last_check = st.session_state.real_time_updates.get("last_check", current_time)
if (current_time - last_check).total_seconds() > 30:
    updates = get_realtime_updates(user["id"])
    st.session_state.real_time_updates = updates
    st.session_state.real_time_updates["last_check"] = current_time

# ----------------------------
# SIDEBAR
# ----------------------------
with st.sidebar:
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
                color:white; padding:16px; border-radius:12px;">
        <div style="font-size:1.1rem; font-weight:800;">👤 {user["name"]}</div>
        <div style="margin-top:6px;">
            <span class="role-badge {role_class}">{role.upper()}</span>
        </div>
        <div style="margin-top:8px;"><b>Rate:</b> ${user["hourly_rate"]}/hr</div>
        <div><b>Status:</b> {user["status"].title()}</div>
    </div>
    """, unsafe_allow_html=True)

    st.write("")
    if st.session_state.ai_enabled:
        st.success("🤖 DeepSeek AI: Enabled")
    else:
        st.warning("🤖 DeepSeek AI: Not configured (add DEEPSEEK_API_KEY in Secrets)")

    st.divider()

    # Notifications
    unread = st.session_state.real_time_updates.get("unread_notifications", 0)
    if unread:
        st.info(f"📢 Notifications: {unread}")

    # Time Clock
    st.markdown("### ⏱️ Time Clock")
    if st.session_state.clocked_in:
        clock_in = st.session_state.current_time_entry["clock_in"]
        hours = (datetime.now() - clock_in).total_seconds() / 3600.0
        st.markdown(f"<div style='font-size:1.8rem;font-weight:800;color:#10b981;text-align:center;'>{hours:.2f}h</div>", unsafe_allow_html=True)
        st.caption(f"Clocked in: {clock_in.strftime('%I:%M %p')}")
        if st.button("🛑 Clock Out", use_container_width=True):
            conn = connect_db()
            c = conn.cursor()
            c.execute("UPDATE time_entries SET clock_out=CURRENT_TIMESTAMP, hours_worked=? WHERE id=?",
                      (hours, st.session_state.current_time_entry["id"]))
            
            # Log audit
            log_audit(
                user["id"],
                "CLOCK_OUT",
                f"Clocked out after {hours:.2f} hours"
            )
            
            conn.commit()
            conn.close()
            st.session_state.clocked_in = False
            st.session_state.current_time_entry = None
            st.success("Clocked out.")
            time.sleep(0.5)
            st.rerun()
    else:
        if st.button("⏰ Clock In", type="primary", use_container_width=True):
            conn = connect_db()
            c = conn.cursor()
            c.execute("INSERT INTO time_entries (contractor_id, clock_in, location) VALUES (?, CURRENT_TIMESTAMP, ?)",
                      (user["id"], "Field Location"))
            
            # Log audit
            log_audit(
                user["id"],
                "CLOCK_IN",
                "Clocked in at field location"
            )
            
            conn.commit()
            c.execute("""
                SELECT id, clock_in FROM time_entries
                WHERE contractor_id=? AND clock_out IS NULL
                ORDER BY id DESC LIMIT 1
            """, (user["id"],))
            row = c.fetchone()
            conn.close()
            if row:
                st.session_state.clocked_in = True
                st.session_state.current_time_entry = {
                    "id": row[0],
                    "clock_in": datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S"),
                }
            st.success("Clocked in.")
            time.sleep(0.5)
            st.rerun()

    st.divider()

    # NAV
    st.markdown("### 📱 Navigation")
    if role in ["owner", "supervisor", "admin"]:
        nav = [
            ("dashboard", "📊 Dashboard"),
            ("ticket", "📋 Ticket Manager"),
            ("unit", "🏢 Unit Explorer"),
            ("batch", "⚡ Batch Operations"),
            ("ai", "🤖 AI Assistant"),
            ("admin", "⚙️ Admin Tools"),
        ]
    else:
        nav = [
            ("dashboard", "📊 My Dashboard"),
            ("ticket", "📋 My Assignments"),
            ("unit", "🏢 My Units"),
        ]

    for key, label in nav:
        if st.button(label, use_container_width=True):
            st.session_state.current_page = key
            st.rerun()

    st.divider()
    if st.button("🚪 Logout", use_container_width=True):
        # Log audit
        log_audit(user["id"], "LOGOUT", "User logged out")
        
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.clocked_in = False
        st.session_state.current_time_entry = None
        st.session_state.current_page = "dashboard"
        st.rerun()

# ----------------------------
# HEADER
# ----------------------------
st.markdown(f"""
<div class="hct-header">
  <h1>🏢 {COMPANY_NAME} Field Management</h1>
  <h3>Welcome back, {user["name"]} • {datetime.now().strftime("%A, %B %d, %Y")}</h3>
</div>
""", unsafe_allow_html=True)

page = st.session_state.current_page

# ============================================================
# DASHBOARD
# ============================================================
if page == "dashboard":
    if role in ["owner", "supervisor", "admin"]:
        st.subheader(f"👑 {role.upper()} DASHBOARD")

        conn = connect_db()

        team_stats = pd.read_sql_query("""
            SELECT
              SUM(CASE WHEN status='active' AND role='technician' THEN 1 ELSE 0 END) AS active_techs,
              SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) AS pending_approvals,
              AVG(CASE WHEN role='technician' THEN hourly_rate ELSE NULL END) AS avg_rate
            FROM contractors
        """, conn).iloc[0]

        work_stats = pd.read_sql_query("""
            SELECT
              SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_jobs,
              SUM(CASE WHEN status='in_progress' THEN 1 ELSE 0 END) AS in_progress_jobs,
              SUM(CASE WHEN status='completed' AND DATE(completed_date)=DATE('now') THEN 1 ELSE 0 END) AS completed_today
            FROM work_orders
        """, conn).iloc[0]

        # Recent audit logs
        audit_logs = pd.read_sql_query("""
            SELECT a.action, a.details, a.timestamp, c.name as user_name
            FROM audit_log a
            JOIN contractors c ON a.user_id = c.id
            ORDER BY a.timestamp DESC
            LIMIT 5
        """, conn)

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Active Techs", int(team_stats["active_techs"] or 0))
        col2.metric("Pending Approvals", int(team_stats["pending_approvals"] or 0))
        col3.metric("Open Jobs", int(work_stats["open_jobs"] or 0))
        col4.metric("Completed Today", int(work_stats["completed_today"] or 0))

        st.divider()
        
        # Recent Activity (Audit Logs)
        with st.expander("📜 Recent Activity Logs", expanded=True):
            if not audit_logs.empty:
                for _, r in audit_logs.iterrows():
                    st.markdown(f"""
                    <div style="padding:8px; border-bottom:1px solid #e5e7eb;">
                      <b>{r['action']}</b> • {r['user_name']}<br/>
                      <small>{r['details'] or ''}</small><br/>
                      <small style="color:#6b7280;">{r['timestamp']}</small>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("No recent activity")

        st.subheader("📋 Recent Tickets")

        recent = pd.read_sql_query("""
            SELECT wo.ticket_id, wo.description, wo.status, wo.priority,
                   b.name AS property, u.unit_number, c.name AS contractor,
                   wo.created_date
            FROM work_orders wo
            JOIN units u ON wo.unit_id = u.id
            JOIN buildings b ON u.building_id = b.id
            LEFT JOIN contractors c ON wo.contractor_id = c.id
            ORDER BY wo.created_date DESC
            LIMIT 10
        """, conn)
        conn.close()

        if recent.empty:
            st.info("No tickets yet.")
        else:
            for _, r in recent.iterrows():
                st.markdown(f"""
                <div class="ticket-card">
                  <b>{r['ticket_id']}</b> • {r['property']} • Unit {r['unit_number']}<br/>
                  <b>Priority:</b> {str(r['priority']).upper()} • <b>Status:</b> {str(r['status']).replace('_',' ').title()}<br/>
                  <b>Assigned:</b> {r['contractor'] if pd.notna(r['contractor']) else 'Unassigned'}<br/>
                  <div style="margin-top:6px;color:#374151;">{str(r['description'])[:160]}</div>
                </div>
                """, unsafe_allow_html=True)

    else:
        st.subheader("👷 TECHNICIAN DASHBOARD")

        col1, col2, col3 = st.columns(3)
        col1.metric("My Rate", f"${user['hourly_rate']:.2f}")

        month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
        payroll = calculate_payroll(user["id"], month_start, datetime.now().strftime("%Y-%m-%d"))
        col2.metric("This Month Est.", f"${payroll['total_pay']:.0f}" if payroll else "$0")

        conn = connect_db()
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(*) FROM work_orders
            WHERE contractor_id=? AND status IN ('open','in_progress')
        """, (user["id"],))
        active_jobs = c.fetchone()[0]
        conn.close()
        col3.metric("Active Jobs", int(active_jobs))

        # Recent work
        st.divider()
        st.subheader("Recent Work History")
        conn = connect_db()
        recent_work = pd.read_sql_query("""
            SELECT wo.ticket_id, wo.description, wo.completed_date,
                   b.name as property, u.unit_number
            FROM work_orders wo
            JOIN units u ON wo.unit_id = u.id
            JOIN buildings b ON u.building_id = b.id
            WHERE wo.contractor_id=? AND wo.status='completed'
            ORDER BY wo.completed_date DESC
            LIMIT 5
        """, conn, params=(user["id"],))
        conn.close()
        
        if not recent_work.empty:
            for _, r in recent_work.iterrows():
                st.markdown(f"""
                <div style="padding:10px; border:1px solid #e5e7eb; border-radius:8px; margin-bottom:8px;">
                  <b>{r['ticket_id']}</b> • {r['property']} - {r['unit_number']}<br/>
                  <small>{str(r['description'])[:100]}...</small><br/>
                  <small style="color:#6b7280;">Completed: {r['completed_date']}</small>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No completed work yet")

# ============================================================
# TICKET MANAGER
# ============================================================
elif page == "ticket":
    if role in ["owner", "supervisor", "admin"]:
        st.subheader("📋 Ticket Manager")
        tab1, tab2 = st.tabs(["📧 Email Parser", "📝 Manual Ticket"])

        with tab1:
            st.write("Paste Elauwit email, then parse + create ticket.")
            email_text = st.text_area("Email text", height=220)

            colA, colB = st.columns(2)
            use_ai = colA.checkbox("Use DeepSeek AI parser", value=st.session_state.ai_enabled)
            save_email = colB.checkbox("Save original email in DB", value=True)

            if st.button("Parse Email", type="primary", disabled=not email_text.strip()):
                with st.spinner("Parsing..."):
                    result = deepseek_parse_email(email_text) if use_ai else simple_parse_email(email_text)
                    data = result["data"] if isinstance(result, dict) else result

                st.success(f"Parsed via: {result.get('source', 'simple_parser')}" if isinstance(result, dict) else "Parsed via simple parser")
                st.json(data)

                # Create ticket form
                st.markdown("### Create Work Order")
                conn = connect_db()
                props = pd.read_sql_query("SELECT id, name FROM buildings ORDER BY name", conn)

                ticket_id_default = data.get("ticket_id") or f"T-{int(time.time())}"
                ticket_id = st.text_input("Ticket ID", value=ticket_id_default)

                selected_property = st.selectbox("Property", props["name"].tolist())
                prop_id = int(props[props["name"] == selected_property].iloc[0]["id"])

                units = pd.read_sql_query("""
                    SELECT id, unit_number, resident_name
                    FROM units WHERE building_id=?
                    ORDER BY unit_number
                """, conn, params=(prop_id,))

                unit_default = data.get("unit_number")
                unit_index = 0
                if unit_default:
                    matches = units.index[units["unit_number"].str.contains(unit_default, na=False)].tolist()
                    if matches:
                        unit_index = matches[0]

                selected_unit = st.selectbox("Unit", units["unit_number"].tolist(), index=unit_index)
                unit_id = int(units[units["unit_number"] == selected_unit].iloc[0]["id"])

                desc_default = data.get("issue_description") or ""
                description = st.text_area("Description", value=desc_default, height=110)

                pr = data.get("priority", "normal").lower()
                if pr not in ["normal", "high", "urgent"]:
                    pr = "normal"
                priority = st.selectbox("Priority", ["normal", "high", "urgent"], index=["normal", "high", "urgent"].index(pr))

                techs = pd.read_sql_query("""
                    SELECT id, name FROM contractors
                    WHERE status='active' AND role='technician'
                    ORDER BY name
                """, conn)
                assigned_name = st.selectbox("Assign to", ["Unassigned"] + techs["name"].tolist())
                conn.close()

                if st.button("Create Work Order", type="primary"):
                    conn = connect_db()
                    c = conn.cursor()

                    contractor_id = None
                    if assigned_name != "Unassigned":
                        c.execute("SELECT id FROM contractors WHERE name=?", (assigned_name,))
                        row = c.fetchone()
                        contractor_id = row[0] if row else None

                    email_to_save = email_text if save_email else None
                    c.execute("""
                        INSERT INTO work_orders (ticket_id, unit_id, contractor_id, description, priority, status, email_text, assigned_date)
                        VALUES (?, ?, ?, ?, ?, 'open', ?, ?)
                    """, (ticket_id, unit_id, contractor_id, description, priority, email_to_save, now_str() if contractor_id else None))

                    # Log audit
                    log_audit(
                        user["id"],
                        "CREATE_TICKET",
                        f"Created ticket {ticket_id} for unit {selected_unit}"
                    )

                    conn.commit()
                    conn.close()
                    st.success(f"✅ Created work order {ticket_id}")
                    time.sleep(0.7)
                    st.rerun()

        with tab2:
            st.markdown("### Manual Ticket Entry")
            conn = connect_db()
            props = pd.read_sql_query("SELECT id, name FROM buildings ORDER BY name", conn)
            selected_property = st.selectbox("Property", props["name"].tolist(), key="manual_prop")
            prop_id = int(props[props["name"] == selected_property].iloc[0]["id"])
            units = pd.read_sql_query("SELECT id, unit_number FROM units WHERE building_id=? ORDER BY unit_number", conn, params=(prop_id,))
            selected_unit = st.selectbox("Unit", units["unit_number"].tolist(), key="manual_unit")
            unit_id = int(units[units["unit_number"] == selected_unit].iloc[0]["id"])

            ticket_id = st.text_input("Ticket ID", value=f"T-{int(time.time())}", key="manual_ticket")
            description = st.text_area("Description", height=120, key="manual_desc")
            priority = st.selectbox("Priority", ["normal", "high", "urgent"], key="manual_pri")

            techs = pd.read_sql_query("""
                SELECT id, name FROM contractors
                WHERE status='active' AND role='technician'
                ORDER BY name
            """, conn)
            assigned_name = st.selectbox("Assign to", ["Unassigned"] + techs["name"].tolist(), key="manual_assign")
            conn.close()

            if st.button("Create Ticket", type="primary", key="manual_create"):
                conn = connect_db()
                c = conn.cursor()
                contractor_id = None
                if assigned_name != "Unassigned":
                    c.execute("SELECT id FROM contractors WHERE name=?", (assigned_name,))
                    row = c.fetchone()
                    contractor_id = row[0] if row else None

                c.execute("""
                    INSERT INTO work_orders (ticket_id, unit_id, contractor_id, description, priority, status, assigned_date)
                    VALUES (?, ?, ?, ?, ?, 'open', ?)
                """, (ticket_id, unit_id, contractor_id, description, priority, now_str() if contractor_id else None))
                
                # Log audit
                log_audit(
                    user["id"],
                    "CREATE_TICKET",
                    f"Created manual ticket {ticket_id}"
                )
                
                conn.commit()
                conn.close()
                st.success(f"✅ Ticket created: {ticket_id}")
                time.sleep(0.7)
                st.rerun()

    else:
        st.subheader("📋 My Assignments")
        conn = connect_db()
        df = pd.read_sql_query("""
            SELECT wo.ticket_id, wo.description, wo.priority, wo.status,
                   b.name as property, u.unit_number, wo.created_date
            FROM work_orders wo
            JOIN units u ON wo.unit_id=u.id
            JOIN buildings b ON u.building_id=b.id
            WHERE wo.contractor_id=?
            ORDER BY wo.created_date DESC
        """, conn, params=(user["id"],))
        conn.close()

        if df.empty:
            st.info("No assignments yet.")
        else:
            for _, r in df.iterrows():
                st.markdown(f"""
                <div class="ticket-card">
                  <b>{r['ticket_id']}</b> • {r['property']} • Unit {r['unit_number']}<br/>
                  <b>Priority:</b> {str(r['priority']).upper()} • <b>Status:</b> {str(r['status']).replace('_',' ').title()}<br/>
                  <div style="margin-top:6px;color:#374151;">{str(r['description'])[:200]}</div>
                </div>
                """, unsafe_allow_html=True)

# ============================================================
# BATCH OPERATIONS (NEW)
# ============================================================
elif page == "batch" and role in ["owner", "supervisor", "admin"]:
    st.subheader("⚡ Batch Operations")
    
    tab1, tab2, tab3 = st.tabs(["📋 Bulk Assign Tickets", "⏱️ Bulk Approve Time", "📤 Bulk Export"])
    
    with tab1:
        st.markdown("### Bulk Ticket Assignment")
        
        conn = connect_db()
        
        # Get unassigned tickets
        unassigned = pd.read_sql_query("""
            SELECT wo.ticket_id, wo.description, wo.created_date,
                   b.name as property, u.unit_number
            FROM work_orders wo
            JOIN units u ON wo.unit_id = u.id
            JOIN buildings b ON u.building_id = b.id
            WHERE wo.contractor_id IS NULL AND wo.status = 'open'
            ORDER BY wo.created_date DESC
        """, conn)
        
        # Get available technicians
        techs = pd.read_sql_query("""
            SELECT id, name, hourly_rate 
            FROM contractors 
            WHERE status='active' AND role='technician'
            ORDER BY name
        """, conn)
        
        if unassigned.empty:
            st.info("No unassigned tickets found.")
        else:
            # Multiselect for tickets
            ticket_options = unassigned.apply(
                lambda x: f"{x['ticket_id']} - {x['property']} {x['unit_number']} ({x['created_date'][:10]})", 
                axis=1
            ).tolist()
            
            selected_tickets = st.multiselect(
                "Select Tickets to Assign",
                options=ticket_options,
                default=ticket_options[:3] if len(ticket_options) > 3 else ticket_options
            )
            
            # Extract ticket IDs
            ticket_ids = [t.split(" - ")[0] for t in selected_tickets]
            
            # Select technician
            tech_options = {f"{row['name']} (${row['hourly_rate']}/hr)": row['id'] for _, row in techs.iterrows()}
            selected_tech_name = st.selectbox("Assign to Technician", list(tech_options.keys()))
            tech_id = tech_options[selected_tech_name]
            
            if st.button("🔄 Assign Selected Tickets", type="primary", disabled=not selected_tickets):
                with st.spinner(f"Assigning {len(ticket_ids)} tickets..."):
                    success_count = batch_assign_tickets(ticket_ids, tech_id)
                    
                st.success(f"✅ Successfully assigned {success_count} out of {len(ticket_ids)} tickets")
                time.sleep(1)
                st.rerun()
            
            # Show selected tickets
            if selected_tickets:
                st.markdown("### Selected Tickets")
                for ticket in selected_tickets:
                    st.markdown(f"- {ticket}")
        
        conn.close()
    
    with tab2:
        st.markdown("### Bulk Time Entry Approval")
        
        conn = connect_db()
        
        # Get pending time entries
        pending_time = pd.read_sql_query("""
            SELECT te.id, te.clock_in, te.clock_out, te.hours_worked, te.location,
                   c.name as contractor_name, c.hourly_rate
            FROM time_entries te
            JOIN contractors c ON te.contractor_id = c.id
            WHERE te.approved = 0 AND te.clock_out IS NOT NULL
            ORDER BY te.clock_in DESC
        """, conn)
        
        if pending_time.empty:
            st.info("No pending time entries for approval.")
        else:
            # Calculate estimated pay
            pending_time["estimated_pay"] = pending_time["hours_worked"] * pending_time["hourly_rate"]
            total_hours = pending_time["hours_worked"].sum()
            total_pay = pending_time["estimated_pay"].sum()
            
            st.metric("Total Pending Hours", f"{total_hours:.2f}")
            st.metric("Total Estimated Pay", f"${total_pay:.2f}")
            
            # Multiselect for time entries
            time_options = pending_time.apply(
                lambda x: f"ID {x['id']}: {x['contractor_name']} - {x['hours_worked']:.2f}h (${x['estimated_pay']:.2f}) - {x['clock_in'][:10]}", 
                axis=1
            ).tolist()
            
            selected_entries = st.multiselect(
                "Select Time Entries to Approve",
                options=time_options,
                default=time_options[:5] if len(time_options) > 5 else time_options
            )
            
            # Extract entry IDs
            entry_ids = [int(t.split("ID ")[1].split(":")[0]) for t in selected_entries]
            
            if st.button("✅ Approve Selected Time Entries", type="primary", disabled=not selected_entries):
                with st.spinner(f"Approving {len(entry_ids)} time entries..."):
                    success_count = batch_approve_time_entries(entry_ids)
                    
                st.success(f"✅ Successfully approved {success_count} out of {len(entry_ids)} time entries")
                time.sleep(1)
                st.rerun()
            
            # Show preview
            if selected_entries:
                st.markdown("### Selected Time Entries")
                for entry in selected_entries:
                    st.markdown(f"- {entry}")
        
        conn.close()
    
    with tab3:
        st.markdown("### Bulk Data Export")
        
        export_options = st.multiselect(
            "Select Data to Export",
            ["Work Orders", "Time Entries", "Service History", "Contractors", "Equipment"],
            default=["Work Orders", "Time Entries"]
        )
        
        col1, col2 = st.columns(2)
        start_date = col1.date_input("Start Date", datetime.now() - timedelta(days=30))
        end_date = col2.date_input("End Date", datetime.now())
        
        if st.button("📥 Export Selected Data", type="primary"):
            conn = connect_db()
            export_data = {}
            
            with st.spinner("Exporting data..."):
                if "Work Orders" in export_options:
                    work_df = pd.read_sql_query("""
                        SELECT wo.*, b.name as property, u.unit_number, c.name as contractor_name
                        FROM work_orders wo
                        JOIN units u ON wo.unit_id = u.id
                        JOIN buildings b ON u.building_id = b.id
                        LEFT JOIN contractors c ON wo.contractor_id = c.id
                        WHERE DATE(wo.created_date) BETWEEN ? AND ?
                    """, conn, params=(str(start_date), str(end_date)))
                    export_data["Work_Orders"] = work_df
                
                if "Time Entries" in export_options:
                    time_df = pd.read_sql_query("""
                        SELECT te.*, c.name as contractor_name, c.hourly_rate
                        FROM time_entries te
                        JOIN contractors c ON te.contractor_id = c.id
                        WHERE DATE(te.clock_in) BETWEEN ? AND ?
                    """, conn, params=(str(start_date), str(end_date)))
                    export_data["Time_Entries"] = time_df
                
                if "Service History" in export_options:
                    service_df = pd.read_sql_query("""
                        SELECT sh.*, b.name as property, u.unit_number, c.name as contractor_name
                        FROM service_history sh
                        JOIN units u ON sh.unit_id = u.id
                        JOIN buildings b ON u.building_id = b.id
                        JOIN contractors c ON sh.contractor_id = c.id
                        WHERE DATE(sh.service_date) BETWEEN ? AND ?
                    """, conn, params=(str(start_date), str(end_date)))
                    export_data["Service_History"] = service_df
                
                if "Contractors" in export_options:
                    contractors_df = pd.read_sql_query("SELECT * FROM contractors", conn)
                    export_data["Contractors"] = contractors_df
                
                if "Equipment" in export_options:
                    equipment_df = pd.read_sql_query("""
                        SELECT e.*, b.name as property, u.unit_number
                        FROM equipment e
                        JOIN units u ON e.unit_id = u.id
                        JOIN buildings b ON u.building_id = b.id
                    """, conn)
                    export_data["Equipment"] = equipment_df
            
            conn.close()
            
            # Create Excel file with multiple sheets
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                for sheet_name, df in export_data.items():
                    if not df.empty:
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
            
            output.seek(0)
            
            # Download button
            st.download_button(
                label="📥 Download Excel File",
                data=output,
                file_name=f"hghi_export_{start_date}_{end_date}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # Log audit
            log_audit(
                user["id"],
                "DATA_EXPORT",
                f"Exported {len(export_data)} datasets"
            )

# ============================================================
# UNIT EXPLORER
# ============================================================
elif page == "unit":
    st.subheader("🏢 Unit Explorer")

    conn = connect_db()
    props = pd.read_sql_query("SELECT id, name, address FROM buildings ORDER BY name", conn)
    if props.empty:
        conn.close()
        st.info("No properties yet.")
    else:
        selected_property = st.selectbox("Select Property", props["name"].tolist())
        prop_id = int(props[props["name"] == selected_property].iloc[0]["id"])

        units = pd.read_sql_query("""
            SELECT id, unit_number, resident_name, status, notes
            FROM units
            WHERE building_id=?
            ORDER BY unit_number
        """, conn, params=(prop_id,))

        if units.empty:
            conn.close()
            st.info("No units found for this property.")
        else:
            pick = st.selectbox(
                "Select Unit",
                units.apply(lambda x: f"{x['unit_number']} - {x['resident_name']}", axis=1).tolist()
            )
            unit_number = pick.split(" - ")[0].strip()
            unit_id = int(units[units["unit_number"] == unit_number].iloc[0]["id"])
            unit_row = units[units["id"] == unit_id].iloc[0]

            st.markdown(f"""
            <div class="ticket-card">
                <h4>Unit {unit_row['unit_number']}</h4>
                <b>Resident:</b> {unit_row['resident_name']}<br/>
                <b>Status:</b> {str(unit_row['status']).title()}<br/>
                <b>Notes:</b> {unit_row['notes'] if unit_row['notes'] else '—'}
            </div>
            """, unsafe_allow_html=True)

            tab1, tab2, tab3, tab4 = st.tabs(["📋 Service History", "🔧 Equipment", "📝 Notes", "➕ Add Service"])

            with tab1:
                hist = get_unit_service_history(unit_id)
                if hist.empty:
                    st.info("No service history yet.")
                else:
                    # Export button
                    excel_data = export_to_excel(hist, f"service_history_{unit_number}")
                    st.download_button(
                        label="📥 Export to Excel",
                        data=excel_data,
                        file_name=f"service_history_{unit_number}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    for _, v in hist.iterrows():
                        st.markdown(f"""
                        <div class="ticket-card">
                          <b>Date:</b> {v['service_date']}<br/>
                          <b>Type:</b> {v['service_type'] or 'General'} • <b>Tech:</b> {v['contractor_name'] or '—'} • <b>Ticket:</b> {v['ticket_id'] or '—'}<br/>
                          <b>Serial:</b> {v['equipment_serial'] or '—'}<br/>
                          <b>Speed:</b> {v['speed_test_download'] or '—'}↓ / {v['speed_test_upload'] or '—'}↑ / {v['speed_test_ping'] or '—'}ms<br/>
                          <b>Notes:</b> {v['notes'] or '—'}
                        </div>
                        """, unsafe_allow_html=True)

            with tab2:
                eq = get_unit_equipment(unit_id)
                if eq.empty:
                    st.info("No equipment recorded.")
                else:
                    for _, e in eq.iterrows():
                        with st.expander(f"{e['equipment_type']} • {e['serial_number']}"):
                            st.write(f"**Manufacturer:** {e['manufacturer'] or '—'}")
                            st.write(f"**Model:** {e['model'] or '—'}")
                            st.write(f"**Status:** {e['status'] or '—'}")
                            st.write(f"**Installed:** {e['installation_date'] or '—'}")
                            st.write(f"**Last Service:** {e['last_service_date'] or '—'}")
                            st.write(f"**Notes:** {e['notes'] or '—'}")

                st.divider()
                st.markdown("### ➕ Add Equipment")
                with st.form("add_equipment"):
                    equip_type = st.selectbox("Type", ["ONT", "Router", "AP", "Switch", "Modem", "Other"])
                    serial = st.text_input("Serial Number")
                    manu = st.text_input("Manufacturer")
                    model = st.text_input("Model")
                    status = st.selectbox("Status", ["active", "needs_service", "replaced"])
                    notes = st.text_area("Notes")
                    submitted = st.form_submit_button("Add Equipment")

                if submitted:
                    if not serial.strip():
                        st.error("Serial number required.")
                    else:
                        c = conn.cursor()
                        try:
                            c.execute("""
                                INSERT INTO equipment (unit_id, equipment_type, serial_number, manufacturer, model, status, notes)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """, (unit_id, equip_type, serial.strip(), manu.strip(), model.strip(), status, notes.strip()))
                            
                            # Log audit
                            log_audit(
                                user["id"],
                                "ADD_EQUIPMENT",
                                f"Added {equip_type} {serial} to unit {unit_number}"
                            )
                            
                            conn.commit()
                            st.success("Equipment added.")
                            time.sleep(0.6)
                            st.rerun()
                        except Exception as ex:
                            st.error(f"Could not add equipment: {ex}")

            with tab3:
                notes_df = get_unit_notes(unit_id)
                if notes_df.empty:
                    st.info("No notes yet.")
                else:
                    for _, n in notes_df.iterrows():
                        st.markdown(f"""
                        <div class="ticket-card">
                          <b>{str(n['note_type']).title()} Note</b> • <i>{n['created_at']}</i><br/>
                          <b>By:</b> {n['contractor_name'] or 'System'}<br/>
                          <div style="margin-top:6px;">{n['content']}</div>
                        </div>
                        """, unsafe_allow_html=True)

                st.divider()
                st.markdown("### ➕ Add Note")
                with st.form("add_note"):
                    note_type = st.selectbox("Note Type", ["general", "maintenance", "resident", "issue", "equipment"])
                    content = st.text_area("Content", height=100)
                    submit_note = st.form_submit_button("Add Note")
                if submit_note:
                    if not content.strip():
                        st.error("Note content required.")
                    else:
                        c = conn.cursor()
                        c.execute("""
                            INSERT INTO unit_notes (unit_id, contractor_id, note_type, content)
                            VALUES (?, ?, ?, ?)
                        """, (unit_id, user["id"], note_type, content.strip()))
                        
                        # Log audit
                        log_audit(
                            user["id"],
                            "ADD_NOTE",
                            f"Added {note_type} note to unit {unit_number}"
                        )
                        
                        conn.commit()
                        st.success("Note added.")
                        time.sleep(0.6)
                        st.rerun()

            with tab4:
                st.markdown("### ➕ Add Service Record")
                with st.form("add_service"):
                    service_type = st.selectbox("Service Type", ["Installation", "Repair", "Maintenance", "Inspection"])
                    ticket_ref = st.text_input("Ticket ID (optional)")
                    serial_ref = st.text_input("Equipment Serial (optional)")

                    colS1, colS2, colS3 = st.columns(3)
                    download = colS1.number_input("Download (Mbps)", min_value=0, value=850)
                    upload = colS2.number_input("Upload (Mbps)", min_value=0, value=850)
                    ping = colS3.number_input("Ping (ms)", min_value=0, value=8)

                    notes = st.text_area("Service Notes", height=130)
                    save = st.form_submit_button("Save Service Record")

                if save:
                    wo_id = None
                    if ticket_ref.strip():
                        c = conn.cursor()
                        c.execute("SELECT id FROM work_orders WHERE ticket_id=?", (ticket_ref.strip(),))
                        row = c.fetchone()
                        wo_id = row[0] if row else None

                    c = conn.cursor()
                    c.execute("""
                        INSERT INTO service_history
                        (unit_id, contractor_id, work_order_id, service_type, equipment_serial, notes,
                         speed_test_download, speed_test_upload, speed_test_ping)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (unit_id, user["id"], wo_id, service_type, serial_ref.strip(), notes.strip(),
                          float(download), float(upload), float(ping)))

                    if serial_ref.strip():
                        c.execute("""
                            UPDATE equipment SET last_service_date=CURRENT_DATE
                            WHERE unit_id=? AND serial_number=?
                        """, (unit_id, serial_ref.strip()))
                    
                    # Log audit
                    log_audit(
                        user["id"],
                        "ADD_SERVICE",
                        f"Added {service_type} service for unit {unit_number}"
                    )

                    conn.commit()
                    st.success("Service record added.")
                    time.sleep(0.6)
                    st.rerun()

        conn.close()

# ============================================================
# ADMIN TOOLS (NEW)
# ============================================================
elif page == "admin" and role in ["owner", "admin"]:
    st.subheader("⚙️ Admin Tools")
    
    tab1, tab2, tab3, tab4 = st.tabs(["🔄 Database Backup", "📊 System Audit", "🔧 Maintenance", "📈 Performance"])
    
    with tab1:
        st.markdown("### Database Backup & Restore")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🛡️ Create Backup", type="primary", use_container_width=True):
                try:
                    backup_path = backup_database()
                    st.success(f"✅ Backup created: {backup_path}")
                    
                    # Log audit
                    log_audit(
                        user["id"],
                        "DATABASE_BACKUP",
                        "Created database backup"
                    )
                except Exception as e:
                    st.error(f"Backup failed: {e}")
        
        with col2:
            # List existing backups
            if os.path.exists(BACKUP_DIR):
                backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith('.db')], reverse=True)
                if backups:
                    selected_backup = st.selectbox("Select backup to restore", backups)
                    
                    if st.button("🔄 Restore Backup", type="secondary", use_container_width=True):
                        if st.warning("⚠️ This will overwrite the current database. Continue?"):
                            backup_file = os.path.join(BACKUP_DIR, selected_backup)
                            success, message = restore_database(backup_file)
                            if success:
                                st.success(message)
                                
                                # Log audit
                                log_audit(
                                    user["id"],
                                    "DATABASE_RESTORE",
                                    f"Restored from backup: {selected_backup}"
                                )
                                
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error(message)
                else:
                    st.info("No backups available")
            else:
                st.info("Backup directory doesn't exist")
        
        # Database statistics
        st.divider()
        st.markdown("### Database Statistics")
        
        conn = connect_db()
        c = conn.cursor()
        
        tables = ["contractors", "time_entries", "work_orders", "service_history", "equipment", "unit_notes", "audit_log"]
        stats = []
        
        for table in tables:
            try:
                c.execute(f"SELECT COUNT(*) FROM {table}")
                count = c.fetchone()[0]
                stats.append({"Table": table, "Records": count})
            except:
                pass
        
        conn.close()
        
        if stats:
            stats_df = pd.DataFrame(stats)
            st.dataframe(stats_df, use_container_width=True, hide_index=True)
    
    with tab2:
        st.markdown("### System Audit Log")
        
        conn = connect_db()
        
        # Filter options
        col1, col2, col3 = st.columns(3)
        with col1:
            days_back = st.selectbox("Time Period", ["1 day", "7 days", "30 days", "All time"], index=1)
        with col2:
            action_filter = st.text_input("Filter by action (optional)")
        with col3:
            user_filter = st.text_input("Filter by user (optional)")
        
        # Build query
        query = """
            SELECT a.action, a.details, a.timestamp, c.name as user_name, c.role as user_role
            FROM audit_log a
            JOIN contractors c ON a.user_id = c.id
            WHERE 1=1
        """
        params = []
        
        if days_back != "All time":
            days = int(days_back.split()[0])
            query += " AND a.timestamp >= datetime('now', ?)"
            params.append(f"-{days} days")
        
        if action_filter:
            query += " AND a.action LIKE ?"
            params.append(f"%{action_filter}%")
        
        if user_filter:
            query += " AND c.name LIKE ?"
            params.append(f"%{user_filter}%")
        
        query += " ORDER BY a.timestamp DESC LIMIT 100"
        
        audit_logs = pd.read_sql_query(query, conn, params=params)
        conn.close()
        
        if audit_logs.empty:
            st.info("No audit logs found")
        else:
            # Export option
            excel_data = export_to_excel(audit_logs, "audit_logs")
            st.download_button(
                label="📥 Export Audit Logs",
                data=excel_data,
                file_name=f"audit_logs_{datetime.now().strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            
            # Display logs
            for _, r in audit_logs.iterrows():
                role_color = {
                    "owner": "#92400e",
                    "supervisor": "#1e40af", 
                    "technician": "#065f46",
                    "admin": "#5b21b6"
                }.get(r['user_role'], "#6b7280")
                
                st.markdown(f"""
                <div style="padding:10px; border-left:4px solid {role_color}; border-bottom:1px solid #e5e7eb; margin-bottom:8px;">
                  <div style="display:flex; justify-content:space-between;">
                    <b>{r['action']}</b>
                    <small style="color:#6b7280;">{r['timestamp']}</small>
                  </div>
                  <div>
                    <span style="background-color:{role_color};color:white;padding:2px 6px;border-radius:4px;font-size:0.8rem;">
                      {r['user_role']}
                    </span>
                    <b>{r['user_name']}</b>
                  </div>
                  <div style="margin-top:4px;color:#4b5563;">{r['details'] or '—'}</div>
                </div>
                """, unsafe_allow_html=True)
    
    with tab3:
        st.markdown("### System Maintenance")
        
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("🔄 Rebuild Indexes", use_container_width=True):
                try:
                    add_indexes()
                    st.success("✅ Database indexes rebuilt")
                    
                    # Log audit
                    log_audit(
                        user["id"],
                        "MAINTENANCE",
                        "Rebuilt database indexes"
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
        
        with col2:
            if st.button("🧹 Clean Old Notifications", use_container_width=True):
                try:
                    conn = connect_db()
                    c = conn.cursor()
                    c.execute("DELETE FROM notifications WHERE read=1 AND created_at < datetime('now', '-30 days')")
                    deleted = c.rowcount
                    conn.commit()
                    conn.close()
                    
                    st.success(f"✅ Cleaned {deleted} old notifications")
                    
                    # Log audit
                    log_audit(
                        user["id"],
                        "MAINTENANCE",
                        f"Cleaned {deleted} old notifications"
                    )
                except Exception as e:
                    st.error(f"Failed: {e}")
        
        st.divider()
        
        # Demo credentials management
        st.markdown("### Demo Accounts Management")
        st.info("""
        Demo accounts are for testing purposes only. In production:
        1. Remove hardcoded demo credentials
        2. Use environment variables for sensitive data
        3. Implement proper user registration flow
        """)
        
        if st.button("🔄 Reset Demo Passwords", type="secondary"):
            st.warning("This would reset all demo passwords in a production environment")
    
    with tab4:
        st.markdown("### System Performance")
        
        conn = connect_db()
        
        # Query performance metrics
        metrics = []
        
        # Table sizes
        tables = ["work_orders", "time_entries", "service_history", "audit_log"]
        for table in tables:
            try:
                c = conn.cursor()
                c.execute(f"SELECT COUNT(*) FROM {table}")
                count = c.fetchone()[0]
                metrics.append({"Metric": f"{table} records", "Value": count})
            except:
                pass
        
        # Recent activity
        c.execute("SELECT COUNT(*) FROM audit_log WHERE timestamp > datetime('now', '-1 hour')")
        recent_activity = c.fetchone()[0]
        metrics.append({"Metric": "Audit logs (last hour)", "Value": recent_activity})
        
        # Unresolved tickets
        c.execute("SELECT COUNT(*) FROM work_orders WHERE status IN ('open', 'in_progress')")
        open_tickets = c.fetchone()[0]
        metrics.append({"Metric": "Open tickets", "Value": open_tickets})
        
        # Pending approvals
        c.execute("SELECT COUNT(*) FROM time_entries WHERE approved = 0 AND clock_out IS NOT NULL")
        pending_time = c.fetchone()[0]
        metrics.append({"Metric": "Pending time approvals", "Value": pending_time})
        
        conn.close()
        
        # Display metrics
        metrics_df = pd.DataFrame(metrics)
        st.dataframe(metrics_df, use_container_width=True, hide_index=True)
        
        # Performance recommendations
        st.divider()
        st.markdown("### Performance Recommendations")
        
        recommendations = []
        
        if open_tickets > 50:
            recommendations.append("High number of open tickets. Consider assigning more technicians.")
        
        if pending_time > 20:
            recommendations.append("Many pending time approvals. Review time entries regularly.")
        
        if recent_activity > 100:
            recommendations.append("High system activity. Consider archiving old audit logs.")
        
        if recommendations:
            for rec in recommendations:
                st.warning(f"⚠️ {rec}")
        else:
            st.success("✅ System performance is within optimal ranges")

# ============================================================
# AI ASSISTANT
# ============================================================
elif page == "ai":
    st.subheader("🤖 AI Assistant")

    if not DEEPSEEK_API_KEY:
        st.warning("DeepSeek AI is not configured. Add DEEPSEEK_API_KEY in Streamlit Secrets.")
        st.stop()

    tab1, tab2 = st.tabs(["💬 Chat", "📊 Report Generator"])

    with tab1:
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        if prompt := st.chat_input("Ask HGHI Tech AI..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    system = f"""
You are an assistant for {COMPANY_NAME} fiber field service operations.
Be concise, technical, and practical.
You can help with troubleshooting, work order workflow, and reporting.
"""
                    messages = [{"role": "system", "content": system}]
                    messages += st.session_state.chat_history[-8:]

                    answer, err = deepseek_call(messages, temperature=0.25, max_tokens=500)
                    if answer:
                        st.markdown(answer)
                        st.session_state.chat_history.append({"role": "assistant", "content": answer})
                        
                        # Log audit
                        log_audit(
                            user["id"],
                            "AI_CHAT",
                            f"AI query: {prompt[:50]}..."
                        )
                    else:
                        st.error(f"AI error: {err}")

    with tab2:
        st.markdown("### Generate Report")
        report_type = st.selectbox("Report Type", [
            "Weekly Performance Summary",
            "Contractor Productivity Analysis",
            "Equipment Maintenance Overview",
            "Custom"
        ])
        col1, col2 = st.columns(2)
        start_date = col1.date_input("Start Date", datetime.now() - timedelta(days=7))
        end_date = col2.date_input("End Date", datetime.now())

        if st.button("Generate AI Report", type="primary"):
            with st.spinner("Building report..."):
                conn = connect_db()
                work = pd.read_sql_query("""
                    SELECT wo.ticket_id, wo.description, wo.priority, wo.status,
                           wo.created_date, wo.completed_date,
                           b.name as property, u.unit_number,
                           c.name as contractor
                    FROM work_orders wo
                    JOIN units u ON wo.unit_id=u.id
                    JOIN buildings b ON u.building_id=b.id
                    LEFT JOIN contractors c ON wo.contractor_id=c.id
                    WHERE DATE(wo.created_date) BETWEEN ? AND ?
                """, conn, params=(str(start_date), str(end_date)))

                time_df = pd.read_sql_query("""
                    SELECT c.name as contractor,
                           SUM(te.hours_worked) as total_hours,
                           COUNT(DISTINCT DATE(te.clock_in)) as days_worked
                    FROM time_entries te
                    JOIN contractors c ON te.contractor_id=c.id
                    WHERE DATE(te.clock_in) BETWEEN ? AND ?
                      AND te.clock_out IS NOT NULL
                    GROUP BY c.name
                """, conn, params=(str(start_date), str(end_date)))

                conn.close()

                data = {
                    "report_type": report_type,
                    "period": f"{start_date} to {end_date}",
                    "jobs_total": int(len(work)),
                    "jobs_completed": int((work["status"] == "completed").sum()) if not work.empty else 0,
                    "priority_counts": work["priority"].value_counts().to_dict() if not work.empty else {},
                    "contractor_time": time_df.to_dict("records") if not time_df.empty else []
                }

                report = deepseek_generate_report(data)
                st.markdown("### 📄 Report")
                st.markdown(report)

                st.download_button(
                    "Download Report (txt)",
                    data=report,
                    file_name=f"hghi_report_{start_date}_{end_date}.txt",
                    mime="text/plain"
                )
                
                # Log audit
                log_audit(
                    user["id"],
                    "AI_REPORT",
                    f"Generated {report_type} report for {start_date} to {end_date}"
                )

# ============================================================
# FOOTER
# ============================================================
st.divider()
st.markdown(f"""
<div style="text-align:center;color:#64748b;padding:14px;">
  <b>{COMPANY_NAME} Field Management System</b><br/>
  Owner: {OWNER_NAME} • Supervisors: {", ".join(SUPERVISORS)}<br/>
  DeepSeek AI: {"Enabled" if bool(DEEPSEEK_API_KEY) else "Disabled"} • Session timeout: {SESSION_TIMEOUT_MINUTES} min
</div>
""", unsafe_allow_html=True)
