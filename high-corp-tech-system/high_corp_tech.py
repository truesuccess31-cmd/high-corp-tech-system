# ============================================
# HGHI TECH FIELD MANAGEMENT SYSTEM (DEPLOY READY)
# - Streamlit Cloud friendly
# - Demo login buttons FIXED (no session_state widget errors)
# - DeepSeek AI via Streamlit Secrets
# ============================================

import os
import re
import io
import json
import time
import base64
import hashlib
import sqlite3
import requests
from datetime import datetime, timedelta
from PIL import Image

import pandas as pd
import streamlit as st


# ----------------------------
# CONFIG / CONSTANTS
# ----------------------------
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# Prefer Streamlit secrets, fallback to env var, fallback to blank
DEEPSEEK_API_KEY = ""
try:
    if "DEEPSEEK_API_KEY" in st.secrets:
        DEEPSEEK_API_KEY = st.secrets["DEEPSEEK_API_KEY"]
except Exception:
    pass
DEEPSEEK_API_KEY = DEEPSEEK_API_KEY or os.getenv("DEEPSEEK_API_KEY", "")


# ----------------------------
# PAGE SETUP (MUST BE EARLY)
# ----------------------------
st.set_page_config(
    page_title=f"{COMPANY_NAME} Field System",
    page_icon="🏗️",
    layout="wide",
)

st.markdown(
    """
<style>
    .hct-header {
        background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
        color: white;
        padding: 22px;
        border-radius: 14px;
        margin-bottom: 20px;
    }
    .role-badge {
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 700;
        display: inline-block;
        margin-top: 6px;
        background: rgba(255,255,255,0.18);
        color: white;
    }
    .card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 14px;
        margin: 10px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    .ai-box {
        background: #f0f9ff;
        border-left: 4px solid #3b82f6;
        padding: 12px;
        border-radius: 8px;
        margin: 10px 0;
    }
</style>
""",
    unsafe_allow_html=True,
)


# ----------------------------
# DATABASE
# ----------------------------
DB_PATH = "field_management.db"


def db_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def init_database():
    conn = db_conn()
    c = conn.cursor()

    c.execute(
        """CREATE TABLE IF NOT EXISTS contractors (
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
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS time_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contractor_id INTEGER NOT NULL,
            clock_in TIMESTAMP NOT NULL,
            clock_out TIMESTAMP,
            location TEXT,
            hours_worked REAL,
            verified BOOLEAN DEFAULT 0,
            approved BOOLEAN DEFAULT 0,
            FOREIGN KEY(contractor_id) REFERENCES contractors(id)
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS buildings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            property_manager TEXT,
            total_units INTEGER,
            status TEXT DEFAULT 'active'
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS units (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            building_id INTEGER NOT NULL,
            unit_number TEXT NOT NULL,
            resident_name TEXT,
            unit_type TEXT,
            status TEXT DEFAULT 'occupied',
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(building_id) REFERENCES buildings(id)
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS work_orders (
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
            email_screenshot BLOB,
            FOREIGN KEY(unit_id) REFERENCES units(id),
            FOREIGN KEY(contractor_id) REFERENCES contractors(id)
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS service_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL,
            contractor_id INTEGER NOT NULL,
            work_order_id INTEGER,
            service_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            service_type TEXT,
            equipment_serial TEXT,
            notes TEXT,
            photos BLOB,
            speed_test_download REAL,
            speed_test_upload REAL,
            speed_test_ping REAL,
            FOREIGN KEY(unit_id) REFERENCES units(id),
            FOREIGN KEY(contractor_id) REFERENCES contractors(id),
            FOREIGN KEY(work_order_id) REFERENCES work_orders(id)
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS equipment (
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
            photo BLOB,
            FOREIGN KEY(unit_id) REFERENCES units(id)
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_order_id INTEGER,
            contractor_id INTEGER NOT NULL,
            photo_type TEXT,
            photo_data BLOB,
            serial_number TEXT,
            ai_analysis TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(work_order_id) REFERENCES work_orders(id),
            FOREIGN KEY(contractor_id) REFERENCES contractors(id)
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS payroll (
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
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            type TEXT DEFAULT 'info',
            read BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES contractors(id)
        )"""
    )

    c.execute(
        """CREATE TABLE IF NOT EXISTS unit_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unit_id INTEGER NOT NULL,
            contractor_id INTEGER,
            note_type TEXT,
            content TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(unit_id) REFERENCES units(id),
            FOREIGN KEY(contractor_id) REFERENCES contractors(id)
        )"""
    )

    # Seed default users
    users = [
        (OWNER_NAME, "darrell@hghitech.com", "owner123", "owner", "active", 0),
        ("Brandon Alves", "brandon@hghitech.com", "super123", "supervisor", "active", 1),
        ("Andre Ampey", "andre@hghitech.com", "super123", "supervisor", "active", 1),
        ("Mike Rodriguez", "mike@hghitech.com", "tech123", "technician", "active", 40.00),
        ("Sarah Chen", "sarah@hghitech.com", "tech123", "technician", "active", 38.50),
        ("Admin", "tuesuccess3@gmail.com", "admin123", "admin", "active", 0),
    ]
    for name, email, pw, role, status, rate in users:
        c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email,))
        if c.fetchone()[0] == 0:
            c.execute(
                """INSERT INTO contractors (name,email,password_hash,role,status,hourly_rate,approved_by)
                   VALUES (?,?,?,?,?,?,?)""",
                (name, email, hash_password(pw), role, status, rate, 1),
            )

    # Seed buildings/units if empty
    c.execute("SELECT COUNT(*) FROM buildings")
    if c.fetchone()[0] == 0:
        sample_buildings = [
            ("ARVA1850 - Cortland on Pike", "1234 Pike Street, Arlington, VA", "Elauwit", 350),
            ("Tysons Corner Plaza", "5678 Tysons Blvd, McLean, VA", "Elauwit", 200),
            ("Ballston Commons", "9010 Wilson Blvd, Arlington, VA", "Verizon", 180),
        ]
        for name, addr, pm, total in sample_buildings:
            c.execute(
                "INSERT INTO buildings (name,address,property_manager,total_units) VALUES (?,?,?,?)",
                (name, addr, pm, total),
            )
            building_id = c.lastrowid
            # Add small sample unit set
            for floor in range(1, 4):
                for unit in range(1, 11):
                    unit_num = f"{chr(64 + floor)}-{unit:03d}"
                    c.execute(
                        "INSERT INTO units (building_id,unit_number,resident_name,unit_type) VALUES (?,?,?,?)",
                        (building_id, unit_num, f"Resident {floor}{unit:02d}", "apartment"),
                    )

    conn.commit()
    conn.close()


