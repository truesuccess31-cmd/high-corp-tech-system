# ========== IMPORTS (MINIMAL SET) ==========
import streamlit as st
import pandas as pd
import requests
import sqlite3
import hashlib
import json
import time
import re
import base64
import io
from datetime import datetime, timedelta

# ========== DEEPSEEK AI CONFIGURATION ==========
DEEPSEEK_API_KEY = "sk-eb858895d4fe4f3eadb59d682ad86a04"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ========== COMPANY CONSTANTS ==========
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]
CONTACT_PHONE = "(555) 123-4567"
CONTACT_EMAIL = "brandon@hghitech.com"

# ========== SIMPLE EMAIL PARSER ==========
def simple_parse_email(email_text):
    """Parse Elauwit emails without AI dependency"""
    results = {}
    
    # Extract ticket ID
    ticket_match = re.search(r'T[_-]?\d{6}', email_text)
    if ticket_match:
        results['ticket_id'] = ticket_match.group(0)
    
    # Extract property code
    prop_match = re.search(r'\[([A-Z0-9]+)\]', email_text)
    if prop_match:
        results['property_code'] = prop_match.group(1)
    
    # Extract unit number
    unit_match = re.search(r'\[([A-Z]-?\d+)\]', email_text)
    if unit_match:
        results['unit_number'] = unit_match.group(1)
    
    # Extract resident name
    resident_match = re.search(r'Resident[:\s]+([A-Za-z\s]+)', email_text, re.IGNORECASE)
    if resident_match:
        results['resident_name'] = resident_match.group(1).strip()
    
    # Extract issue
    issue_match = re.search(r'Issue[:\s]+(.+)', email_text, re.IGNORECASE)
    if issue_match:
        results['issue_description'] = issue_match.group(1)
    
    # Determine priority
    email_lower = email_text.lower()
    if 'urgent' in email_lower or 'asap' in email_lower:
        results['priority'] = 'urgent'
    elif 'high' in email_lower or 'priority' in email_lower:
        results['priority'] = 'high'
    else:
        results['priority'] = 'normal'
    
    return {
        'success': True,
        'data': results,
        'source': 'simple_parser'
    }

