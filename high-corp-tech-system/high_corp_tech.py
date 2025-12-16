import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import json
import time
import re
import requests
from datetime import datetime, timedelta

# =========================
# CONFIG
# =========================
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]

DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_API_KEY = ""
try:
    # Streamlit Cloud Secrets
    DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
except Exception:
    DEEPSEEK_API_KEY = ""

DB_PATH = "field_management.db"

st.set_page_config(
    page_title=f"{COMPANY_NAME} Field System",
    page_icon="🏗️",
    layout="wide",
)

# =========================
# STYLE
# =========================
st.markdown(
    """
<style>
.hct-header {
  background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
  color: white; padding: 20px; border-radius: 14px; margin-bottom: 18px;
}
.card {background: white; border:1px solid #e5e7eb; border-radius: 12px; padding:14px; margin:10px 0;}
.badge {display:inline-block; padding:4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700;}
.badge-owner {background:#fef3c7; color:#92400e;}
.badge-supervisor {background:#dbeafe; color:#1e40af;}
.badge-technician {background:#d1fae5; color:#065f46;}
.muted {color:#6b7280;}
</style>
""",
    unsafe_allow_html=True,
)

# =========================
# DB
# =========================
def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_database():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        phone TEXT,
        hourly_rate REAL DEFAULT 35.00,
        role TEXT DEFAULT 'technician',
        status TEXT DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

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

    c.execute("""
    CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        building_id INTEGER NOT NULL,
        unit_number TEXT NOT NULL,
        resident_name TEXT,
        status TEXT DEFAULT 'occupied',
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(building_id) REFERENCES buildings(id)
    )
    """)

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
        email_text TEXT,
        FOREIGN KEY(unit_id) REFERENCES units(id),
        FOREIGN KEY(contractor_id) REFERENCES contractors(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        clock_in TIMESTAMP NOT NULL,
        clock_out TIMESTAMP,
        location TEXT,
        hours_worked REAL,
        FOREIGN KEY(contractor_id) REFERENCES contractors(id)
    )
    """)

    # Seed users (demo)
    users = [
        (OWNER_NAME, "darrell@hghitech.com", "owner123", "owner", "active", 0),
        ("Brandon Alves", "brandon@hghitech.com", "super123", "supervisor", "active", 0),
        ("Andre Ampey", "andre@hghitech.com", "super123", "supervisor", "active", 0),
        ("Mike Rodriguez", "mike@hghitech.com", "tech123", "technician", "active", 40.00),
        ("Sarah Chen", "sarah@hghitech.com", "tech123", "technician", "active", 38.50),
    ]

    for name, email, pw, role, status, rate in users:
        c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email,))
        if c.fetchone()[0] == 0:
            pw_hash = hashlib.sha256(pw.encode()).hexdigest()
            c.execute(
                """INSERT INTO contractors (name,email,password_hash,role,status,hourly_rate)
                   VALUES (?,?,?,?,?,?)""",
                (name, email, pw_hash, role, status, rate),
            )

    # Seed building/units
    c.execute("SELECT COUNT(*) FROM buildings")
    if c.fetchone()[0] == 0:
        c.execute(
            """INSERT INTO buildings (name,address,property_manager,total_units)
               VALUES (?,?,?,?)""",
            ("ARVA1850 - Cortland on Pike", "1234 Pike Street, Arlington, VA", "Elauwit", 350),
        )
        building_id = c.lastrowid
        for floor in range(1, 4):
            for unit in range(1, 11):
                unit_num = f"{chr(64+floor)}-{unit:03d}"
                c.execute(
                    """INSERT INTO units (building_id,unit_number,resident_name)
                       VALUES (?,?,?)""",
                    (building_id, unit_num, f"Resident {floor}{unit:02d}"),
                )

    conn.commit()
    conn.close()

init_database()

# =========================
# AUTH
# =========================
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def verify_login(email: str, password: str):
    conn = db()
    c = conn.cursor()
    c.execute(
        """SELECT id,name,role,hourly_rate,status FROM contractors
           WHERE email=? AND password_hash=?""",
        (email, hash_password(password)),
    )
    row = c.fetchone()
    conn.close()

    if not row:
        return None, "Invalid credentials"

    user = {"id": row[0], "name": row[1], "role": row[2], "hourly_rate": float(row[3]), "status": row[4]}
    if user["status"] != "active":
        return None, f"Account is {user['status']}. Contact supervisor."
    return user, "Success"

# =========================
# AI
# =========================
def simple_parse_email(email_text: str):
    patterns = {
        "ticket_id": r"(T[-_ ]?\d{6,})",
        "property_code": r"\[([A-Z0-9]{4,})\]",
        "unit_number": r"\[([A-Z]-?\d{2,4})\]",
        "resident_name": r"Resident[:\s]+([A-Za-z\s'\-]+)",
        "issue_description": r"Issue[:\s]+(.+)",
    }
    results = {}
    for k, p in patterns.items():
        m = re.search(p, email_text, re.IGNORECASE)
        if m:
            results[k] = m.group(1).strip()

    low = email_text.lower()
    if "urgent" in low or "asap" in low:
        results["priority"] = "urgent"
    elif "high" in low:
        results["priority"] = "high"
    else:
        results["priority"] = "normal"

    return {"success": True, "data": results, "source": "simple_parser"}

def deepseek_parse_email(email_text: str):
    if not DEEPSEEK_API_KEY:
        return simple_parse_email(email_text)

    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    system_prompt = """