def verify_login(email: str, password: str):
    conn = db_conn()
    c = conn.cursor()
    c.execute(
        """SELECT id,name,role,hourly_rate,status FROM contractors
           WHERE email=? AND password_hash=?""",
        (email.strip().lower(), hash_password(password)),
    )
    row = c.fetchone()
    conn.close()

    if not row:
        return None, "Invalid credentials"

    user = {"id": row[0], "name": row[1], "role": row[2], "hourly_rate": row[3], "status": row[4]}
    if user["status"] == "pending":
        return None, "Account pending approval. Contact supervisor."
    if user["status"] == "inactive":
        return None, "Account inactive. Contact supervisor."
    return user, "Success"


def register_contractor(name, email, password, phone, hourly_rate):
    conn = db_conn()
    c = conn.cursor()

    email_norm = email.strip().lower()
    c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email_norm,))
    if c.fetchone()[0] > 0:
        conn.close()
        return False, "Email already registered"

    try:
        rate = float(hourly_rate)
        if rate < 15 or rate > 100:
            conn.close()
            return False, "Hourly rate must be between $15 and $100"
    except Exception:
        conn.close()
        return False, "Invalid hourly rate"

    c.execute(
        """INSERT INTO contractors (name,email,password_hash,phone,hourly_rate,role,status)
           VALUES (?,?,?,?,?,'technician','pending')""",
        (name.strip(), email_norm, hash_password(password), phone.strip(), rate),
    )

    # notify supervisors/owner
    c.execute("SELECT id FROM contractors WHERE role IN ('supervisor','owner')")
    for (sup_id,) in c.fetchall():
        c.execute(
            "INSERT INTO notifications (user_id,message,type) VALUES (?,?,?)",
            (sup_id, f"New contractor registration: {name} (${rate}/hr)", "warning"),
        )

    conn.commit()
    conn.close()
    return True, "Registration submitted for supervisor approval"


# ----------------------------
# DEEPSEEK AI
# ----------------------------
def simple_parse_email(email_text: str):
    patterns = {
        "ticket_id": r"(T[-_ ]?\d{6,})",
        "property_code": r"\[([A-Z0-9]{4,})\]",
        "unit_number": r"\[([A-Z]-?\d{2,4})\]",
        "resident_name": r"Resident[:\s]+([A-Za-z\s]+)",
        "issue_description": r"Issue[:\s]+(.+)",
    }

    results = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, email_text, re.IGNORECASE)
        if m:
            results[key] = m.group(1).strip()

    low = email_text.lower()
    if "urgent" in low or "asap" in low:
        results["priority"] = "urgent"
    elif "high" in low or "priority" in low:
        results["priority"] = "high"
    else:
        results["priority"] = "normal"

    return {"success": True, "data": results, "source": "simple_parser"}


def deepseek_chat(messages, temperature=0.2, max_tokens=600):
    if not DEEPSEEK_API_KEY:
        return None, "DeepSeek key missing"

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=20)
        if resp.status_code != 200:
            return None, f"DeepSeek HTTP {resp.status_code}: {resp.text[:120]}"
        data = resp.json()
        return data["choices"][0]["message"]["content"], None
    except Exception as e:
        return None, str(e)


