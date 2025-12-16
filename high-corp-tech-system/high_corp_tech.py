# ============================================================
# HGHI TECH FIELD MANAGEMENT SYSTEM (Streamlit)
# - Login + Contractor Registration (pending approval)
# - Time Clock (Clock in/out)
# - Ticket Manager (Email parser + manual ticket)
# - Unit Explorer (service history + equipment + notes)
# - DeepSeek AI integration (email parsing, reports, assistant)
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
from datetime import datetime, timedelta
from PIL import Image

# ----------------------------
# COMPANY CONSTANTS
# ----------------------------
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]

DB_PATH = "field_management.db"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

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

    return {"success": True, "data": results, "source": "simple_parser"}

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
        return {"success": True, "data": parsed, "source": "deepseek_ai"}
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

    # ----------------------------
    # SEED: REAL TEAM USERS
    # ----------------------------
    users = [
        # name, email, password, role, status, rate
        ("Darrell Kelly",  "darrell@hghitech.com",  "owner123", "owner",      "active", 0),

        ("Brandon Alves",  "brandon@hghitech.com",  "super123", "supervisor", "active", 0),
        ("Andre Ampey",    "andre@hghitech.com",    "super123", "supervisor", "active", 0),

        ("Walter Chandler","walter@hghitech.com",   "tech123",  "technician", "active", 40.00),
        ("Rasheed Rouse",  "rasheed@hghitech.com",  "tech123",  "technician", "active", 40.00),
        ("Dale Vester",    "dale@hghitech.com",     "tech123",  "technician", "active", 40.00),

        # optional admin (keep if you want)
        ("Admin",          "tuesuccess3@gmail.com", "admin123", "admin",      "active", 0),
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
    return user, "Success"

def register_contractor(name, email, password, phone, hourly_rate):
    conn = connect_db()
    c = conn.cursor()

    email_norm = email.strip().lower()

    c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email_norm,))
    if c.fetchone()[0] > 0:
        conn.close()
        return False, "Email already registered"

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

# IMPORTANT: These keys are NOT bound to widgets directly
# so we can safely change them from demo buttons.
if "prefill_email" not in st.session_state:
    st.session_state.prefill_email = ""
if "prefill_password" not in st.session_state:
    st.session_state.prefill_password = ""

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
                password = st.text_input("Password (min 8 chars)", type="password")
                confirm = st.text_input("Confirm Password", type="password")
                submit = st.form_submit_button("Submit Registration", use_container_width=True)

            if submit:
                if not all([name, email, phone, password, confirm]):
                    st.error("Please fill all fields.")
                elif len(password) < 8:
                    st.error("Password must be at least 8 characters.")
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
            demo_cols = st.columns(3)
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
    conn = connect_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM notifications WHERE user_id=? AND read=0", (user["id"],))
    unread = c.fetchone()[0]
    conn.close()

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
            ("ai", "🤖 AI Assistant"),
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

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Active Techs", int(team_stats["active_techs"] or 0))
        col2.metric("Pending Approvals", int(team_stats["pending_approvals"] or 0))
        col3.metric("Open Jobs", int(work_stats["open_jobs"] or 0))
        col4.metric("Completed Today", int(work_stats["completed_today"] or 0))

        st.divider()
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
                    data = result["data"]

                st.success(f"Parsed via: {result['source']}")
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

                    conn.commit()
                    st.success("Service record added.")
                    time.sleep(0.6)
                    st.rerun()

        conn.close()

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

# ============================================================
# FOOTER
# ============================================================
st.divider()
st.markdown(f"""
<div style="text-align:center;color:#64748b;padding:14px;">
  <b>{COMPANY_NAME} Field Management System</b><br/>
  Owner: {OWNER_NAME} • Supervisors: {", ".join(SUPERVISORS)}<br/>
  DeepSeek AI: {"Enabled" if bool(DEEPSEEK_API_KEY) else "Disabled"}
</div>
""", unsafe_allow_html=True)