You are an AI assistant for HGHI Tech.
Parse an Elauwit work order email and return ONLY valid JSON:
{
  "ticket_id": "T-109040 or null",
  "property_code": "ARVA1850 or null",
  "unit_number": "C-508 or null",
  "resident_name": "Name or null",
  "issue_description": "Detailed issue",
  "priority": "urgent/high/normal",
  "extracted_notes": "Any extra notes or null"
}
    """.strip()

    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": email_text}],
        "temperature": 0.1,
        "max_tokens": 500,
    }

    try:
        r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=12)
        if r.status_code != 200:
            return simple_parse_email(email_text)
        content = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return simple_parse_email(email_text)
        data = json.loads(m.group())
        return {"success": True, "data": data, "source": "deepseek_ai"}
    except Exception:
        return simple_parse_email(email_text)

# =========================
# SESSION STATE (SAFE PREFILL)
# =========================
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "dashboard"
if "clocked_in" not in st.session_state:
    st.session_state.clocked_in = False
if "time_entry_id" not in st.session_state:
    st.session_state.time_entry_id = None

# SAFE: apply demo-prefill BEFORE rendering widgets
if st.session_state.get("prefill_login", None):
    st.session_state["login_email"] = st.session_state["prefill_login"]["email"]
    st.session_state["login_password"] = st.session_state["prefill_login"]["password"]
    st.session_state["prefill_login"] = None

# =========================
# LOGIN PAGE
# =========================
def login_page():
    st.markdown(
        f"""
<div class="hct-header" style="text-align:center;">
  <h1>🏢 {COMPANY_NAME}</h1>
  <h3>Field Management System</h3>
  <p class="muted">Login to access your dashboard</p>
</div>
""",
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔐 Login")

        # IMPORTANT: keys exist, but we only set them BEFORE this renders (see prefill block above)
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")

        if st.button("🚀 Login", type="primary", use_container_width=True):
            user, msg = verify_login(email.strip(), password)
            if user:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.session_state.page = "dashboard"
                st.success(f"Welcome, {user['name']}!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(msg)

        st.divider()
        st.caption("Demo accounts (safe buttons):")

        demo_cols = st.columns(4)

        def set_prefill(e, p):
            # Do NOT set login_email directly here (will crash).
            # Instead set a temp key, rerun, then prefill before widgets render.
            st.session_state["prefill_login"] = {"email": e, "password": p}
            st.rerun()

        with demo_cols[0]:
            if st.button("👑 Owner Demo", use_container_width=True):
                set_prefill("darrell@hghitech.com", "owner123")
        with demo_cols[1]:
            if st.button("👨‍💼 Supervisor Demo", use_container_width=True):
                set_prefill("brandon@hghitech.com", "super123")
        with demo_cols[2]:
            if st.button("👷 Tech Demo", use_container_width=True):
                set_prefill("mike@hghitech.com", "tech123")
        with demo_cols[3]:
            if st.button("👷 Tech 2", use_container_width=True):
                set_prefill("sarah@hghitech.com", "tech123")

# =========================
# SIDEBAR
# =========================
def role_badge(role: str) -> str:
    cls = "badge-technician"
    if role == "owner":
        cls = "badge-owner"
    elif role == "supervisor":
        cls = "badge-supervisor"
    return f"<span class='badge {cls}'>{role.upper()}</span>"

def sidebar(user):
    with st.sidebar:
        st.markdown(
            f"""