def deepseek_parse_email(email_text: str):
    if not DEEPSEEK_API_KEY:
        return simple_parse_email(email_text)

    system_prompt = """You are an AI assistant for HGHI Tech field management.
Parse Elauwit work order emails and extract structured info.
Return ONLY valid JSON with fields:
{
 "ticket_id": "T-XXXXXX or null",
 "property_code": "ARVA1850 or similar",
 "unit_number": "C-508 or similar",
 "resident_name": "Name or null",
 "issue_description": "Detailed issue",
 "priority": "urgent/high/normal",
 "extracted_notes": "Any additional notes"
}
"""
    user_prompt = f"Parse this email and return JSON only:\n\n{email_text}"

    content, err = deepseek_chat(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        temperature=0.1,
        max_tokens=500,
    )
    if err or not content:
        return simple_parse_email(email_text)

    # Extract JSON safely
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if not m:
        return simple_parse_email(email_text)

    try:
        parsed = json.loads(m.group(0))
        return {"success": True, "data": parsed, "source": "deepseek_ai"}
    except Exception:
        return simple_parse_email(email_text)


def deepseek_generate_report(report_data: dict):
    if not DEEPSEEK_API_KEY:
        return "AI not configured."

    prompt = f"""Generate a professional HGHI Tech report.

Data (JSON):
{json.dumps(report_data, indent=2)}

Include:
1. Executive Summary
2. Key Metrics
3. Notable issues/patterns
4. Recommendations
5. Next steps

Use headings + bullet points."""
    content, err = deepseek_chat([{"role": "user", "content": prompt}], temperature=0.25, max_tokens=900)
    return content if content else f"AI failed: {err}"


# ----------------------------
# UTILITIES
# ----------------------------
def get_unread_notification_count(user_id: int) -> int:
    conn = db_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user_id,))
    n = c.fetchone()[0]
    conn.close()
    return int(n or 0)