# ========== DATABASE SETUP ==========
def init_database():
    """Initialize SQLite database"""
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
                  role TEXT DEFAULT 'pending',
                  status TEXT DEFAULT 'pending',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Time entries table
    c.execute('''CREATE TABLE IF NOT EXISTS time_entries
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  contractor_id INTEGER NOT NULL,
                  clock_in TIMESTAMP NOT NULL,
                  clock_out TIMESTAMP,
                  location TEXT,
                  hours_worked REAL,
                  FOREIGN KEY(contractor_id) REFERENCES contractors(id))''')
    
    # Buildings table
    c.execute('''CREATE TABLE IF NOT EXISTS buildings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  address TEXT NOT NULL,
                  property_manager TEXT,
                  total_units INTEGER,
                  status TEXT DEFAULT 'active')''')
    
    # Units table
    c.execute('''CREATE TABLE IF NOT EXISTS units
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  building_id INTEGER NOT NULL,
                  unit_number TEXT NOT NULL,
                  resident_name TEXT,
                  unit_type TEXT,
                  status TEXT DEFAULT 'occupied',
                  notes TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(building_id) REFERENCES buildings(id))''')
    
    # Work orders table
    c.execute('''CREATE TABLE IF NOT EXISTS work_orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  ticket_id TEXT UNIQUE,
                  unit_id INTEGER NOT NULL,
                  contractor_id INTEGER,
                  description TEXT NOT NULL,
                  priority TEXT DEFAULT 'normal',
                  status TEXT DEFAULT 'open',
                  created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(unit_id) REFERENCES units(id),
                  FOREIGN KEY(contractor_id) REFERENCES contractors(id))''')
    
    # Add default users if not exist
    users = [
        (OWNER_NAME, "darrell@hghitech.com", "owner123", "owner", "active", 0),
        ("Brandon Alves", "brandon@hghitech.com", "super123", "supervisor", "active", 1),
        ("Andre Ampey", "andre@hghitech.com", "super123", "supervisor", "active", 1),
        ("Mike Rodriguez", "mike@hghitech.com", "tech123", "technician", "active", 40.00),
        ("Sarah Chen", "sarah@hghitech.com", "tech123", "technician", "active", 38.50)
    ]
    
    for name, email, password, role, status, rate in users:
        c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email,))
        if c.fetchone()[0] == 0:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            c.execute('''INSERT INTO contractors (name, email, password_hash, role, status, hourly_rate)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (name, email, password_hash, role, status, rate))
    
    # Add sample building
    c.execute("SELECT COUNT(*) FROM buildings")
    if c.fetchone()[0] == 0:
        c.execute('''INSERT INTO buildings (name, address, property_manager, total_units)
                     VALUES (?, ?, ?, ?)''',
                  ("ARVA1850 - Cortland on Pike", "1234 Pike Street, Arlington, VA", "Elauwit", 350))
        
        building_id = c.lastrowid
        for floor in range(1, 3):
            for unit in range(1, 6):
                unit_num = f"{chr(64+floor)}-{unit:03d}"
                c.execute('''INSERT INTO units (building_id, unit_number, resident_name, unit_type)
                             VALUES (?, ?, ?, ?)''',
                          (building_id, unit_num, f"Resident {floor}{unit:02d}", "apartment"))
    
    conn.commit()
    conn.close()

# ========== AUTHENTICATION ==========
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_login(email, password):
    conn = sqlite3.connect('field_management.db')
    c = conn.cursor()
    password_hash = hash_password(password)
    
    c.execute('''SELECT id, name, role, hourly_rate, status FROM contractors 
                 WHERE email=? AND password_hash=?''',
              (email, password_hash))
    user = c.fetchone()
    conn.close()
    
    if user:
        return {
            'id': user[0],
            'name': user[1],
            'role': user[2],
            'hourly_rate': user[3],
            'status': user[4]
        }, "Success"
    
    return None, "Invalid credentials"

# ========== SESSION STATE ==========
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'clocked_in' not in st.session_state:
    st.session_state.clocked_in = False

# ========== PAGE SETUP ==========
st.set_page_config(
    page_title=f"{COMPANY_NAME} Management",
    page_icon="🏗️",
    layout="wide"
)

# ========== CUSTOM CSS ==========
st.markdown(f"""
<style>
    .hct-header {{
        background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%);
        color: white;
        padding: 25px;
        border-radius: 15px;
        margin-bottom: 25px;
    }}
    .owner-header {{
        background: linear-gradient(135deg, #92400e 0%, #d97706 100%);
        color: white;
        padding: 25px;
        border-radius: 15px;
        margin-bottom: 25px;
    }}
    .metric-card {{
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 15px rgba(0,0,0,0.08);
        border-left: 5px solid #3b82f6;
        transition: transform 0.2s;
    }}
    .role-badge {{
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
        margin: 2px;
    }}
    .role-owner {{ background: #fef3c7; color: #92400e; }}
    .role-supervisor {{ background: #dbeafe; color: #1e40af; }}
    .role-technician {{ background: #d1fae5; color: #065f46; }}
</style>
""", unsafe_allow_html=True)

# Initialize database
init_database()

# ========== LOGIN PAGE ==========
if not st.session_state.logged_in:
    st.markdown(f"""
    <div class="hct-header" style="text-align: center;">
        <h1>🏢 {COMPANY_NAME}</h1>
        <h3>Field Management System</h3>
        <p>Login to access your dashboard</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.subheader("🔐 Login")
        
        email = st.text_input("📧 Email Address", key="login_email")
        password = st.text_input("🔑 Password", type="password", key="login_password")
        
        if st.button("🚀 Login", type="primary", use_container_width=True):
            user, message = verify_login(email, password)
            if user:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.success(f"Welcome back, {user['name']}!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)
        
        st.divider()
        
        # Quick login buttons
        st.caption("**Demo Accounts:**")
        cols = st.columns(4)
        accounts = [
            ("👑 Owner", "darrell@hghitech.com", "owner123"),
            ("👨‍💼 Supervisor", "brandon@hghitech.com", "super123"),
            ("👷 Technician", "mike@hghitech.com", "tech123"),
            ("👷 Technician", "sarah@hghitech.com", "tech123")
        ]
        
        for idx, (role, email_addr, pwd) in enumerate(accounts):
            with cols[idx]:
                if st.button(role, use_container_width=True):
                    st.session_state.login_email = email_addr
                    st.session_state.login_password = pwd
                    st.rerun()
    
    st.stop()

# ========== MAIN APP ==========
user = st.session_state.user

# Sidebar
with st.sidebar:
    role_class = f"role-{user['role']}"
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); 
                color: white; padding: 20px; border-radius: 12px; margin-bottom: 20px;">
        <h4>👤 {user['name']}</h4>
        <p><span class="role-badge {role_class}">{user['role'].upper()}</span></p>
        <p><strong>Rate:</strong> ${user['hourly_rate']}/hr</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Navigation
    st.markdown("### 📱 Navigation")
    
    if user['role'] in ['owner', 'supervisor']:
        nav_options = ["📊 Dashboard", "📋 Email Parser", "💰 ROI Calculator", "👥 Team"]
    else:
        nav_options = ["📊 My Dashboard", "📋 My Jobs", "💰 My Pay"]
    
    for option in nav_options:
        if st.button(option, use_container_width=True):
            st.session_state.current_page = option.split(" ")[1].lower()
            st.rerun()
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.rerun()

# Main Content
st.markdown(f"""
<div class="hct-header">
    <h1>🏢 {COMPANY_NAME} Field Management</h1>
    <h3>Welcome back, {user['name']}! • {datetime.now().strftime('%A, %B %d, %Y')}</h3>
</div>
""", unsafe_allow_html=True)

# ROI Calculator for Darrell
if user['role'] == 'owner':
    st.markdown("""
    <div class="owner-header" style="text-align: center;">
        <h1>💰 ROI CALCULATOR</h1>
        <h3>See Your Monthly Savings in Real-Time</h3>
        <p>Adjust the numbers to match YOUR business</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("### ⏰ Your Time")
        old_hours = st.slider(
            "Hours you spend on admin/week", 
            5, 40, 15, 1,
            help="How many hours do YOU waste on paperwork each week?"
        )
        
        hourly_rate = st.number_input(
            "Your time value/hour ($)", 
            value=150.0,
            min_value=50.0, 
            max_value=300.0, 
            step=25.0,
            help="What's an hour of YOUR time worth?"
        )
    
    with col2:
        st.markdown("### 👷 Your Team")
        contractors = st.number_input(
            "Number of contractors", 
            value=5, 
            min_value=1, 
            max_value=20, 
            step=1
        )
        
        efficiency_gain = st.slider(
            "Contractor efficiency gain (%)",
            0, 30, 10, 5,
            help="How much more efficient will contractors be?"
        )
    
    with col3:
        st.markdown("### 📈 Your Savings")
        # Calculate savings
        weekly_time_savings = (old_hours - 2) * hourly_rate
        monthly_time_savings = weekly_time_savings * 4.33
        
        contractor_savings = contractors * 10 * 35 * (efficiency_gain/100) * 4.33
        total_monthly_savings = monthly_time_savings + contractor_savings
        
        st.metric("**Weekly Time Savings**", f"${weekly_time_savings:,.0f}")
        st.metric("**Monthly Time Savings**", f"${monthly_time_savings:,.0f}")
        st.metric("**Total Monthly Savings**", f"${total_monthly_savings:,.0f}")
    
    # Show the math
    with st.expander("📊 Show Detailed Calculation"):
        st.write(f"""
        **Your Inputs:**
        - Hours wasted weekly: {old_hours} hours
        - Your hourly rate: ${hourly_rate}/hour
        - Contractors: {contractors}
        - Efficiency gain: {efficiency_gain}%
        
        **Calculation:**
        1. Time saved with system: {old_hours} - 2 = **{old_hours - 2} hours/week**
        2. Weekly value: {old_hours - 2} × ${hourly_rate} = **${weekly_time_savings:,.0f}/week**
        3. Monthly value: ${weekly_time_savings:,.0f} × 4.33 = **${monthly_time_savings:,.0f}/month**
        4. Contractor efficiency: {contractors} × 10 hours × $35/hour × {efficiency_gain}% × 4.33 = **${contractor_savings:,.0f}/month**
        
        **Total Monthly Savings: ${total_monthly_savings:,.0f}**
        
        **Even if we're 50% wrong:** ${total_monthly_savings/2:,.0f}/month still pays for itself immediately.
        """)
    
    # Email Parser Demo
    st.divider()
    st.markdown("### 📧 Try Email Parser")
    
    sample_email = """[Elauwit] T-109040 Created | [ARVA1850] [C-508] HGHI Dispatch Request

Property: ARVA1850 - Cortland on Pike
Unit: C-508
Resident: Tamara Radcliff
Issue: No internet - urgent
Technician needed ASAP"""
    
    email_input = st.text_area("Paste Elauwit Email:", value=sample_email, height=150)
    
    if st.button("🤖 Parse Email"):
        result = simple_parse_email(email_input)
        if result['success']:
            data = result['data']
            st.success("✅ Email Parsed Successfully!")
            
            col_r1, col_r2 = st.columns(2)
            with col_r1:
                st.write("**Extracted Details:**")
                for key, value in data.items():
                    if value:
                        st.write(f"- **{key.replace('_', ' ').title()}:** {value}")
            
            with col_r2:
                st.write("**Time Saved:**")
                st.write("- **Manual:** 5-10 minutes per email")
                st.write("- **System:** 2 seconds per email")
                st.write("- **Savings:** 8 minutes × 20 emails/day = **2.7 hours/week saved**")
                st.write(f"- **Value:** 2.7 hours × ${hourly_rate}/hour = **${hourly_rate*2.7:,.0f}/week**")

# Dashboard for everyone
st.divider()
st.markdown("### 📊 Quick Stats")

col1, col2, col3 = st.columns(3)
col1.metric("Hourly Rate", f"${user['hourly_rate']}/hr")
col2.metric("Status", user['status'].title())
col3.metric("Role", user['role'].title())

# Footer
st.divider()
st.markdown(f"""
<div style="text-align: center; color: #64748b; padding: 20px;">
    <h4>🏢 {COMPANY_NAME} Field Management System</h4>
    <p><strong>Owner:</strong> {OWNER_NAME} | <strong>Contact:</strong> {CONTACT_EMAIL}</p>
    <p style="font-size: 0.9rem;">🚀 Deployed Successfully | © 2024 {COMPANY_NAME}</p>
</div>
""", unsafe_allow_html=True)