<div class="card">
  <div style="font-size:18px; font-weight:800;">👤 {user['name']}</div>
  <div style="margin-top:6px;">{role_badge(user['role'])}</div>
  <div class="muted" style="margin-top:8px;"><b>Rate:</b> ${user['hourly_rate']:.2f}/hr</div>
  <div class="muted"><b>Status:</b> {user['status']}</div>
</div>
""",
            unsafe_allow_html=True,
        )

        # AI status
        if DEEPSEEK_API_KEY:
            st.success("🤖 DeepSeek AI: Enabled")
        else:
            st.warning("🤖 DeepSeek AI: Not configured (Secrets)")

        st.divider()
        st.markdown("### ⏱️ Time Clock")

        if st.session_state.clocked_in and st.session_state.time_entry_id:
            conn = db()
            c = conn.cursor()
            c.execute("SELECT clock_in FROM time_entries WHERE id=?", (st.session_state.time_entry_id,))
            row = c.fetchone()
            conn.close()

            if row:
                clock_in = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                hours = (datetime.now() - clock_in).total_seconds() / 3600
                st.markdown(f"<div style='font-size:26px; font-weight:900; text-align:center;'>{hours:.2f}h</div>", unsafe_allow_html=True)
                st.caption(f"Clocked in: {clock_in.strftime('%I:%M %p')}")

            if st.button("🛑 Clock Out", use_container_width=True):
                conn = db()
                c = conn.cursor()
                c.execute("SELECT clock_in FROM time_entries WHERE id=?", (st.session_state.time_entry_id,))
                row = c.fetchone()
                clock_in = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S") if row else datetime.now()
                hours = (datetime.now() - clock_in).total_seconds() / 3600
                c.execute("UPDATE time_entries SET clock_out=CURRENT_TIMESTAMP, hours_worked=? WHERE id=?",
                          (hours, st.session_state.time_entry_id))
                conn.commit()
                conn.close()
                st.session_state.clocked_in = False
                st.session_state.time_entry_id = None
                st.success("Clocked out.")
                time.sleep(0.4)
                st.rerun()
        else:
            if st.button("⏰ Clock In", type="primary", use_container_width=True):
                conn = db()
                c = conn.cursor()
                c.execute("INSERT INTO time_entries (contractor_id, clock_in, location) VALUES (?, CURRENT_TIMESTAMP, ?)",
                          (user["id"], "Field Location"))
                conn.commit()
                c.execute("SELECT id FROM time_entries WHERE contractor_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1",
                          (user["id"],))
                row = c.fetchone()
                conn.close()
                if row:
                    st.session_state.clocked_in = True
                    st.session_state.time_entry_id = row[0]
                st.success("Clocked in.")
                time.sleep(0.4)
                st.rerun()

        st.divider()
        st.markdown("### 📱 Navigation")

        if user["role"] in ["owner", "supervisor"]:
            nav = [("dashboard", "📊 Dashboard"), ("parser", "📧 Email Parser"), ("units", "🏢 Unit Explorer")]
        else:
            nav = [("dashboard", "📊 My Dashboard"), ("parser", "📧 Email Parser"), ("units", "🏢 Unit Explorer")]

        for key, label in nav:
            if st.button(label, use_container_width=True):
                st.session_state.page = key
                st.rerun()

        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.session_state.page = "dashboard"
            st.session_state.clocked_in = False
            st.session_state.time_entry_id = None
            st.rerun()

# =========================
# PAGES
# =========================
def header(user):
    st.markdown(
        f"""