def mark_all_notifications_read(user_id: int):
    conn = db_conn()
    c = conn.cursor()
    c.execute("UPDATE notifications SET read=1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


def calculate_payroll(contractor_id, start_date, end_date):
    conn = db_conn()
    q = """
    SELECT te.clock_in, te.clock_out, te.hours_worked, te.approved, c.hourly_rate
    FROM time_entries te
    JOIN contractors c ON te.contractor_id = c.id
    WHERE te.contractor_id = ?
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

    regular_hours = min(total_hours, 40.0)
    overtime_hours = max(total_hours - 40.0, 0.0)

    regular_pay = regular_hours * rate
    overtime_pay = overtime_hours * rate * 1.5
    total_pay = regular_pay + overtime_pay

    return {
        "total_hours": total_hours,
        "regular_hours": regular_hours,
        "overtime_hours": overtime_hours,
        "hourly_rate": rate,
        "regular_pay": regular_pay,
        "overtime_pay": overtime_pay,
        "total_pay": total_pay,
        "period": f"{start_date} to {end_date}",
    }


# ----------------------------
# SESSION STATE INIT
# ----------------------------
def ss_init():
    defaults = {
        "logged_in": False,
        "user": None,
        "clocked_in": False,
        "current_time_entry": None,
        "show_registration": False,
        "current_page": None,
        "show_notifications": False,
        "ai_enabled": bool(DEEPSEEK_API_KEY),
        # IMPORTANT: demo creds request lives here
        "demo_creds": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


ss_init()
init_database()


# ----------------------------
# DEMO LOGIN PREFILL (FIX)
# This must run BEFORE widgets are created.
# ----------------------------
if st.session_state.get("demo_creds"):
    st.session_state["prefill_email"] = st.session_state["demo_creds"]["email"]
    st.session_state["prefill_password"] = st.session_state["demo_creds"]["password"]
    st.session_state["demo_creds"] = None  # clear


# ----------------------------
# LOGIN / REGISTRATION
# ----------------------------
def login_screen():
    st.markdown(
        f"""
<div class="hct-header" style="text-align:center;">
  <h1>🏢 {COMPANY_NAME} Tech Field System</h1>
  <h3>Login</h3>
</div>
""",
        unsafe_allow_html=True,
    )

    # If user clicked a demo button earlier, these will exist:
    default_email = st.session_state.get("prefill_email", "")
    default_password = st.session_state.get("prefill_password", "")

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.session_state.show_registration:
            st.subheader("👷 Contractor Registration")
            with st.form("registration_form"):
                name = st.text_input("Full Name")
                email = st.text_input("Email")
                phone = st.text_input("Phone")
                hourly_rate = st.number_input("Desired Hourly Rate ($)", min_value=15.0, max_value=100.0, value=35.0, step=0.5)
                password = st.text_input("Password", type="password")
                confirm = st.text_input("Confirm Password", type="password")

                c1, c2 = st.columns(2)
                submit = c1.form_submit_button("🚀 Submit Registration", use_container_width=True)
                back = c2.form_submit_button("← Back", use_container_width=True)

                if back:
                    st.session_state.show_registration = False
                    st.rerun()

                if submit:
                    if not all([name, email, phone, password, confirm]):
                        st.error("Fill all fields.")
                    elif len(password) < 8:
                        st.error("Password must be 8+ characters.")
                    elif password != confirm:
                        st.error("Passwords do not match.")
                    else:
                        ok, msg = register_contractor(name, email, password, phone, hourly_rate)
                        if ok:
                            st.success(msg)
                            st.session_state.show_registration = False
                            # clear prefills
                            st.session_state.pop("prefill_email", None)
                            st.session_state.pop("prefill_password", None)
                            st.rerun()
                        else:
                            st.error(msg)

        else:
            st.subheader("🔐 Login")
            # IMPORTANT: do NOT assign to st.session_state["login_email"] after this renders.
            email = st.text_input("Email", key="login_email", value=default_email)
            password = st.text_input("Password", key="login_password", type="password", value=default_password)

            c1, c2 = st.columns(2)
            if c1.button("🚀 Login", type="primary", use_container_width=True):
                user, msg = verify_login(email, password)
                if user:
                    st.session_state.logged_in = True
                    st.session_state.user = user

                    # Clock-in resume check
                    conn = db_conn()
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, clock_in FROM time_entries WHERE contractor_id=? AND clock_out IS NULL",
                        (user["id"],),
                    )
                    row = cur.fetchone()
                    conn.close()
                    if row:
                        st.session_state.clocked_in = True
                        st.session_state.current_time_entry = {
                            "id": row[0],
                            "clock_in": datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S"),
                        }
                    st.rerun()
                else:
                    st.error(msg)

            if c2.button("🆕 New Contractor", use_container_width=True):
                st.session_state.show_registration = True
                st.rerun()

            st.divider()
            st.caption("Demo accounts (click to prefill):")

            demo_cols = st.columns(5)
            demos = [
                ("👑 Owner", "darrell@hghitech.com", "owner123"),
                ("👨‍💼 Supervisor", "brandon@hghitech.com", "super123"),
                ("👷 Tech", "mike@hghitech.com", "tech123"),
                ("👷 Tech", "sarah@hghitech.com", "tech123"),
                ("🛠️ Admin", "tuesuccess3@gmail.com", "admin123"),
            ]
            for i, (label, em, pw) in enumerate(demos):
                with demo_cols[i]:
                    if st.button(label, use_container_width=True, key=f"demo_{i}"):
                        # FIX: store creds -> rerun -> inputs render with values
                        st.session_state.demo_creds = {"email": em, "password": pw}
                        st.rerun()


# ----------------------------
# SIDEBAR + CLOCK
# ----------------------------
def sidebar(user):
    with st.sidebar:
        st.markdown(
            f"""
<div style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
            color:white; padding:16px; border-radius:12px; margin-bottom:12px;">
  <h4 style="margin:0;">👤 {user["name"]}</h4>
  <div class="role-badge">{user["role"].upper()}</div>
  <div style="margin-top:10px;"><b>Rate:</b> ${user["hourly_rate"]}/hr</div>
  <div><b>Status:</b> {user["status"].title()}</div>
</div>
""",
            unsafe_allow_html=True,
        )

        if DEEPSEEK_API_KEY:
            st.success("🤖 DeepSeek AI: Enabled")
        else:
            st.warning("🤖 DeepSeek AI: Not Configured (add secrets)")

        unread = get_unread_notification_count(user["id"])
        if unread:
            if st.button(f"📢 Notifications ({unread})", use_container_width=True):
                st.session_state.show_notifications = True

        st.markdown("### ⏱️ Time Clock")
        if st.session_state.clocked_in:
            now = datetime.now()
            clock_in = st.session_state.current_time_entry["clock_in"]
            hours = (now - clock_in).total_seconds() / 3600
            st.metric("Hours (current shift)", f"{hours:.2f}")

            if st.button("🛑 Clock Out", use_container_width=True):
                conn = db_conn()
                c = conn.cursor()
                c.execute(
                    "UPDATE time_entries SET clock_out=CURRENT_TIMESTAMP, hours_worked=? WHERE id=?",
                    (hours, st.session_state.current_time_entry["id"]),
                )
                conn.commit()
                conn.close()
                st.session_state.clocked_in = False
                st.session_state.current_time_entry = None
                st.rerun()
        else:
            if st.button("⏰ Clock In", type="primary", use_container_width=True):
                conn = db_conn()
                c = conn.cursor()
                c.execute(
                    "INSERT INTO time_entries (contractor_id, clock_in, location) VALUES (?, CURRENT_TIMESTAMP, ?)",
                    (user["id"], "Field Location"),
                )
                conn.commit()
                c.execute(
                    "SELECT id, clock_in FROM time_entries WHERE contractor_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1",
                    (user["id"],),
                )
                row = c.fetchone()
                conn.close()
                if row:
                    st.session_state.clocked_in = True
                    st.session_state.current_time_entry = {
                        "id": row[0],
                        "clock_in": datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S"),
                    }
                st.rerun()

        st.divider()
        st.markdown("### 📱 Navigation")

        if user["role"] in ("owner", "supervisor", "admin"):
            options = ["Dashboard", "Ticket Manager", "Unit Explorer", "AI Assistant", "Reports"]
        else:
            options = ["My Dashboard", "My Assignments", "Ticket Manager", "Unit Explorer"]

        choice = st.radio("Go to:", options, index=0, label_visibility="collapsed")
        st.session_state.current_page = choice

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            for k in ["logged_in", "user", "clocked_in", "current_time_entry", "prefill_email", "prefill_password"]:
                st.session_state.pop(k, None)
            st.session_state.logged_in = False
            st.session_state.user = None
            st.rerun()


# ----------------------------
# PAGES
# ----------------------------
def page_dashboard(user):
    st.subheader("📊 Dashboard")

    conn = db_conn()
    # Team stats
    team_stats = pd.read_sql_query(
        """
        SELECT
          COUNT(CASE WHEN status='active' THEN 1 END) as active_contractors,
          COUNT(CASE WHEN status='pending' THEN 1 END) as pending_approvals,
          COUNT(CASE WHEN role='technician' THEN 1 END) as total_technicians,
          AVG(hourly_rate) as avg_rate
        FROM contractors
        """,
        conn,
    ).iloc[0]

    work_stats = pd.read_sql_query(
        """
        SELECT
          COUNT(CASE WHEN status='open' THEN 1 END) as open_jobs,
          COUNT(CASE WHEN status='in_progress' THEN 1 END) as in_progress_jobs,
          SUM(CASE WHEN status='completed' AND DATE(completed_date)=DATE('now') THEN 1 ELSE 0 END) as completed_today
        FROM work_orders
        """,
        conn,
    ).iloc[0]

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Active Contractors", int(team_stats["active_contractors"] or 0))
    col2.metric("Pending Approvals", int(team_stats["pending_approvals"] or 0))
    col3.metric("Open Jobs", int(work_stats["open_jobs"] or 0))
    col4.metric("Completed Today", int(work_stats["completed_today"] or 0))

    st.divider()

    recent = pd.read_sql_query(
        """
        SELECT wo.ticket_id, wo.description, wo.status, wo.priority,
               b.name as property, u.unit_number, c.name as contractor,
               wo.created_date
        FROM work_orders wo
        JOIN units u ON wo.unit_id=u.id
        JOIN buildings b ON u.building_id=b.id
        LEFT JOIN contractors c ON wo.contractor_id=c.id
        ORDER BY wo.created_date DESC
        LIMIT 12
        """,
        conn,
    )
    conn.close()

    st.markdown("### Recent Work Orders")
    if recent.empty:
        st.info("No work orders yet.")
        return

    for _, r in recent.iterrows():
        st.markdown(
            f"""
<div class="card">
  <b>{r["ticket_id"]}</b> — {r["property"]} / Unit {r["unit_number"]}<br/>
  <span><b>Priority:</b> {str(r["priority"]).upper()} &nbsp;|&nbsp; <b>Status:</b> {str(r["status"]).replace("_"," ").title()}</span><br/>
  <span><b>Assigned:</b> {r["contractor"] if r["contractor"] else "Unassigned"}</span><br/>
  <span>{str(r["description"])[:140]}</span>
</div>
""",
            unsafe_allow_html=True,
        )


def page_ticket_manager(user):
    st.subheader("📋 Ticket Manager")
    tab1, tab2 = st.tabs(["📧 Email Parser", "📝 Manual Entry"])

    with tab1:
        email_text = st.text_area(
            "Paste Elauwit Email",
            height=220,
            placeholder="[Elauwit] T-109040 Created | [ARVA1850] [C-508] HGHI Dispatch Request\n\nProperty: ARVA1850 - Cortland on Pike\nUnit: C-508\nResident: Tamara Radcliff\nIssue: No internet - urgent\nTechnician needed ASAP",
        )
        use_ai = st.checkbox("🤖 Use DeepSeek AI", value=bool(DEEPSEEK_API_KEY))
        save_email = st.checkbox("💾 Save original email", value=True)

        if st.button("Parse Email", type="primary", disabled=not email_text.strip()):
            with st.spinner("Parsing..."):
                parsed = deepseek_parse_email(email_text) if use_ai else simple_parse_email(email_text)

            st.success(f"Parsed via: {parsed['source']}")
            data = parsed["data"]

            conn = db_conn()
            properties = pd.read_sql_query("SELECT id,name,address FROM buildings ORDER BY name", conn)
            selected_property = st.selectbox("Property", properties["name"].tolist(), key="em_prop")
            prop_id = int(properties[properties["name"] == selected_property].iloc[0]["id"])

            units = pd.read_sql_query(
                "SELECT id,unit_number,resident_name FROM units WHERE building_id=? ORDER BY unit_number",
                conn,
                params=(prop_id,),
            )

            selected_unit = st.selectbox("Unit", units["unit_number"].tolist(), key="em_unit")
            unit_id = int(units[units["unit_number"] == selected_unit].iloc[0]["id"])

            ticket_id_default = data.get("ticket_id") or f"T-{int(time.time())}"
            ticket_id = st.text_input("Ticket ID", value=ticket_id_default)

            desc_default = data.get("issue_description") or data.get("description") or ""
            description = st.text_area("Description", value=desc_default, height=120)

            priority_default = data.get("priority", "normal")
            priority = st.selectbox("Priority", ["normal", "high", "urgent"], index=["normal", "high", "urgent"].index(priority_default))

            contractor_id = None
            assigned_name = "Unassigned"

            if user["role"] in ("owner", "supervisor", "admin"):
                contractors = pd.read_sql_query(
                    "SELECT id,name FROM contractors WHERE status='active' AND role IN ('technician','supervisor','owner','admin') ORDER BY name",
                    conn,
                )
                assigned_name = st.selectbox("Assign to", ["Unassigned"] + contractors["name"].tolist())
                if assigned_name != "Unassigned":
                    contractor_id = int(contractors[contractors["name"] == assigned_name].iloc[0]["id"])
            else:
                contractor_id = user["id"]
                assigned_name = user["name"]

            if st.button("✅ Create Work Order", type="primary"):
                cur = conn.cursor()
                email_to_save = email_text if save_email else None
                cur.execute(
                    """INSERT INTO work_orders (ticket_id, unit_id, contractor_id, description, priority, status, email_text, assigned_date)
                       VALUES (?, ?, ?, ?, ?, 'open', ?, CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END)
                    """,
                    (ticket_id, unit_id, contractor_id, description, priority, email_to_save, contractor_id),
                )
                conn.commit()
                conn.close()
                st.success(f"Created work order: {ticket_id} (Assigned: {assigned_name})")
                st.rerun()

            conn.close()

    with tab2:
        conn = db_conn()
        properties = pd.read_sql_query("SELECT id,name FROM buildings ORDER BY name", conn)
        selected_property = st.selectbox("Property", properties["name"].tolist(), key="man_prop")
        prop_id = int(properties[properties["name"] == selected_property].iloc[0]["id"])

        units = pd.read_sql_query(
            "SELECT id,unit_number FROM units WHERE building_id=? ORDER BY unit_number",
            conn,
            params=(prop_id,),
        )
        selected_unit = st.selectbox("Unit", units["unit_number"].tolist(), key="man_unit")
        unit_id = int(units[units["unit_number"] == selected_unit].iloc[0]["id"])

        ticket_id = st.text_input("Ticket ID", value=f"T-{int(time.time())}")
        description = st.text_area("Description", height=130)
        priority = st.selectbox("Priority", ["normal", "high", "urgent"])

        contractor_id = None
        if user["role"] in ("owner", "supervisor", "admin"):
            contractors = pd.read_sql_query(
                "SELECT id,name FROM contractors WHERE status='active' ORDER BY name", conn
            )
            assigned_name = st.selectbox("Assign to", ["Unassigned"] + contractors["name"].tolist())
            if assigned_name != "Unassigned":
                contractor_id = int(contractors[contractors["name"] == assigned_name].iloc[0]["id"])
        else:
            contractor_id = user["id"]

        if st.button("✅ Create Ticket", type="primary"):
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO work_orders (ticket_id, unit_id, contractor_id, description, priority, status, assigned_date)
                   VALUES (?, ?, ?, ?, ?, 'open', CASE WHEN ? IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END)
                """,
                (ticket_id, unit_id, contractor_id, description, priority, contractor_id),
            )
            conn.commit()
            st.success("Ticket created.")
            st.rerun()

        conn.close()


