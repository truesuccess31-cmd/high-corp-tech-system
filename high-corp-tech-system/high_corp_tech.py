import streamlit as st
import pandas as pd
import numpy as np
import sqlite3
import hashlib
import json
import time
from datetime import datetime, timedelta

# Optional imports - handled gracefully
try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
    # Don't show warning - it's okay if missing

try:
    import pytz
    HAS_PYTZ = True
except ImportError:
    HAS_PYTZ = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ========== DATABASE SETUP ==========
def init_database():
    """Initialize all database tables"""
    conn = sqlite3.connect('field_management.db')
    c = conn.cursor()
    
    # Contractors table
    c.execute('''CREATE TABLE IF NOT EXISTS contractors
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  phone TEXT,
                  hourly_rate REAL DEFAULT 35.00,
                  role TEXT DEFAULT 'technician',
                  status TEXT DEFAULT 'active',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Time entries table
    c.execute('''CREATE TABLE IF NOT EXISTS time_entries
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  contractor_id INTEGER NOT NULL,
                  clock_in TIMESTAMP NOT NULL,
                  clock_out TIMESTAMP,
                  location TEXT,
                  hours_worked REAL,
                  verified BOOLEAN DEFAULT 0)''')
    
    # Add default admin user if not exists
    c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", ("tuesuccess3@gmail.com",))
    if c.fetchone()[0] == 0:
        password_hash = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute('''INSERT INTO contractors (name, email, password_hash, role, hourly_rate)
                     VALUES (?, ?, ?, ?, ?)''',
                  ("Brandon Alves", "tuesuccess3@gmail.com", password_hash, "admin", 45.00))
    
    conn.commit()
    conn.close()

# ========== AUTHENTICATION ==========
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_login(email, password):
    conn = sqlite3.connect('field_management.db')
    c = conn.cursor()
    password_hash = hash_password(password)
    
    c.execute('''SELECT id, name, role, hourly_rate FROM contractors 
                 WHERE email=? AND password_hash=?''',
              (email, password_hash))
    user = c.fetchone()
    conn.close()
    
    if user:
        return {
            'id': user[0],
            'name': user[1],
            'role': user[2],
            'hourly_rate': user[3]
        }
    return None

# ========== SESSION STATE ==========
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'clocked_in' not in st.session_state:
    st.session_state.clocked_in = False

# ========== PAGE SETUP ==========
st.set_page_config(
    page_title="High Corp Tech Management",
    page_icon="🏗️",
    layout="wide"
)

# ========== CUSTOM CSS ==========
st.markdown("""
<style>
    .hct-header {
        background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
        color: white;
        padding: 25px;
        border-radius: 15px;
        margin-bottom: 25px;
    }
    .metric-card {
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 15px rgba(0,0,0,0.08);
        border-left: 5px solid #3b82f6;
    }
</style>
""", unsafe_allow_html=True)

# Initialize database
init_database()

# ========== LOGIN PAGE ==========
if not st.session_state.logged_in:
    st.markdown("""
    <div class="hct-header" style="text-align: center;">
        <h1>🏢 High Corp Tech</h1>
        <h3>Field Management System</h3>
        <p>Contractor Login Portal</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔐 Contractor Login")
        email = st.text_input("📧 Email Address")
        password = st.text_input("🔑 Password", type="password")
        
        if st.button("🚀 Login", type="primary", use_container_width=True):
            user = verify_login(email, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.success(f"Welcome back, {user['name']}!")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Invalid credentials")
        
        st.divider()
        st.caption("👑 Admin: tuesuccess3@gmail.com / admin123")
    
    st.stop()

# ========== MAIN APP ==========
user = st.session_state.user

st.markdown(f"""
<div class="hct-header">
    <h1>🏢 High Corp Tech Field Management</h1>
    <h3>Welcome back, {user['name']}! • {datetime.now().strftime('%A, %B %d, %Y')}</h3>
</div>
""", unsafe_allow_html=True)

# Metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown('<div class="metric-card">💰<br><h3>$2,100</h3><p>Monthly Savings</p></div>', unsafe_allow_html=True)
with col2:
    st.markdown('<div class="metric-card">⏱️<br><h3>15 hrs</h3><p>Time Saved/Week</p></div>', unsafe_allow_html=True)
with col3:
    st.markdown('<div class="metric-card">📊<br><h3>100%</h3><p>Accuracy Rate</p></div>', unsafe_allow_html=True)
with col4:
    st.markdown('<div class="metric-card">📈<br><h3>+42%</h3><p>Efficiency Gain</p></div>', unsafe_allow_html=True)

st.divider()

# Tabs
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📋 Dispatch", "🔧 Field Work", "🏢 Properties", "⏰ Time", "💰 ROI"])

with tab1:
    st.subheader("🚀 Dispatch Board")
    
    # Email parser demo
    st.write("**AI Email Parser**")
    email = st.text_area("Paste Elauwit email:", height=100, 
                        value="[Elauwit] T-109040 Created | [ARVA1850] [C-508] No internet - urgent")
    
    if st.button("🤖 Parse & Create Ticket"):
        st.success("✅ Ticket T-109040 created and assigned")
    
    # Active tickets
    st.subheader("📋 Active Tickets")
    tickets = pd.DataFrame([
        {"ID": "T-109040", "Property": "ARVA1850", "Unit": "C-508", "Status": "Urgent", "Tech": "Mike R."},
        {"ID": "T-109041", "Property": "Tysons Corner", "Unit": "B-205", "Status": "Normal", "Tech": "Sarah C."},
    ])
    st.dataframe(tickets, use_container_width=True)

with tab2:
    st.subheader("🔧 Field Technician Portal")
    
    # Time clock
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⏰ Clock In", use_container_width=True, type="primary"):
            st.session_state.clocked_in = True
            st.success("Clocked in at " + datetime.now().strftime("%I:%M %p"))
    with col2:
        if st.button("🛑 Clock Out", use_container_width=True, type="secondary"):
            st.session_state.clocked_in = False
            st.success("Clocked out at " + datetime.now().strftime("%I:%M %p"))
    
    # Photo upload
    st.subheader("📸 Equipment Photos")
    uploaded_file = st.file_uploader("Upload equipment photo", type=['jpg', 'png', 'jpeg'])
    if uploaded_file:
        if HAS_PIL:
            try:
                image = Image.open(uploaded_file)
                st.image(image, caption="Equipment Photo", use_column_width=True)
            except:
                st.warning("Could not display image")
        else:
            st.info("Photo uploaded (PIL not available for preview)")
        
        serial = st.text_input("Equipment Serial Number")
        if st.button("✅ Submit Report"):
            st.balloons()
            st.success("Report submitted with serial: " + serial)

with tab3:
    st.subheader("🏢 Properties")
    properties = pd.DataFrame([
        {"Name": "ARVA1850 - Cortland", "Units": 350, "Manager": "Elauwit", "Status": "Active"},
        {"Name": "Tysons Corner Plaza", "Units": 200, "Manager": "Elauwit", "Status": "Active"},
        {"Name": "Ballston Commons", "Units": 180, "Manager": "Verizon", "Status": "Active"},
    ])
    st.dataframe(properties, use_container_width=True)

with tab4:
    st.subheader("⏰ Time Tracking")
    
    # Sample time entries
    time_data = pd.DataFrame([
        {"Date": "2024-12-11", "Clock In": "08:00", "Clock Out": "17:00", "Hours": 9.0, "Location": "ARVA1850"},
        {"Date": "2024-12-10", "Clock In": "08:30", "Clock Out": "16:30", "Hours": 8.0, "Location": "Tysons"},
        {"Date": "2024-12-09", "Clock In": "09:00", "Clock Out": "18:00", "Hours": 9.0, "Location": "Ballston"},
    ])
    
    total_hours = time_data["Hours"].sum()
    st.metric("Total Hours This Week", f"{total_hours:.1f}")
    st.dataframe(time_data, use_container_width=True)

with tab5:
    st.subheader("💰 ROI Calculator")
    
    st.markdown("""
    ### Current Costs (Manual)
    - Ticket processing: $1,050/month
    - Payroll verification: $700/month  
    - Client reporting: $525/month
    - Equipment tracking: $350/month
    - **Total: $2,625/month**
    
    ### With This System
    - Automated processing: $245/month
    - **Monthly Savings: $2,380**
    - **Annual Savings: $28,560**
    """)
    
    st.success("**ROI: 1,090%** • **Payback: Immediate**")

# Sidebar
with st.sidebar:
    st.markdown(f"""
    <div style="background: #1e40af; color: white; padding: 20px; border-radius: 12px;">
        <h4>👤 {user['name']}</h4>
        <p><strong>Role:</strong> {user['role'].title()}</p>
        <p><strong>Rate:</strong> ${user['hourly_rate']}/hr</p>
    </div>
    """, unsafe_allow_html=True)
    
    if st.session_state.clocked_in:
        st.info("⏰ **CLOCKED IN** - Active since last clock in")
    else:
        st.warning("⏰ **CLOCKED OUT**")
    
    st.divider()
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.clocked_in = False
        st.rerun()

# Footer
st.divider()
st.markdown("""
<div style="text-align: center; color: #64748b;">
    <p>🏢 High Corp Tech Field Management v1.0 • 🔧 Built by Brandon Alves</p>
    <p>📞 (555) 123-4567 • 📧 tuesuccess3@gmail.com</p>
</div>
""", unsafe_allow_html=True)
