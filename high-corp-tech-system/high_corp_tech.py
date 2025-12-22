import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import json
import re
import requests
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta
from io import BytesIO, StringIO

# =========================================================
# CONFIG (use Streamlit Secrets, not hardcoded keys)
# =========================================================
APP_NAME = "HGHI Tech Field Management"
DB_PATH = "field_management.db"

def get_secret(name: str, default=None):
    try:
        return st.secrets.get(name, default)
    except Exception:
        return default

DEEPSEEK_API_KEY = get_secret("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = get_secret("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")

SMTP_HOST = get_secret("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(get_secret("SMTP_PORT", 587))
SMTP_USER = get_secret("SMTP_USER", "")   # e.g. reports@fiberops-hghitechs.com
SMTP_PASS = get_secret("SMTP_PASS", "")   # Google App Password (NOT normal password)

COMPANY_DOMAIN = "fiberops-hghitechs.com"  # confirmed by you
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]

st.set_page_config(page_title=APP_NAME, page_icon="🏗️", layout="wide")

# =========================================================
# UI STYLE
# =========================================================
st.markdown("""
<style>
.header {
  background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
  color: white;
  padding: 18px 20px;
  border-radius: 14px;
  margin-bottom: 16px;
}
.card {
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 14px;
  margin: 10px 0;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.muted { color: #6b7280; font-size: 0.92rem; }
.badge {
  display:inline-block; padding:4px 10px; border-radius:999px;
  font-size:0.8rem; font-weight:700;
}
.owner { background:#fef3c7; color:#92400e; }
.supervisor { background:#dbeafe; color:#1e40af; }
.technician { background:#d1fae5; color:#065f46; }
.admin { background:#ede9fe; color:#5b21b6; }
.pending { background:#f3f4f6; color:#6b7280; }
.small { font-size: 0.9rem; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 14px 0; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# SESSION STATE (safe defaults)
# =========================================================
def ss_setdefault(key, value):
    if key not in st.session_state:
        st.session_state[key] = value

ss_setdefault("logged_in", False)
ss_setdefault("user", None)
ss_setdefault("current_page", "Dashboard")
ss_setdefault("login_prefill", {"email": "", "password": ""})
ss_setdefault("clocked_in", False)
ss_setdefault("active_time_entry_id", None)

# =========================================================
# DATABASE
# =========================================================
def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        hourly_rate REAL NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS buildings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        name TEXT NOT NULL,
        address TEXT,
        property_manager TEXT,
        city TEXT,
        state TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        building_id INTEGER NOT NULL,
        unit_number TEXT NOT NULL,
        resident_name TEXT,
        unit_type TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        notes TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(building_id, unit_number),
        FOREIGN KEY(building_id) REFERENCES buildings(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS equipment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER NOT NULL,
        equipment_type TEXT,
        serial_number TEXT,
        manufacturer TEXT,
        model TEXT,
        status TEXT DEFAULT 'active',
        notes TEXT,
        installed_at TEXT,
        last_service_at TEXT,
        UNIQUE(serial_number),
        FOREIGN KEY(unit_id) REFERENCES units(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT UNIQUE,
        building_id INTEGER,
        unit_id INTEGER,
        description TEXT,
        priority TEXT DEFAULT 'normal',
        status TEXT DEFAULT 'open',
        created_by INTEGER,
        assigned_to INTEGER,
        created_at TEXT NOT NULL,
        source TEXT,
        raw_text TEXT,
        FOREIGN KEY(building_id) REFERENCES buildings(id),
        FOREIGN KEY(unit_id) REFERENCES units(id),
        FOREIGN KEY(created_by) REFERENCES contractors(id),
        FOREIGN KEY(assigned_to) REFERENCES contractors(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS unit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        building_id INTEGER NOT NULL,
        unit_id INTEGER NOT NULL,
        created_by INTEGER NOT NULL,
        log_type TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(building_id) REFERENCES buildings(id),
        FOREIGN KEY(unit_id) REFERENCES units(id),
        FOREIGN KEY(created_by) REFERENCES contractors(id)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER NOT NULL,
        clock_in TEXT NOT NULL,
        clock_out TEXT,
        location TEXT,
        hours_worked REAL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(contractor_id) REFERENCES contractors(id)
    )
    """)

    conn.commit()
    conn.close()

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def upsert_default_users():
    """
    Creates/updates your real users (so boss can log in immediately).
    Passwords are set here for first launch; change after login.
    """
    defaults = [
        # name, email, password, role, status, hourly_rate
        ("Darrell Kelly", "darrell@fiberops-hghitechs.com", "Owner123!", "owner", "active", 0.0),
        ("Brandon Alves", "brandon@fiberops-hghitechs.com", "Super123!", "supervisor", "active", 0.0),
        ("Andre Ampey", "andre@fiberops-hghitechs.com", "Super123!", "supervisor", "active", 0.0),

        ("Walter Chandler", "walter@fiberops-hghitechs.com", "Tech123!", "technician", "active", 40.0),
        ("Rasheed Rouse", "rasheed@fiberops-hghitechs.com", "Tech123!", "technician", "active", 40.0),
        ("Dale Vester", "dale@fiberops-hghitechs.com", "Tech123!", "technician", "active", 40.0),

        # If Darrell is also working in the field sometimes:
        # Keep his role owner; assign tickets to him when needed.
    ]

    conn = db()
    c = conn.cursor()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    for name, email, pw, role, status, rate in defaults:
        c.execute("SELECT id FROM contractors WHERE email=?", (email,))
        row = c.fetchone()
        if row:
            c.execute("""
                UPDATE contractors
                SET name=?, role=?, status=?, hourly_rate=?
                WHERE email=?
            """, (name, role, status, rate, email))
        else:
            c.execute("""
                INSERT INTO contractors (name,email,password_hash,role,status,hourly_rate,created_at)
                VALUES (?,?,?,?,?,?,?)
            """, (name, email, hash_password(pw), role, status, rate, now))

    conn.commit()
    conn.close()

init_db()
upsert_default_users()

# =========================================================
# AI (DeepSeek)
# =========================================================
def deepseek_chat(messages, temperature=0.2, max_tokens=600, timeout=8):
    """
    Bullet-proof call: if anything fails, return None.
    """
    if not DEEPSEEK_API_KEY:
        return None

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        r = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"]
        return None
    except Exception:
        return None

def parse_elauwit_email(email_text: str) -> dict:
    """
    AI first, fallback to regex.
    Returns dict with ticket_id, property_code/name, unit, resident, priority, description
    """
    # AI attempt
    ai = deepseek_chat(
        [
            {"role": "system", "content":
             "Parse the following work order email. Return ONLY valid JSON with keys: "
             "ticket_id, property_code, property_name, unit_number, resident_name, priority, issue_description, notes."},
            {"role": "user", "content": email_text}
        ],
        temperature=0.1,
        max_tokens=400,
        timeout=6
    )
    if ai:
        m = re.search(r"\{.*\}", ai, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass

    # Fallback regex (never breaks demo)
    def find(pattern, default=None):
        mm = re.search(pattern, email_text, re.IGNORECASE)
        return mm.group(1).strip() if mm else default

    ticket = find(r"(T[-_ ]?\d{5,8})", None)
    prop_code = find(r"\[([A-Z0-9]{4,})\]", None)  # first bracket token
    unit = find(r"\[([A-Z]-?\d{1,4})\]", None)

    resident = find(r"Resident[:\s]+([A-Za-z][A-Za-z\s\.\-']+)", None)
    issue = find(r"Issue[:\s]+(.+)", None) or email_text.strip().splitlines()[-1][:200]

    lower = email_text.lower()
    if "urgent" in lower or "asap" in lower:
        priority = "urgent"
    elif "high" in lower:
        priority = "high"
    else:
        priority = "normal"

    return {
        "ticket_id": ticket,
        "property_code": prop_code,
        "property_name": None,
        "unit_number": unit,
        "resident_name": resident,
        "priority": priority,
        "issue_description": issue,
        "notes": None
    }

def ai_generate_unit_report(unit_context: dict, raw_text: str) -> str:
    """
    Takes unit context + raw notes/chat/email and creates a professional report.
    """
    prompt = f"""
You are HGHI Tech's operations reporting assistant.
Write a professional, detailed service report for a single unit.

Unit Context (JSON):
{json.dumps(unit_context, indent=2)}

Raw Field Notes / Chat / Email:
{raw_text}

Report requirements:
- Title line: "Unit Service Report"
- Include: Property, Unit, Date/Time, Technician/Supervisor (if available)
- Bullet steps: What was done (specific)
- Equipment/Serials (if mentioned)
- Fiber work vs construction work (if present)
- Test results (speed/levels if present)
- Issues found + recommendations
- Next actions (if any)
Return in clean Markdown.
"""
    out = deepseek_chat([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=700, timeout=10)
    if out:
        return out.strip()
    # Fallback: simple
    return f"""# Unit Service Report

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

## Summary
{raw_text[:1200]}

## Recommendations
- Verify service quality and confirm resident connectivity.
- Record any equipment serial numbers in the unit equipment section.
"""

# =========================================================
# AUTH
# =========================================================
def verify_login(email: str, password: str):
    conn = db()
    c = conn.cursor()
    c.execute("""
        SELECT id, name, email, role, status, hourly_rate
        FROM contractors
        WHERE email=? AND password_hash=?
    """, (email.strip().lower(), hash_password(password)))
    row = c.fetchone()
    conn.close()
    if not row:
        return None, "Invalid email or password."
    if row[4] != "active":
        return None, f"Account status is '{row[4]}'. Contact supervisor."
    return {
        "id": row[0],
        "name": row[1],
        "email": row[2],
        "role": row[3],
        "status": row[4],
        "hourly_rate": float(row[5])
    }, "OK"

def role_badge(role: str):
    cls = role if role in ("owner", "supervisor", "technician", "admin") else "pending"
    return f"<span class='badge {cls}'>{role.upper()}</span>"

# =========================================================
# BUILDING/UNIT IMPORT (CSV)
# =========================================================
def normalize_cols(df: pd.DataFrame):
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    return df

def import_buildings_units_from_csv(file_bytes: bytes):
    """
    Accepts a CSV that might contain:
    - building_name / name
    - building_code / code
    - address
    - property_manager
    - city, state
    - unit_number
    - resident_name
    - serial_number / equipment_serial
    - equipment_type, manufacturer, model
    If your CSV is buildings-only, it still imports buildings.
    If it contains units, it imports units.
    If it contains serials, it imports equipment.
    """
    df = pd.read_csv(BytesIO(file_bytes))
    df = normalize_cols(df)

    # Best-effort column detection
    b_name = "building_name" if "building_name" in df.columns else ("name" if "name" in df.columns else None)
    b_code = "building_code" if "building_code" in df.columns else ("code" if "code" in df.columns else None)
    addr = "address" if "address" in df.columns else None
    pm = "property_manager" if "property_manager" in df.columns else None
    city = "city" if "city" in df.columns else None
    state = "state" if "state" in df.columns else None

    unit_col = "unit_number" if "unit_number" in df.columns else ("unit" if "unit" in df.columns else None)
    resident_col = "resident_name" if "resident_name" in df.columns else ("resident" if "resident" in df.columns else None)

    serial_col = None
    for cand in ["serial_number", "equipment_serial", "serial", "sn"]:
        if cand in df.columns:
            serial_col = cand
            break

    equip_type_col = "equipment_type" if "equipment_type" in df.columns else None
    manu_col = "manufacturer" if "manufacturer" in df.columns else None
    model_col = "model" if "model" in df.columns else None

    if not b_name:
        raise ValueError("CSV must include a building name column: building_name or name")

    conn = db()
    c = conn.cursor()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    imported_buildings = 0
    imported_units = 0
    imported_equipment = 0

    # Cache building ids by (code,name,address)
    b_cache = {}

    for _, r in df.iterrows():
        name_val = str(r.get(b_name, "")).strip()
        if not name_val:
            continue
        code_val = str(r.get(b_code, "")).strip() if b_code else None
        addr_val = str(r.get(addr, "")).strip() if addr else None
        pm_val = str(r.get(pm, "")).strip() if pm else None
        city_val = str(r.get(city, "")).strip() if city else None
        state_val = str(r.get(state, "")).strip() if state else None

        key = (code_val or "", name_val, addr_val or "")
        if key in b_cache:
            building_id = b_cache[key]
        else:
            # find existing building
            c.execute("""
                SELECT id FROM buildings
                WHERE name=? AND COALESCE(address,'')=COALESCE(?, '')
            """, (name_val, addr_val))
            ex = c.fetchone()
            if ex:
                building_id = ex[0]
                c.execute("""
                    UPDATE buildings SET code=?, property_manager=?, city=?, state=?
                    WHERE id=?
                """, (code_val, pm_val, city_val, state_val, building_id))
            else:
                c.execute("""
                    INSERT INTO buildings (code,name,address,property_manager,city,state,status,created_at)
                    VALUES (?,?,?,?,?,?, 'active', ?)
                """, (code_val, name_val, addr_val, pm_val, city_val, state_val, now))
                building_id = c.lastrowid
                imported_buildings += 1
            b_cache[key] = building_id

        # Units (optional)
        unit_val = str(r.get(unit_col, "")).strip() if unit_col else ""
        if unit_val:
            resident_val = str(r.get(resident_col, "")).strip() if resident_col else None
            c.execute("""
                SELECT id FROM units WHERE building_id=? AND unit_number=?
            """, (building_id, unit_val))
            u = c.fetchone()
            if u:
                unit_id = u[0]
                # update resident if present
                if resident_val:
                    c.execute("UPDATE units SET resident_name=? WHERE id=?", (resident_val, unit_id))
            else:
                c.execute("""
                    INSERT INTO units (building_id, unit_number, resident_name, unit_type, status, notes, created_at)
                    VALUES (?,?,?,?, 'active', NULL, ?)
                """, (building_id, unit_val, resident_val, None, now))
                unit_id = c.lastrowid
                imported_units += 1

            # Equipment (optional)
            if serial_col:
                serial_val = str(r.get(serial_col, "")).strip()
                if serial_val:
                    et = str(r.get(equip_type_col, "")).strip() if equip_type_col else None
                    mf = str(r.get(manu_col, "")).strip() if manu_col else None
                    md = str(r.get(model_col, "")).strip() if model_col else None
                    # upsert equipment by serial (unique)
                    c.execute("SELECT id FROM equipment WHERE serial_number=?", (serial_val,))
                    e = c.fetchone()
                    if e:
                        c.execute("""
                            UPDATE equipment SET unit_id=?, equipment_type=?, manufacturer=?, model=?
                            WHERE id=?
                        """, (unit_id, et, mf, md, e[0]))
                    else:
                        c.execute("""
                            INSERT INTO equipment (unit_id,equipment_type,serial_number,manufacturer,model,status,notes,installed_at,last_service_at)
                            VALUES (?,?,?,?,?, 'active', NULL, ?, NULL)
                        """, (unit_id, et, serial_val, mf, md, now))
                        imported_equipment += 1

    conn.commit()
    conn.close()

    return imported_buildings, imported_units, imported_equipment

# =========================================================
# SEARCH
# =========================================================
def global_search(q: str) -> pd.DataFrame:
    q = (q or "").strip()
    if not q:
        return pd.DataFrame()

    conn = db()
    query = """
    SELECT
      b.name AS building,
      b.address AS address,
      u.unit_number AS unit,
      u.resident_name AS resident,
      e.serial_number AS serial,
      e.equipment_type AS equipment_type,
      e.manufacturer AS manufacturer,
      e.model AS model,
      b.id AS building_id,
      u.id AS unit_id
    FROM buildings b
    LEFT JOIN units u ON u.building_id=b.id
    LEFT JOIN equipment e ON e.unit_id=u.id
    WHERE
      LOWER(b.name) LIKE LOWER(?)
      OR LOWER(COALESCE(b.address,'')) LIKE LOWER(?)
      OR LOWER(COALESCE(u.unit_number,'')) LIKE LOWER(?)
      OR LOWER(COALESCE(u.resident_name,'')) LIKE LOWER(?)
      OR LOWER(COALESCE(e.serial_number,'')) LIKE LOWER(?)
    LIMIT 500
    """
    like = f"%{q}%"
    df = pd.read_sql_query(query, conn, params=(like, like, like, like, like))
    conn.close()
    return df

# =========================================================
# REPORT EXPORTS + EMAIL
# =========================================================
def unit_context(building_id: int, unit_id: int):
    conn = db()
    b = pd.read_sql_query("SELECT * FROM buildings WHERE id=?", conn, params=(building_id,))
    u = pd.read_sql_query("SELECT * FROM units WHERE id=?", conn, params=(unit_id,))
    e = pd.read_sql_query("SELECT * FROM equipment WHERE unit_id=?", conn, params=(unit_id,))
    conn.close()
    ctx = {
        "building": b.iloc[0].to_dict() if not b.empty else {},
        "unit": u.iloc[0].to_dict() if not u.empty else {},
        "equipment": e.to_dict("records") if not e.empty else [],
    }
    return ctx

def fetch_unit_logs(building_id: int, unit_id: int) -> pd.DataFrame:
    conn = db()
    df = pd.read_sql_query("""
        SELECT ul.id, ul.created_at, ul.log_type, ul.title, ul.content, c.name AS created_by
        FROM unit_logs ul
        JOIN contractors c ON c.id=ul.created_by
        WHERE ul.building_id=? AND ul.unit_id=?
        ORDER BY ul.created_at DESC
    """, conn, params=(building_id, unit_id))
    conn.close()
    return df

def save_unit_log(building_id: int, unit_id: int, created_by: int, log_type: str, title: str, content: str):
    conn = db()
    c = conn.cursor()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO unit_logs (building_id, unit_id, created_by, log_type, title, content, created_at)
        VALUES (?,?,?,?,?,?,?)
    """, (building_id, unit_id, created_by, log_type, title, content, now))
    conn.commit()
    conn.close()

def send_email_report(to_email: str, subject: str, body_md: str, attachment_name: str = None, attachment_bytes: bytes = None):
    """
    Uses SMTP_USER/SMTP_PASS (Google Workspace requires an App Password if 2FA is enabled).
    """
    if not (SMTP_USER and SMTP_PASS):
        return False, "SMTP is not configured in Streamlit Secrets."

    msg = EmailMessage()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_md)

    if attachment_name and attachment_bytes:
        msg.add_attachment(attachment_bytes, maintype="application", subtype="octet-stream", filename=attachment_name)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True, "Email sent."
    except Exception as e:
        return False, f"Email failed: {str(e)[:120]}"

# =========================================================
# TIME CLOCK
# =========================================================
def get_open_time_entry(contractor_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT id, clock_in FROM time_entries WHERE contractor_id=? AND clock_out IS NULL", (contractor_id,))
    row = c.fetchone()
    conn.close()
    return row

def clock_in(contractor_id: int, location: str):
    conn = db()
    c = conn.cursor()
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("""
        INSERT INTO time_entries (contractor_id, clock_in, location, created_at)
        VALUES (?, ?, ?, ?)
    """, (contractor_id, now, location, now))
    conn.commit()
    c.execute("SELECT id FROM time_entries WHERE contractor_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1", (contractor_id,))
    tid = c.fetchone()[0]
    conn.close()
    return tid

def clock_out(entry_id: int):
    conn = db()
    c = conn.cursor()
    c.execute("SELECT clock_in FROM time_entries WHERE id=?", (entry_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return False

    clock_in_ts = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    now_ts = datetime.utcnow()
    hours = (now_ts - clock_in_ts).total_seconds() / 3600.0

    c.execute("""
        UPDATE time_entries
        SET clock_out=?, hours_worked=?
        WHERE id=?
    """, (now_ts.strftime("%Y-%m-%d %H:%M:%S"), hours, entry_id))
    conn.commit()
    conn.close()
    return True

# =========================================================
# LOGIN PAGE (FIXED DEMO BUTTONS)
# =========================================================
def login_page():
    st.markdown(f"""
    <div class="header">
      <h2 style="margin:0;">🏢 {COMPANY_NAME}</h2>
      <div class="muted">{APP_NAME}</div>
    </div>
    """, unsafe_allow_html=True)

    # Prefill values (safe)
    pre = st.session_state.get("login_prefill", {"email": "", "password": ""})
    ss_setdefault("login_email", pre.get("email", ""))
    ss_setdefault("login_password", pre.get("password", ""))

    col1, col2, col3 = st.columns([1, 1.4, 1])
    with col2:
        st.subheader("🔐 Login")

        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_password")

        if st.button("🚀 Login", type="primary", use_container_width=True):
            user, msg = verify_login(email, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.user = user

                # restore open time entry (if any)
                open_entry = get_open_time_entry(user["id"])
                if open_entry:
                    st.session_state.clocked_in = True
                    st.session_state.active_time_entry_id = open_entry[0]
                else:
                    st.session_state.clocked_in = False
                    st.session_state.active_time_entry_id = None

                st.success(f"Welcome, {user['name']}!")
                st.rerun()
            else:
                st.error(msg)

        st.markdown("----")
        st.caption("✅ Demo quick-fill buttons (these now work).")
        d1, d2, d3 = st.columns(3)

        def set_demo(email, pw):
            # IMPORTANT: set prefill + clear widget keys safely by updating state, then rerun
            st.session_state.login_prefill = {"email": email, "password": pw}
            # reset widget keys
            st.session_state.login_email = email
            st.session_state.login_password = pw
            st.rerun()

        with d1:
            if st.button("👑 Owner (Darrell)", use_container_width=True):
                set_demo("darrell@fiberops-hghitechs.com", "Owner123!")
        with d2:
            if st.button("👨‍💼 Supervisor", use_container_width=True):
                set_demo("brandon@fiberops-hghitechs.com", "Super123!")
        with d3:
            if st.button("👷 Technician", use_container_width=True):
                set_demo("walter@fiberops-hghitechs.com", "Tech123!")

# =========================================================
# SIDEBAR + NAV
# =========================================================
def sidebar(user):
    with st.sidebar:
        st.markdown(f"""
        <div class="card">
          <div style="font-weight:800; font-size:1.05rem;">👤 {user['name']}</div>
          <div style="margin-top:6px;">{role_badge(user['role'])}</div>
          <div class="muted" style="margin-top:6px;">{user['email']}</div>
        </div>
        """, unsafe_allow_html=True)

        # AI status
        if DEEPSEEK_API_KEY:
            st.success("🤖 DeepSeek AI: Enabled")
        else:
            st.warning("🤖 DeepSeek AI: Not configured (set DEEPSEEK_API_KEY in Secrets).")

        st.markdown("### ⏱️ Time Clock")
        if st.session_state.clocked_in and st.session_state.active_time_entry_id:
            st.success("Clocked in ✅")
            if st.button("🛑 Clock Out", use_container_width=True):
                ok = clock_out(st.session_state.active_time_entry_id)
                if ok:
                    st.session_state.clocked_in = False
                    st.session_state.active_time_entry_id = None
                    st.rerun()
        else:
            loc = st.text_input("Location (optional)", value="Field", key="clock_location")
            if st.button("⏰ Clock In", type="primary", use_container_width=True):
                tid = clock_in(user["id"], loc)
                st.session_state.clocked_in = True
                st.session_state.active_time_entry_id = tid
                st.rerun()

        st.markdown("----")
        st.markdown("### 📍 Navigation")

        if user["role"] in ("owner", "supervisor", "admin"):
            pages = [
                "Dashboard",
                "Import (CSV)",
                "Search",
                "Buildings & Units",
                "Unit Reports",
                "Email Parser",
                "WhatsApp Import",
                "Time & Payroll",
                "Settings",
            ]
        else:
            pages = [
                "Dashboard",
                "Search",
                "Buildings & Units",
                "Unit Reports",
                "WhatsApp Import",
                "Time & Payroll",
            ]

        current = st.session_state.current_page
        choice = st.radio("Go to", pages, index=pages.index(current) if current in pages else 0)
        st.session_state.current_page = choice

        st.markdown("----")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.session_state.current_page = "Dashboard"
            st.session_state.clocked_in = False
            st.session_state.active_time_entry_id = None
            st.rerun()

# =========================================================
# PAGES
# =========================================================
def page_dashboard(user):
    st.markdown(f"""
    <div class="header">
      <h2 style="margin:0;">🏢 {COMPANY_NAME} Field Ops</h2>
      <div class="muted">Welcome back, {user['name']} • {datetime.now().strftime('%A, %b %d, %Y')}</div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)

    conn = db()
    buildings = pd.read_sql_query("SELECT COUNT(*) AS n FROM buildings", conn)["n"][0]
    units = pd.read_sql_query("SELECT COUNT(*) AS n FROM units", conn)["n"][0]
    equips = pd.read_sql_query("SELECT COUNT(*) AS n FROM equipment", conn)["n"][0]
    logs = pd.read_sql_query("SELECT COUNT(*) AS n FROM unit_logs", conn)["n"][0]
    conn.close()

    c1.metric("Buildings", int(buildings))
    c2.metric("Units", int(units))
    c3.metric("Serials/Equipment", int(equips))
    c4.metric("Unit Reports/Logs", int(logs))

    st.markdown("### ✅ Boss Demo Path (never breaks)")
    st.info(
        "1) Import CSV (if not already)\n"
        "2) Search unit/serial\n"
        "3) Open Unit Reports → Generate AI Report → Export/Email"
    )

    if user["role"] == "owner":
        st.markdown("### 💰 ROI Calculator (Owner)")
        col1, col2, col3 = st.columns(3)
        with col1:
            old_hours = st.slider("Admin hours/week (before)", 5, 40, 15)
        with col2:
            hourly_value = st.number_input("Your time value ($/hr)", min_value=50, max_value=500, value=150, step=25)
        with col3:
            techs = st.number_input("Number of techs", min_value=1, max_value=50, value=5)
        weekly_savings = max(old_hours - 2, 0) * hourly_value
        monthly = weekly_savings * 4.33
        st.success(f"Estimated savings: **${monthly:,.0f}/month** (just from admin time)")

def page_import_csv(user):
    st.subheader("📥 Import Buildings/Units/Serials (CSV)")

    st.write("Upload your CSV with buildings and optionally units + serial numbers. This is what makes Search work.")

    up = st.file_uploader("Upload CSV", type=["csv"])
    if up:
        preview = pd.read_csv(up)
        st.write("Preview:")
        st.dataframe(preview.head(30), use_container_width=True)

        if st.button("✅ Import into System", type="primary"):
            try:
                b, u, e = import_buildings_units_from_csv(up.getvalue())
                st.success(f"Imported: {b} new buildings, {u} new units, {e} new equipment/serials.")
            except Exception as ex:
                st.error(f"Import failed: {ex}")

    st.markdown("----")
    st.markdown("### CSV Column Examples (flexible)")
    st.code(
        "building_name,building_code,address,property_manager,city,state,unit_number,resident_name,equipment_type,serial_number,manufacturer,model\n"
        "Cortland on Pike,ARVA1850,123 Pike St,Elauwit,Arlington,VA,C-508,Tamara Radcliff,ONT,ABC123456,Nokia,XS-010X\n"
    )

def page_search(user):
    st.subheader("🔎 Global Search (Building / Unit / Serial / Resident)")
    q = st.text_input("Search anything (ex: ARVA1850, C-508, ABC123456, Cortland, Tamara)")
    df = global_search(q)
    if df.empty:
        st.info("No results yet. Import CSV first (Import tab).")
        return

    st.dataframe(df, use_container_width=True)

    st.markdown("### Open a result")
    pick = st.selectbox(
        "Select a row to open unit",
        df.apply(lambda r: f"{r['building']} | Unit {r['unit']} | Serial {r['serial']}", axis=1).tolist()
    )
    if st.button("Open Unit Reports", type="primary"):
        row = df.iloc[df.apply(lambda r: f"{r['building']} | Unit {r['unit']} | Serial {r['serial']}", axis=1).tolist().index(pick)]
        st.session_state["open_building_id"] = int(row["building_id"]) if pd.notna(row["building_id"]) else None
        st.session_state["open_unit_id"] = int(row["unit_id"]) if pd.notna(row["unit_id"]) else None
        st.session_state.current_page = "Unit Reports"
        st.rerun()

def page_buildings_units(user):
    st.subheader("🏢 Buildings & Units")

    conn = db()
    bdf = pd.read_sql_query("SELECT id, code, name, address, property_manager, city, state FROM buildings ORDER BY name", conn)
    conn.close()

    if bdf.empty:
        st.info("No buildings found. Import CSV first.")
        return

    bname = st.selectbox(
        "Select building",
        bdf.apply(lambda r: f"{r['name']} ({r['code'] or 'no-code'})", axis=1).tolist()
    )
    b_row = bdf.iloc[bdf.apply(lambda r: f"{r['name']} ({r['code'] or 'no-code'})", axis=1).tolist().index(bname)]
    building_id = int(b_row["id"])

    st.markdown(f"<div class='card'><b>{b_row['name']}</b><div class='muted'>{b_row['address'] or ''}</div></div>", unsafe_allow_html=True)

    conn = db()
    udf = pd.read_sql_query("""
        SELECT id, unit_number, resident_name, status, notes
        FROM units WHERE building_id=?
        ORDER BY unit_number
    """, conn, params=(building_id,))
    conn.close()

    if udf.empty:
        st.warning("No units found for this building.")
        return

    unit_label = st.selectbox(
        "Select unit",
        udf.apply(lambda r: f"{r['unit_number']} — {r['resident_name'] or 'No resident'}", axis=1).tolist()
    )
    u_row = udf.iloc[udf.apply(lambda r: f"{r['unit_number']} — {r['resident_name'] or 'No resident'}", axis=1).tolist().index(unit_label)]
    unit_id = int(u_row["id"])

    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown("### Unit Details")
        st.write(f"**Unit:** {u_row['unit_number']}")
        st.write(f"**Resident:** {u_row['resident_name'] or '—'}")
        st.write(f"**Status:** {u_row['status']}")
    with col2:
        if st.button("Open Unit Reports", type="primary", use_container_width=True):
            st.session_state["open_building_id"] = building_id
            st.session_state["open_unit_id"] = unit_id
            st.session_state.current_page = "Unit Reports"
            st.rerun()

    st.markdown("### Equipment / Serials in this unit")
    conn = db()
    edf = pd.read_sql_query("""
        SELECT equipment_type, serial_number, manufacturer, model, status, notes
        FROM equipment WHERE unit_id=?
        ORDER BY equipment_type, serial_number
    """, conn, params=(unit_id,))
    conn.close()

    if edf.empty:
        st.info("No equipment recorded for this unit yet.")
    else:
        st.dataframe(edf, use_container_width=True)

def page_unit_reports(user):
    st.subheader("📄 Unit Reports (view / generate / export / email)")

    # Pick from search context if present
    building_id = st.session_state.get("open_building_id", None)
    unit_id = st.session_state.get("open_unit_id", None)

    conn = db()
    bdf = pd.read_sql_query("SELECT id, name FROM buildings ORDER BY name", conn)
    conn.close()

    if bdf.empty:
        st.info("No buildings yet. Import CSV first.")
        return

    # If not set, pick manually
    if not building_id:
        building_id = int(st.selectbox("Building", bdf["name"].tolist(), index=0, key="rep_building_pick") and bdf.iloc[0]["id"])
    else:
        # show label
        pass

    # Resolve building name
    bname = bdf[bdf["id"] == building_id]["name"].iloc[0] if (bdf["id"] == building_id).any() else "Building"

    conn = db()
    udf = pd.read_sql_query("SELECT id, unit_number, resident_name FROM units WHERE building_id=? ORDER BY unit_number", conn, params=(building_id,))
    conn.close()

    if udf.empty:
        st.warning("No units for this building.")
        return

    if not unit_id:
        label = st.selectbox("Unit", udf.apply(lambda r: f"{r['unit_number']} — {r['resident_name'] or ''}", axis=1).tolist())
        unit_id = int(udf.iloc[udf.apply(lambda r: f"{r['unit_number']} — {r['resident_name'] or ''}", axis=1).tolist().index(label)]["id"])
    else:
        pass

    urow = udf[udf["id"] == unit_id].iloc[0]
    unit_number = urow["unit_number"]

    st.markdown(f"<div class='card'><b>{bname}</b><div class='muted'>Unit {unit_number}</div></div>", unsafe_allow_html=True)

    # Existing logs
    logs = fetch_unit_logs(building_id, unit_id)
    if logs.empty:
        st.info("No reports/logs saved for this unit yet.")
    else:
        st.markdown("### Saved Reports/Logs")
        for _, r in logs.iterrows():
            with st.expander(f"{r['created_at']} • {r['log_type'].upper()} • {r['title']} • by {r['created_by']}"):
                st.markdown(r["content"])

    st.markdown("----")
    st.markdown("### Create a new report/log")

    tab1, tab2, tab3 = st.tabs(["Manual Notes → Report", "Email/Text → Report", "WhatsApp Export → Report"])

    ctx = unit_context(building_id, unit_id)

    def report_actions(report_md: str, default_title: str):
        c1, c2, c3 = st.columns([1.2, 1.2, 1.6])

        with c1:
            if st.button("💾 Save to Unit Logs", type="primary"):
                save_unit_log(building_id, unit_id, user["id"], "report", default_title, report_md)
                st.success("Saved.")
                st.rerun()

        with c2:
            # Export as markdown/text
            st.download_button(
                "⬇️ Download (Markdown)",
                data=report_md,
                file_name=f"{bname}_Unit_{unit_number}_report.md".replace(" ", "_"),
                mime="text/markdown"
            )

        with c3:
            st.caption("Email requires SMTP secrets (optional).")
            to = st.text_input("Email to:", value=user["email"], key=f"email_to_{unit_id}")
            subj = st.text_input("Subject:", value=f"Unit Report: {bname} - {unit_number}", key=f"email_subj_{unit_id}")
            if st.button("📧 Send Email", use_container_width=True):
                ok, msg = send_email_report(to, subj, report_md)
                (st.success if ok else st.error)(msg)

    with tab1:
        notes = st.text_area("Enter what was done in this unit (steps, equipment, fiber work, construction work, tests, etc.)", height=180)
        if st.button("🤖 Generate Professional Report", type="primary", disabled=not notes.strip()):
            report = ai_generate_unit_report(ctx, notes)
            st.markdown("#### Generated Report")
            st.markdown(report)
            report_actions(report, f"Work Report (Manual) - {unit_number}")

    with tab2:
        raw = st.text_area("Paste email or any text notes (Elauwit, supervisor notes, etc.)", height=180)
        if st.button("🤖 Generate Professional Report", type="primary", key="gen_from_text", disabled=not raw.strip()):
            report = ai_generate_unit_report(ctx, raw)
            st.markdown("#### Generated Report")
            st.markdown(report)
            report_actions(report, f"Work Report (Text) - {unit_number}")

    with tab3:
        st.write("Upload a WhatsApp export (.txt). The system will summarize and turn it into a unit report.")
        wa = st.file_uploader("Upload WhatsApp export TXT", type=["txt"])
        if wa:
            raw_text = wa.read().decode("utf-8", errors="ignore")
            st.text_area("Preview", raw_text[:4000], height=160)

            if st.button("🤖 Generate Unit Report from WhatsApp", type="primary"):
                report = ai_generate_unit_report(ctx, raw_text)
                st.markdown("#### Generated Report")
                st.markdown(report)
                report_actions(report, f"Work Report (WhatsApp) - {unit_number}")

def page_email_parser(user):
    st.subheader("📧 AI Email Parser → Create Ticket + Optional Report")

    sample = """[Elauwit] T-109040 Created | [ARVA1850] [C-508] HGHI Dispatch Request

Property: ARVA1850 - Cortland on Pike
Unit: C-508
Resident: Tamara Radcliff
Issue: No internet - urgent
Technician needed ASAP
"""
    email_text = st.text_area("Paste Elauwit email", value=sample, height=180)

    if st.button("Parse Email", type="primary"):
        parsed = parse_elauwit_email(email_text)
        st.success("Parsed:")
        st.json(parsed)

        # Create ticket workflow
        conn = db()
        bdf = pd.read_sql_query("SELECT id, code, name FROM buildings ORDER BY name", conn)
        conn.close()

        # best effort property match
        building_id = None
        if parsed.get("property_code") and not bdf.empty:
            hits = bdf[bdf["code"].fillna("").str.contains(str(parsed["property_code"]), case=False)]
            if not hits.empty:
                building_id = int(hits.iloc[0]["id"])

        if bdf.empty:
            st.warning("No buildings loaded yet. Import CSV first.")
            return

        b_choice = st.selectbox("Building", bdf["name"].tolist(), index=0 if building_id is None else bdf.index[bdf["id"]==building_id][0])
        building_id = int(bdf[bdf["name"] == b_choice]["id"].iloc[0])

        conn = db()
        udf = pd.read_sql_query("SELECT id, unit_number FROM units WHERE building_id=? ORDER BY unit_number", conn, params=(building_id,))
        conn.close()

        if udf.empty:
            st.warning("No units in this building yet.")
            return

        # best effort unit match
        unit_id = None
        if parsed.get("unit_number"):
            hits = udf[udf["unit_number"].astype(str).str.contains(str(parsed["unit_number"]), case=False)]
            if not hits.empty:
                unit_id = int(hits.iloc[0]["id"])

        unit_choice = st.selectbox("Unit", udf["unit_number"].tolist(), index=0 if unit_id is None else udf.index[udf["id"]==unit_id][0])
        unit_id = int(udf[udf["unit_number"]==unit_choice]["id"].iloc[0])

        conn = db()
        techs = pd.read_sql_query("SELECT id, name FROM contractors WHERE role='technician' AND status='active' ORDER BY name", conn)
        conn.close()

        assigned = st.selectbox("Assign to", ["Unassigned"] + techs["name"].tolist())
        assigned_id = None
        if assigned != "Unassigned":
            assigned_id = int(techs[techs["name"]==assigned]["id"].iloc[0])

        ticket_id = st.text_input("Ticket ID", value=parsed.get("ticket_id") or f"T-{int(datetime.now().timestamp())}")
        priority = st.selectbox("Priority", ["normal","high","urgent"], index=["normal","high","urgent"].index(parsed.get("priority","normal")))
        desc = st.text_area("Description", value=parsed.get("issue_description") or "", height=90)

        if st.button("✅ Create Work Order", type="primary"):
            conn = db()
            c = conn.cursor()
            now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            try:
                c.execute("""
                    INSERT INTO work_orders (ticket_id, building_id, unit_id, description, priority, status, created_by, assigned_to, created_at, source, raw_text)
                    VALUES (?,?,?,?, 'open', ?, ?, ?, ?, ?, ?)
                """, (
                    ticket_id, building_id, unit_id, desc, priority,
                    user["id"], assigned_id, now, "email", email_text
                ))
                conn.commit()
                st.success(f"Work order {ticket_id} created.")
            except Exception as e:
                st.error(f"Failed: {e}")
            finally:
                conn.close()

def page_whatsapp_import(user):
    st.subheader("🟢 WhatsApp Import (Save to Units as Reports)")
    st.write("Upload a WhatsApp export .txt, choose the building + unit, and save it as a report/log.")

    wa = st.file_uploader("Upload WhatsApp export TXT", type=["txt"])
    if not wa:
        st.info("Upload a file to begin.")
        return

    raw_text = wa.read().decode("utf-8", errors="ignore")
    st.text_area("Preview", raw_text[:5000], height=180)

    conn = db()
    bdf = pd.read_sql_query("SELECT id, name FROM buildings ORDER BY name", conn)
    conn.close()

    if bdf.empty:
        st.warning("No buildings loaded yet. Import CSV first.")
        return

    b_choice = st.selectbox("Building", bdf["name"].tolist())
    building_id = int(bdf[bdf["name"] == b_choice]["id"].iloc[0])

    conn = db()
    udf = pd.read_sql_query("SELECT id, unit_number FROM units WHERE building_id=? ORDER BY unit_number", conn, params=(building_id,))
    conn.close()

    if udf.empty:
        st.warning("No units in this building.")
        return

    unit_choice = st.selectbox("Unit", udf["unit_number"].tolist())
    unit_id = int(udf[udf["unit_number"]==unit_choice]["id"].iloc[0])

    if st.button("🤖 Generate Report", type="primary"):
        report = ai_generate_unit_report(unit_context(building_id, unit_id), raw_text)
        st.markdown(report)

        if st.button("💾 Save Report to Unit", type="primary"):
            save_unit_log(building_id, unit_id, user["id"], "report", f"Work Report (WhatsApp) - {unit_choice}", report)
            st.success("Saved to Unit Reports.")
            st.rerun()

def page_time_payroll(user):
    st.subheader("⏱️ Time & Payroll")

    conn = db()
    df = pd.read_sql_query("""
        SELECT te.id, c.name, te.clock_in, te.clock_out, te.hours_worked, te.location
        FROM time_entries te
        JOIN contractors c ON c.id=te.contractor_id
        ORDER BY te.id DESC
        LIMIT 500
    """, conn)
    conn.close()

    if df.empty:
        st.info("No time entries yet.")
        return

    st.dataframe(df, use_container_width=True)

    st.markdown("### Export")
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download Time Entries CSV", data=csv, file_name="time_entries.csv", mime="text/csv")

def page_settings(user):
    st.subheader("⚙️ Settings / Readiness Checklist")

    st.markdown("### ✅ Secrets check")
    c1, c2 = st.columns(2)
    with c1:
        st.write("**DeepSeek Key:**", "✅ Set" if bool(DEEPSEEK_API_KEY) else "❌ Missing")
        st.caption("Secrets key: DEEPSEEK_API_KEY")
    with c2:
        ok_smtp = bool(SMTP_USER and SMTP_PASS)
        st.write("**Email SMTP:**", "✅ Set" if ok_smtp else "⚠️ Optional (not set)")
        st.caption("Secrets keys: SMTP_USER, SMTP_PASS (Google App Password)")

    st.markdown("### ✅ Login info (initial passwords)")
    st.info(
        "These are the default passwords used on first deployment. "
        "After Darrell logs in, change passwords in the DB later.\n\n"
        "**Owner:** darrell@fiberops-hghitechs.com / Owner123!\n"
        "**Supervisors:** brandon@fiberops-hghitechs.com / Super123! | andre@fiberops-hghitechs.com / Super123!\n"
        "**Techs:** walter@fiberops-hghitechs.com / Tech123! | rasheed@fiberops-hghitechs.com / Tech123! | dale@fiberops-hghitechs.com / Tech123!"
    )

    st.markdown("### ✅ Production steps for today")
    st.success(
        "1) Import your CSV\n"
        "2) Search a unit/serial\n"
        "3) Generate a Unit Report (manual / email / WhatsApp)\n"
        "4) Export or Email report to Darrell"
    )

# =========================================================
# MAIN ROUTER
# =========================================================
if not st.session_state.logged_in:
    login_page()
    st.stop()

user = st.session_state.user
sidebar(user)

page = st.session_state.current_page

if page == "Dashboard":
    page_dashboard(user)
elif page == "Import (CSV)":
    page_import_csv(user)
elif page == "Search":
    page_search(user)
elif page == "Buildings & Units":
    page_buildings_units(user)
elif page == "Unit Reports":
    page_unit_reports(user)
elif page == "Email Parser":
    page_email_parser(user)
elif page == "WhatsApp Import":
    page_whatsapp_import(user)
elif page == "Time & Payroll":
    page_time_payroll(user)
elif page == "Settings":
    page_settings(user)
else:
    st.info("Page not found.")