def page_unit_explorer(user):
    st.subheader("🏢 Unit Explorer")

    conn = db_conn()
    properties = pd.read_sql_query("SELECT id,name,address FROM buildings ORDER BY name", conn)
    selected_property = st.selectbox("Select Property", properties["name"].tolist())
    prop_id = int(properties[properties["name"] == selected_property].iloc[0]["id"])

    units = pd.read_sql_query(
        "SELECT id,unit_number,resident_name,status,notes FROM units WHERE building_id=? ORDER BY unit_number",
        conn,
        params=(prop_id,),
    )

    if units.empty:
        st.info("No units found.")
        conn.close()
        return

    label_map = units.apply(lambda x: f"{x['unit_number']} — {x['resident_name']}", axis=1).tolist()
    selected_label = st.selectbox("Select Unit", label_map)
    unit_number = selected_label.split(" — ")[0]
    unit_id = int(units[units["unit_number"] == unit_number].iloc[0]["id"])

    row = units[units["id"] == unit_id].iloc[0]
    st.markdown(
        f"""
<div class="card">
  <h4 style="margin:0;">🏠 Unit {row["unit_number"]}</h4>
  <div><b>Resident:</b> {row["resident_name"]}</div>
  <div><b>Status:</b> {str(row["status"]).title()}</div>
  <div><b>Notes:</b> {row["notes"] if row["notes"] else "—"}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    tab1, tab2, tab3 = st.tabs(["📋 Service History", "🔧 Equipment", "➕ Add Service"])

    with tab1:
        hist = pd.read_sql_query(
            """
            SELECT sh.service_date, sh.service_type, sh.equipment_serial, sh.notes,
                   sh.speed_test_download, sh.speed_test_upload, sh.speed_test_ping,
                   c.name as contractor_name, wo.ticket_id
            FROM service_history sh
            LEFT JOIN contractors c ON sh.contractor_id=c.id
            LEFT JOIN work_orders wo ON sh.work_order_id=wo.id
            WHERE sh.unit_id=?
            ORDER BY sh.service_date DESC
            """,
            conn,
            params=(unit_id,),
        )
        if hist.empty:
            st.info("No service history yet.")
        else:
            for _, h in hist.iterrows():
                st.markdown(
                    f"""
<div class="card">
  <b>📅 {h["service_date"]}</b><br/>
  <b>Type:</b> {h["service_type"]}<br/>
  <b>Tech:</b> {h["contractor_name"]}<br/>
  <b>Ticket:</b> {h["ticket_id"] if h["ticket_id"] else "—"}<br/>
  <b>Serial:</b> {h["equipment_serial"] if h["equipment_serial"] else "—"}<br/>
  <b>Speed:</b> {h["speed_test_download"] or "—"}↓ / {h["speed_test_upload"] or "—"}↑ / {h["speed_test_ping"] or "—"}ms<br/>
  <b>Notes:</b> {h["notes"] if h["notes"] else "—"}
</div>
""",
                    unsafe_allow_html=True,
                )

    with tab2:
        eq = pd.read_sql_query(
            """
            SELECT equipment_type, serial_number, manufacturer, model,
                   installation_date, last_service_date, status, notes
            FROM equipment
            WHERE unit_id=?
            ORDER BY equipment_type
            """,
            conn,
            params=(unit_id,),
        )
        if eq.empty:
            st.info("No equipment recorded for this unit.")
        else:
            st.dataframe(eq, use_container_width=True)

        with st.expander("➕ Add Equipment"):
            with st.form("add_equipment"):
                equip_type = st.selectbox("Equipment Type", ["ONT", "Router", "AP", "Switch", "Modem", "Other"])
                serial = st.text_input("Serial Number")
                manufacturer = st.text_input("Manufacturer")
                model = st.text_input("Model")
                install = st.date_input("Installation Date", value=datetime.now().date())
                status = st.selectbox("Status", ["active", "needs_service", "replaced"])
                notes = st.text_area("Notes")
                submit = st.form_submit_button("Save Equipment")
                if submit:
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO equipment (unit_id,equipment_type,serial_number,manufacturer,model,installation_date,status,notes)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (unit_id, equip_type, serial, manufacturer, model, str(install), status, notes),
                    )
                    conn.commit()
                    st.success("Saved equipment.")
                    st.rerun()

    with tab3:
        with st.form("add_service"):
            service_type = st.selectbox("Service Type", ["Installation", "Repair", "Maintenance", "Inspection"])
            equipment_serial = st.text_input("Equipment Serial (optional)")
            ticket_ref = st.text_input("Ticket ID (optional)")
            sd = st.number_input("Download (Mbps)", min_value=0, value=850)
            su = st.number_input("Upload (Mbps)", min_value=0, value=850)
            sp = st.number_input("Ping (ms)", min_value=0, value=8)
            notes = st.text_area("Service Notes", height=140)

            submit = st.form_submit_button("Save Service Record")
            if submit:
                wo_id = None
                if ticket_ref.strip():
                    cur = conn.cursor()
                    cur.execute("SELECT id FROM work_orders WHERE ticket_id=?", (ticket_ref.strip(),))
                    rr = cur.fetchone()
                    if rr:
                        wo_id = rr[0]

                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO service_history
                       (unit_id, contractor_id, work_order_id, service_type, equipment_serial, notes,
                        speed_test_download, speed_test_upload, speed_test_ping)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (unit_id, user["id"], wo_id, service_type, equipment_serial, notes, sd, su, sp),
                )

                if equipment_serial.strip():
                    cur.execute(
                        "UPDATE equipment SET last_service_date=CURRENT_DATE WHERE unit_id=? AND serial_number=?",
                        (unit_id, equipment_serial.strip()),
                    )

                conn.commit()
                st.success("Service record saved.")
                st.rerun()

    conn.close()


def page_ai_assistant(user):
    st.subheader("🤖 AI Assistant")
    if not DEEPSEEK_API_KEY:
        st.warning("DeepSeek not configured. Add DEEPSEEK_API_KEY to Streamlit Secrets.")
        return

    tab1, tab2 = st.tabs(["💬 Chat", "📄 Generate Report"])

    with tab1:
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        for m in st.session_state.chat_history:
            with st.chat_message(m["role"]):
                st.markdown(m["content"])

        prompt = st.chat_input("Ask HGHI Tech AI… (troubleshooting, steps, notes, etc.)")
        if prompt:
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            sys = f"""You are HGHI Tech's field operations AI.
Be practical and concise. Focus on fiber/network field support, troubleshooting, and work order best practices.
"""
            messages = [{"role": "system", "content": sys}] + st.session_state.chat_history[-8:]
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    content, err = deepseek_chat(messages, temperature=0.25, max_tokens=500)
                    if content:
                        st.markdown(content)
                        st.session_state.chat_history.append({"role": "assistant", "content": content})
                    else:
                        st.error(err or "AI error.")

    with tab2:
        st.markdown("Generate a weekly summary from your data (work orders + time entries).")
        c1, c2 = st.columns(2)
        start = c1.date_input("Start", value=(datetime.now() - timedelta(days=7)).date())
        end = c2.date_input("End", value=datetime.now().date())

        if st.button("Generate AI Report", type="primary"):
            conn = db_conn()
            work = pd.read_sql_query(
                """
                SELECT wo.ticket_id, wo.priority, wo.status, wo.created_date, wo.completed_date,
                       b.name as property, u.unit_number, c.name as contractor
                FROM work_orders wo
                JOIN units u ON wo.unit_id=u.id
                JOIN buildings b ON u.building_id=b.id
                LEFT JOIN contractors c ON wo.contractor_id=c.id
                WHERE DATE(wo.created_date) BETWEEN ? AND ?
                """,
                conn,
                params=(str(start), str(end)),
            )
            time_df = pd.read_sql_query(
                """
                SELECT c.name as contractor, SUM(te.hours_worked) as total_hours
                FROM time_entries te
                JOIN contractors c ON te.contractor_id=c.id
                WHERE te.clock_out IS NOT NULL AND DATE(te.clock_in) BETWEEN ? AND ?
                GROUP BY c.name
                """,
                conn,
                params=(str(start), str(end)),
            )
            conn.close()

            data = {
                "period": f"{start} to {end}",
                "total_jobs": int(len(work)),
                "completed_jobs": int((work["status"] == "completed").sum()) if not work.empty else 0,
                "priority_counts": work["priority"].value_counts().to_dict() if not work.empty else {},
                "hours_by_contractor": time_df.to_dict("records") if not time_df.empty else [],
                "sample_work_orders": work.head(10).to_dict("records") if not work.empty else [],
            }

            with st.spinner("Generating report…"):
                report = deepseek_generate_report(data)

            st.markdown("### Report")
            st.markdown(f"<div class='ai-box'>{report}</div>", unsafe_allow_html=True)

            st.download_button(
                "⬇️ Download Report (txt)",
                data=report,
                file_name=f"hghi_report_{start}_to_{end}.txt",
                mime="text/plain",
            )


def notifications_modal(user):
    st.subheader("📢 Notifications")
    conn = db_conn()
    df = pd.read_sql_query(
        "SELECT message,type,created_at,read FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        conn,
        params=(user["id"],),
    )
    conn.close()

    if df.empty:
        st.info("No notifications.")
    else:
        st.dataframe(df, use_container_width=True)

    col1, col2 = st.columns(2)
    if col1.button("Mark all as read", type="primary"):
        mark_all_notifications_read(user["id"])
        st.session_state.show_notifications = False
        st.rerun()

    if col2.button("Close"):
        st.session_state.show_notifications = False
        st.rerun()


# ----------------------------
# APP ENTRY
# ----------------------------
if not st.session_state.logged_in:
    login_screen()
    st.stop()

user = st.session_state.user

st.markdown(
    f"""
<div class="hct-header">
  <h1 style="margin:0;">🏢 {COMPANY_NAME} Field Management</h1>
  <div style="opacity:0.95;">Welcome back, {user["name"]} • {datetime.now().strftime("%A, %B %d, %Y")}</div>
</div>
""",
    unsafe_allow_html=True,
)

sidebar(user)

# Notifications panel
if st.session_state.show_notifications:
    notifications_modal(user)
    st.stop()

page = st.session_state.current_page or "Dashboard"

if page == "Dashboard":
    page_dashboard(user)
elif page == "Ticket Manager":
    page_ticket_manager(user)
elif page == "Unit Explorer":
    page_unit_explorer(user)
elif page == "AI Assistant":
    page_ai_assistant(user)
elif page == "Reports":
    st.subheader("📈 Reports")
    st.info("Use AI Assistant > Generate Report for now (fastest for today).")
elif page == "My Dashboard":
    page_dashboard(user)
elif page == "My Assignments":
    st.subheader("📋 My Assignments")
    conn = db_conn()
    df = pd.read_sql_query(
        """
        SELECT wo.ticket_id, wo.description, wo.priority, wo.status, wo.created_date,
               b.name as property, u.unit_number
        FROM work_orders wo
        JOIN units u ON wo.unit_id=u.id
        JOIN buildings b ON u.building_id=b.id
        WHERE wo.contractor_id=?
        ORDER BY wo.created_date DESC
        """,
        conn,
        params=(user["id"],),
    )
    conn.close()
    st.dataframe(df, use_container_width=True)
else:
    st.info("Page coming soon.")

st.divider()
st.caption(f"🏢 {COMPANY_NAME} • Powered by DeepSeek AI • Build: v1 (today)")