<div class="hct-header">
  <h1>🏗️ {COMPANY_NAME} Field System</h1>
  <div>{datetime.now().strftime('%A, %B %d, %Y')} • Welcome back, <b>{user['name']}</b></div>
</div>
""",
        unsafe_allow_html=True,
    )

def page_dashboard(user):
    header(user)

    col1, col2, col3 = st.columns(3)
    col1.metric("Role", user["role"].title())
    col2.metric("Hourly Rate", f"${user['hourly_rate']:.2f}/hr")
    col3.metric("AI Status", "Enabled" if DEEPSEEK_API_KEY else "Off (Secrets)")

    if user["role"] == "owner":
        st.markdown("### 💰 Owner ROI Quick Calculator")
        c1, c2, c3 = st.columns(3)
        with c1:
            old_hours = st.slider("Admin hours/week (before)", 5, 40, 15, 1)
            new_hours = st.slider("Admin hours/week (after)", 0, 10, 2, 1)
        with c2:
            owner_rate = st.number_input("Your time value ($/hr)", min_value=50.0, max_value=500.0, value=150.0, step=25.0)
        with c3:
            contractors = st.number_input("Contractors", min_value=1, max_value=50, value=5, step=1)
            eff_gain = st.slider("Efficiency gain (%)", 0, 30, 10, 5)

        weekly_savings = max(old_hours - new_hours, 0) * owner_rate
        monthly_savings = weekly_savings * 4.33
        contractor_savings = contractors * 10 * 35 * (eff_gain / 100) * 4.33
        total = monthly_savings + contractor_savings

        st.success(f"Estimated savings: **${total:,.0f}/month**")

def page_parser(user):
    header(user)
    st.markdown("### 📧 AI Email Parser (Elauwit)")

    sample = """[Elauwit] T-109040 Created | [ARVA1850] [C-508] HGHI Dispatch Request

