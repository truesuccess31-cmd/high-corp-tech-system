# =========================
# HGHI TECH FIELD SYSTEM
# DEPLOY-READY DEMO BUILD
# =========================

import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import requests
import json
import re
import io
from datetime import datetime, timedelta
from PIL import Image

# =========================
# PAGE CONFIG (MUST BE FIRST)
# =========================
st.set_page_config(
    page_title="HGHI Tech Field Management",
    page_icon="🏗️",
    layout="wide"
)

# =========================
# CONSTANTS
# =========================
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]

# =========================
# DEEPSEEK CONFIG (SECURE)
# =========================
DEEPSEEK_API_KEY = st.secrets.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
AI_ENABLED = bool(DEEPSEEK_API_KEY)

# =========================
# DATABASE
# =========================
DB_NAME = "field_management.db"

def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS contractors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        email TEXT UNIQUE,
        password_hash TEXT,
        role TEXT,
        hourly_rate REAL,
        status TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS time_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contractor_id INTEGER,
        clock_in TEXT,
        clock_out TEXT,
        hours REAL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS buildings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        address TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        building_id INTEGER,
        unit_number TEXT,
        resident_name TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS work_orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id TEXT,
        unit_id INTEGER,
        contractor_id INTEGER,
        description TEXT,
        priority TEXT,
        status TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS service_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit_id INTEGER,
        contractor_id INTEGER,
        notes TEXT,
        service_date TEXT
    )
    """)

    conn.commit()

    # Seed demo users
    users = [
        ("Darrell Kelly", "darrell@hghitech.com", "owner123", "owner", 0, "active"),
        ("Brandon Alves", "brandon@hghitech.com", "super123", "supervisor", 0, "active"),
        ("Mike Rodriguez", "mike@hghitech.com", "tech123", "technician", 40, "active"),
    ]

    for name, email, pw, role, rate, status in users:
        h = hashlib.sha256(pw.encode()).hexdigest()
        c.execute("SELECT 1 FROM contractors WHERE email=?", (email,))
        if not c.fetchone():
            c.execute("""
            INSERT INTO contractors (name,email,password_hash,role,hourly_rate,status)
            VALUES (?,?,?,?,?,?)
            """, (name,email,h,role,rate,status))

    # Seed property
    c.execute("SELECT COUNT(*) FROM buildings")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO buildings (name,address) VALUES (?,?)",
                  ("ARVA1850 – Cortland on Pike","Arlington, VA"))
        b_id = c.lastrowid
        for i in range(1,6):
            c.execute("""
            INSERT INTO units (building_id,unit_number,resident_name)
            VALUES (?,?,?)
            """,(b_id,f"C-{500+i}",f"Resident {i}"))

    conn.commit()
    conn.close()

init_db()

# =========================
# AUTH
# =========================
def verify_login(email,password):
    conn = get_conn()
    c = conn.cursor()
    h = hashlib.sha256(password.encode()).hexdigest()
    c.execute("""
    SELECT id,name,role,hourly_rate,status
    FROM contractors WHERE email=? AND password_hash=?
    """,(email,h))
    u = c.fetchone()
    conn.close()
    if not u:
        return None
    return {
        "id":u[0],
        "name":u[1],
        "role":u[2],
        "hourly_rate":u[3],
        "status":u[4]
    }

# =========================
# AI HELPERS
# =========================
def deepseek_chat(prompt):
    if not AI_ENABLED:
        return "AI not configured."
    payload = {
        "model":"deepseek-chat",
        "messages":[{"role":"user","content":prompt}],
        "temperature":0.2,
        "max_tokens":500
    }
    headers = {
        "Authorization":f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type":"application/json"
    }
    r = requests.post(DEEPSEEK_API_URL,json=payload,headers=headers,timeout=15)
    return r.json()["choices"][0]["message"]["content"]

def parse_email(text):
    if AI_ENABLED:
        return deepseek_chat(
            f"Extract ticket_id, unit, issue, priority from this email:\n{text}"
        )
    return "Parsed via simple mode."

# =========================
# SESSION
# =========================
if "user" not in st.session_state:
    st.session_state.user = None
if "page" not in st.session_state:
    st.session_state.page = "dashboard"

# =========================
# LOGIN SCREEN
# =========================
if not st.session_state.user:
    st.title("🏗️ HGHI Tech Field System")

    email = st.text_input("Email", key="login_email")
    password = st.text_input("Password", type="password", key="login_password")

    if st.button("Login"):
        u = verify_login(email,password)
        if u:
            st.session_state.user = u
            st.rerun()
        else:
            st.error("Invalid credentials")

    st.caption("Demo accounts:")
    if st.button("Owner Demo"):
        st.session_state["login_email"] = "darrell@hghitech.com"
        st.session_state["login_password"] = "owner123"
        st.rerun()

    st.stop()

# =========================
# SIDEBAR
# =========================
user = st.session_state.user

PAGE_MAP = {
    "Dashboard":"dashboard",
    "Ticket Manager":"tickets",
    "Unit Explorer":"units",
    "AI Assistant":"ai"
}

with st.sidebar:
    st.markdown(f"### 👤 {user['name']}")
    st.caption(user["role"].upper())

    for label,page in PAGE_MAP.items():
        if st.button(label):
            st.session_state.page = page
            st.rerun()

    if st.button("Logout"):
        st.session_state.user = None
        st.rerun()

# =========================
# DASHBOARD
# =========================
if st.session_state.page == "dashboard":
    st.header("📊 Dashboard")
    st.metric("AI Status", "Enabled" if AI_ENABLED else "Disabled")

# =========================
# TICKETS
# =========================
elif st.session_state.page == "tickets":
    st.header("📋 Ticket Manager")

    email_text = st.text_area("Paste Elauwit Email")
    if st.button("Parse Email"):
        with st.spinner("Parsing..."):
            result = parse_email(email_text)
            st.write(result)

# =========================
# UNITS
# =========================
elif st.session_state.page == "units":
    st.header("🏢 Unit Explorer")
    conn = get_conn()
    df = pd.read_sql("SELECT u.unit_number,b.name FROM units u JOIN buildings b ON u.building_id=b.id",conn)
    conn.close()
    st.dataframe(df)

# =========================
# AI
# =========================
elif st.session_state.page == "ai":
    st.header("🤖 AI Assistant")
    q = st.text_input("Ask AI")
    if st.button("Ask"):
        with st.spinner("Thinking..."):
            st.write(deepseek_chat(q))

# =========================
# FOOTER
# =========================
st.divider()
st.caption("HGHI Tech • Built by Brandon Alves • Powered by DeepSeek AI")