Property: ARVA1850 - Cortland on Pike
Unit: C-508
Resident: Tamara Radcliff
Issue: No internet - urgent
Technician needed ASAP"""

    email_text = st.text_area("Paste the email text:", value=sample, height=200)
    use_ai = st.checkbox("Use DeepSeek AI (if enabled)", value=bool(DEEPSEEK_API_KEY))

    if st.button("🚀 Parse Email", type="primary"):
        with st.spinner("Parsing..."):
            result = deepseek_parse_email(email_text) if use_ai else simple_parse_email(email_text)
            st.success(f"Parsed with: **{result['source']}**")
            data = result["data"]

        st.markdown("### ✅ Extracted")
        st.json(data)

        st.divider()
        st.markdown("### 📝 Create Work Order")

        # Load buildings/units
        conn = db()
        buildings = pd.read_sql_query("SELECT id,name FROM buildings ORDER BY name", conn)
        conn.close()

        ticket_id = st.text_input("Ticket ID", value=data.get("ticket_id") or f"T-{int(time.time())}")
        priority = st.selectbox("Priority", ["normal", "high", "urgent"], index=["normal","high","urgent"].index(data.get("priority","normal")))
        description = st.text_area("Description", value=data.get("issue_description") or "", height=100)

        if buildings.empty:
            st.error("No buildings found in database.")
            return

        building_name = st.selectbox("Property", buildings["name"].tolist())
        building_id = int(buildings[buildings["name"] == building_name].iloc[0]["id"])

        conn = db()
        units = pd.read_sql_query("SELECT id,unit_number FROM units WHERE building_id=? ORDER BY unit_number", conn, params=(building_id,))
        techs = pd.read_sql_query("SELECT id,name FROM contractors WHERE role='technician' AND status='active' ORDER BY name", conn)
        conn.close()

        unit_number = st.selectbox("Unit", units["unit_number"].tolist())
        unit_id = int(units[units["unit_number"] == unit_number].iloc[0]["id"])

        assigned_to = st.selectbox("Assign To", ["Unassigned"] + techs["name"].tolist()) if user["role"] in ["owner","supervisor"] else user["name"]

        if st.button("✅ Save Work Order"):
            conn = db()
            c = conn.cursor()
            contractor_id = None
            if assigned_to != "Unassigned":
                c.execute("SELECT id FROM contractors WHERE name=?", (assigned_to,))
                r = c.fetchone()
                contractor_id = r[0] if r else None

            c.execute(
                """INSERT INTO work_orders (ticket_id, unit_id, contractor_id, description, priority, status, email_text)
                   VALUES (?, ?, ?, ?, ?, 'open', ?)""",
                (ticket_id, unit_id, contractor_id, description, priority, email_text),
            )
            conn.commit()
            conn.close()
            st.success(f"Saved work order: {ticket_id}")

def page_units(user):
    header(user)
    st.markdown("### 🏢 Unit Explorer")

    conn = db()
    buildings = pd.read_sql_query("SELECT id,name,address FROM buildings ORDER BY name", conn)
    conn.close()

    if buildings.empty:
        st.error("No buildings found.")
        return

    bname = st.selectbox("Select Property", buildings["name"].tolist())
    bid = int(buildings[buildings["name"] == bname].iloc[0]["id"])

    conn = db()
    units = pd.read_sql_query(
        "SELECT id,unit_number,resident_name,status,notes FROM units WHERE building_id=? ORDER BY unit_number",
        conn,
        params=(bid,),
    )
    conn.close()

    if units.empty:
        st.warning("No units found for this property.")
        return

    selection = st.selectbox(
        "Select Unit",
        units.apply(lambda r: f"{r['unit_number']} — {r['resident_name']}", axis=1).tolist(),
    )
    unit_number = selection.split(" — ")[0].strip()
    urow = units[units["unit_number"] == unit_number].iloc[0]

    st.markdown(
        f"""
<div class="card">
  <h4>🏠 Unit {urow['unit_number']}</h4>
  <div><b>Resident:</b> {urow['resident_name']}</div>
  <div><b>Status:</b> {urow['status']}</div>
  <div><b>Notes:</b> {urow['notes'] or "—"}</div>
</div>
""",
        unsafe_allow_html=True,
    )

    st.markdown("### 📋 Recent Work Orders (Unit)")
    conn = db()
    wos = pd.read_sql_query(
        """
        SELECT wo.ticket_id, wo.description, wo.priority, wo.status, wo.created_date,
               c.name as contractor
        FROM work_orders wo
        LEFT JOIN contractors c ON wo.contractor_id=c.id
        WHERE wo.unit_id=?
        ORDER BY wo.created_date DESC
        LIMIT 10
        """,
        conn,
        params=(int(urow["id"]),),
    )
    conn.close()

    if wos.empty:
        st.info("No work orders logged for this unit yet.")
    else:
        for _, r in wos.iterrows():
            st.markdown(
                f"""
<div class="card">
  <div style="font-weight:900;">{r['ticket_id']} <span class="muted">({r['priority']})</span></div>
  <div>{r['description']}</div>
  <div class="muted">Status: {r['status']} • Tech: {r['contractor'] or "Unassigned"} • Created: {r['created_date']}</div>
</div>
""",
                unsafe_allow_html=True,
            )

# =========================
# ROUTER
# =========================
if not st.session_state.logged_in:
    login_page()
    st.stop()

user = st.session_state.user
sidebar(user)

page = st.session_state.page

if page == "dashboard":
    page_dashboard(user)
elif page == "parser":
    page_parser(user)
elif page == "units":
    page_units(user)
else:
    page_dashboard(user)

st.divider()
st.markdown(
    f"<div style='text-align:center' class='muted'>© {datetime.now().year} {COMPANY_NAME} • Powered by DeepSeek (optional)</div>",
    unsafe_allow_html=True,
)
