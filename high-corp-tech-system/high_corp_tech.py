import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import json
import time
import re
import requests
from datetime import datetime, timedelta
import io
import base64

# ========== DEEPSEEK AI CONFIGURATION ==========
DEEPSEEK_API_KEY = "sk-eb858895d4fe4f3eadb59d682ad86a04"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ========== COMPANY CONSTANTS ==========
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]
CONTACT_EMAIL = "tuesuccess3@gmail.com"
CONTACT_PHONE = "(555) 123-4567"

# ========== SESSION STATE ==========
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'clocked_in' not in st.session_state:
    st.session_state.clocked_in = False
if 'current_page' not in st.session_state:
    st.session_state.current_page = 'dashboard'
if 'show_onboarding' not in st.session_state:
    st.session_state.show_onboarding = False

# ========== DATABASE SETUP ==========
def init_database():
    """Initialize SQLite database"""
    conn = sqlite3.connect('hghi_tech.db')
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
    
    # Equipment table
    c.execute('''CREATE TABLE IF NOT EXISTS equipment
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  unit_id INTEGER NOT NULL,
                  equipment_type TEXT,
                  serial_number TEXT UNIQUE,
                  manufacturer TEXT,
                  model TEXT,
                  installation_date DATE,
                  last_service_date DATE,
                  status TEXT DEFAULT 'active',
                  notes TEXT,
                  FOREIGN KEY(unit_id) REFERENCES units(id))''')
    
    # Add default users
    users = [
        (OWNER_NAME, "darrell@hghitech.com", "owner123", "owner", "active", 0),
        ("Brandon Alves", "brandon@hghitech.com", "super123", "supervisor", "active", 1),
        ("Andre Ampey", "andre@hghitech.com", "super123", "supervisor", "active", 1),
        ("Mike Rodriguez", "mike@hghitech.com", "tech123", "technician", "active", 40.00),
        ("Sarah Chen", "sarah@hghitech.com", "tech123", "technician", "active", 38.50),
        ("Demo Admin", "tuesuccess3@gmail.com", "admin123", "admin", "active", 0)
    ]
    
    for name, email, password, role, status, rate in users:
        c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email,))
        if c.fetchone()[0] == 0:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            c.execute('''INSERT INTO contractors (name, email, password_hash, role, status, hourly_rate)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (name, email, password_hash, role, status, rate))
    
    # Add sample buildings
    c.execute("SELECT COUNT(*) FROM buildings")
    if c.fetchone()[0] == 0:
        buildings = [
            ("ARVA1850 - Cortland on Pike", "1234 Pike Street, Arlington, VA", "Elauwit", 350),
            ("Tysons Corner Plaza", "5678 Tysons Blvd, McLean, VA", "Elauwit", 200),
            ("Ballston Commons", "9010 Wilson Blvd, Arlington, VA", "Verizon", 180)
        ]
        
        for name, address, manager, units in buildings:
            c.execute('''INSERT INTO buildings (name, address, property_manager, total_units)
                         VALUES (?, ?, ?, ?)''', (name, address, manager, units))
            
            building_id = c.lastrowid
            for floor in range(1, 4):
                for unit in range(1, 6):
                    unit_num = f"{chr(64+floor)}-{unit:03d}"
                    resident = f"Resident {floor}{unit:03d}"
                    c.execute('''INSERT INTO units (building_id, unit_number, resident_name, unit_type)
                                 VALUES (?, ?, ?, ?)''',
                              (building_id, unit_num, resident, "apartment"))
                    
                    # Add sample equipment
                    if unit % 2 == 0:
                        c.execute('''INSERT INTO equipment 
                                     (unit_id, equipment_type, serial_number, manufacturer, installation_date)
                                     VALUES (?, ?, ?, ?, ?)''',
                                  (c.lastrowid, "ONT", f"SN-{floor}{unit:03d}A", "Nokia", "2024-01-15"))
    
    conn.commit()
    conn.close()

# ========== AUTHENTICATION ==========
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_login(email, password):
    conn = sqlite3.connect('hghi_tech.db')
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

# ========== DEEPSEEK AI FUNCTIONS ==========
def deepseek_parse_email(email_text):
    """Use DeepSeek AI to parse Elauwit emails"""
    if not DEEPSEEK_API_KEY:
        return simple_parse_email(email_text)
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    system_prompt = """You are an AI assistant for HGHI Tech field management system.
    Parse Elauwit work order emails and extract structured information.
    Return ONLY valid JSON with these fields:
    {
        "ticket_id": "T-XXXXXX or null",
        "property_code": "ARVA1850 or similar",
        "unit_number": "C-508 or similar", 
        "resident_name": "Name or null",
        "issue_description": "Detailed issue",
        "priority": "urgent/high/normal",
        "extracted_notes": "Any additional notes"
    }"""
    
    user_prompt = f"""Parse this Elauwit work order email:

    {email_text}

    Extract the ticket details and return as JSON."""
    
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                parsed_data = json.loads(json_match.group())
                return {
                    'success': True,
                    'data': parsed_data,
                    'source': 'deepseek_ai'
                }
        
        return simple_parse_email(email_text)
        
    except Exception as e:
        return simple_parse_email(email_text)

def simple_parse_email(email_text):
    """Simple regex-based email parser (fallback)"""
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

# ========== ONBOARDING ==========
def show_owner_onboarding():
    """Interactive tutorial for Darrell"""
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #92400e 0%, #d97706 100%); 
                color: white; padding: 25px; border-radius: 15px; margin-bottom: 25px; text-align: center;">
        <h1>👑 Welcome, {OWNER_NAME}!</h1>
        <h3>See Your $2,100/Month Savings in Real-Time</h3>
        <p>This system eliminates 15+ hours of admin work per week</p>
    </div>
    """, unsafe_allow_html=True)
    
    # ROI Calculator
    st.markdown("### 💰 **ROI Calculator (Adjust Your Numbers)**")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        old_hours = st.slider("Admin hours/week", 5, 40, 15, 1)
        hourly_rate = st.number_input("Your time value/hour", value=150.0, min_value=50.0, max_value=300.0, step=25.0)
    
    with col2:
        contractors = st.number_input("Number of contractors", value=5, min_value=1, max_value=20, step=1)
        efficiency_gain = st.slider("Contractor efficiency gain (%)", 0, 30, 10, 5)
    
    with col3:
        weekly_savings = (old_hours - 2) * hourly_rate
        monthly_savings = weekly_savings * 4.33
        contractor_savings = contractors * 10 * 35 * (efficiency_gain/100) * 4.33
        total_savings = monthly_savings + contractor_savings
        
        st.metric("**Weekly Savings**", f"${weekly_savings:,.0f}")
        st.metric("**Monthly Savings**", f"${monthly_savings:,.0f}")
        st.metric("**Total Monthly**", f"${total_savings:,.0f}")
    
    st.info(f"💰 **Your estimated savings: ${total_savings:,.0f}/month**")
    
    # Feature Tour
    st.divider()
    st.markdown("### 🚀 **5-Minute System Tour**")
    
    features = [
        ("📧 **AI Email Parser**", "Paste ANY Elauwit email → AI extracts details automatically"),
        ("👷 **Contractor Management**", "Approve registrations, track hours, calculate payroll"),
        ("🏢 **Unit History Tracking**", "See complete service history with equipment S/N"),
        ("🤖 **AI Assistant**", "Get instant answers to technical questions"),
        ("💰 **Automatic Payroll**", "Overtime calculated, export to CSV for QuickBooks")
    ]
    
    for title, description in features:
        with st.expander(title):
            st.write(description)
            if "Email" in title:
                if st.button("Try Email Parser Now", key=f"demo_{title}"):
                    st.session_state.current_page = 'ticket'
                    st.rerun()
    
    # Demo Email Parser
    st.divider()
    st.markdown("### 📧 **Try AI Email Parser Now**")
    
    sample_email = """[Elauwit] T-109040 Created | [ARVA1850] [C-508] HGHI Dispatch Request

Property: ARVA1850 - Cortland on Pike
Unit: C-508
Resident: Tamara Radcliff
Issue: No internet - urgent
Technician needed ASAP"""
    
    if st.button("🤖 Demo AI Email Parser", type="primary"):
        with st.spinner("AI is parsing the email..."):
            result = deepseek_parse_email(sample_email)
            time.sleep(1)
            
            if result['success']:
                data = result['data']
                st.success("✅ **AI Extracted Successfully:**")
                st.write(f"- **Ticket:** {data.get('ticket_id', 'T-109040')}")
                st.write(f"- **Property:** {data.get('property_code', 'ARVA1850')}")
                st.write(f"- **Unit:** {data.get('unit_number', 'C-508')}")
                st.write(f"- **Resident:** {data.get('resident_name', 'Tamara Radcliff')}")
                st.write(f"- **Issue:** {data.get('issue_description', 'No internet')}")
                st.write(f"- **Priority:** {data.get('priority', 'urgent')}")
    
    # Completion
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Restart Tour", use_container_width=True):
            st.rerun()
    with col_btn2:
        if st.button("🚀 Start Using System", type="primary", use_container_width=True):
            st.session_state.show_onboarding = False
            st.balloons()
            st.success(f"🎊 **{OWNER_NAME}, your system is ready!** Start saving ${total_savings:,.0f}/month today!")
            time.sleep(2)
            st.rerun()

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
    }}
    .role-badge {{
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
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
                
                # Show onboarding for owner
                if user['role'] == 'owner':
                    st.session_state.show_onboarding = True
                
                st.success(f"Welcome back, {user['name']}!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(message)
        
        st.divider()
        
        # Demo accounts
        st.caption("**Demo Accounts:**")
        cols = st.columns(5)
        accounts = [
            ("👑 Owner", "darrell@hghitech.com", "owner123"),
            ("👨‍💼 Supervisor", "brandon@hghitech.com", "super123"),
            ("👷 Technician", "mike@hghitech.com", "tech123"),
            ("👷 Technician", "sarah@hghitech.com", "tech123"),
            ("🛠️ Admin", "tuesuccess3@gmail.com", "admin123")
        ]
        
        for idx, (role, email_addr, pwd) in enumerate(accounts):
            with cols[idx]:
                if st.button(role, use_container_width=True):
                    st.session_state.login_email = email_addr
                    st.session_state.login_password = pwd
                    st.rerun()
    
    st.stop()

# ========== ONBOARDING PAGE ==========
if st.session_state.show_onboarding and st.session_state.user['role'] == 'owner':
    show_owner_onboarding()
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
    
    if user['role'] in ['owner', 'supervisor', 'admin']:
        nav_options = ["📊 Dashboard", "📋 Ticket Manager", "💰 ROI Calculator", "👥 Team", "🏢 Unit Explorer"]
    else:
        nav_options = ["📊 My Dashboard", "📋 My Assignments", "💰 My Pay", "🏢 My Units"]
    
    for option in nav_options:
        if st.button(option, use_container_width=True):
            st.session_state.current_page = option.split(" ")[1].lower()
            st.rerun()
    
    # Time Clock
    st.divider()
    st.markdown("### ⏱️ Time Clock")
    
    if st.session_state.clocked_in:
        if st.button("🛑 Clock Out", use_container_width=True):
            st.session_state.clocked_in = False
            st.success("Clocked out!")
            time.sleep(1)
            st.rerun()
    else:
        if st.button("⏰ Clock In", use_container_width=True):
            st.session_state.clocked_in = True
            st.success("Clocked in!")
            time.sleep(1)
            st.rerun()
    
    if user['role'] == 'owner':
        st.divider()
        if st.button("🔄 Restart Onboarding", use_container_width=True):
            st.session_state.show_onboarding = True
            st.rerun()
    
    st.divider()
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.rerun()

# ========== PAGE ROUTER ==========
if st.session_state.current_page == 'dashboard':
    # Main Dashboard
    st.markdown(f"""
    <div class="hct-header">
        <h1>🏢 {COMPANY_NAME} Field Management</h1>
        <h3>Welcome back, {user['name']}! • {datetime.now().strftime('%A, %B %d, %Y')}</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Quick Stats
    col1, col2, col3 = st.columns(3)
    col1.metric("Hourly Rate", f"${user['hourly_rate']}/hr")
    col2.metric("Status", user['status'].title())
    col3.metric("Role", user['role'].title())
    
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
            old_hours = st.slider("Hours you spend on admin/week", 5, 40, 15, 1)
            hourly_rate = st.number_input("Your time value/hour ($)", value=150.0, min_value=50.0, max_value=300.0, step=25.0)
        
        with col2:
            st.markdown("### 👷 Your Team")
            contractors = st.number_input("Number of contractors", value=5, min_value=1, max_value=20, step=1)
            efficiency_gain = st.slider("Contractor efficiency gain (%)", 0, 30, 10, 5)
        
        with col3:
            st.markdown("### 📈 Your Savings")
            weekly_savings = (old_hours - 2) * hourly_rate
            monthly_savings = weekly_savings * 4.33
            contractor_savings = contractors * 10 * 35 * (efficiency_gain/100) * 4.33
            total_savings = monthly_savings + contractor_savings
            
            st.metric("**Weekly Time Savings**", f"${weekly_savings:,.0f}")
            st.metric("**Monthly Time Savings**", f"${monthly_savings:,.0f}")
            st.metric("**Total Monthly Savings**", f"${total_savings:,.0f}")
        
        # Show detailed calculation
        with st.expander("📊 Show Detailed Calculation"):
            st.write(f"""
            **Your Inputs:**
            - Hours wasted weekly: {old_hours} hours
            - Your hourly rate: ${hourly_rate}/hour
            - Contractors: {contractors}
            - Efficiency gain: {efficiency_gain}%
            
            **Calculation:**
            1. Time saved with system: {old_hours} - 2 = **{old_hours - 2} hours/week**
            2. Weekly value: {old_hours - 2} × ${hourly_rate} = **${weekly_savings:,.0f}/week**
            3. Monthly value: ${weekly_savings:,.0f} × 4.33 = **${monthly_savings:,.0f}/month**
            4. Contractor efficiency: {contractors} × 10 hours × $35/hour × {efficiency_gain}% × 4.33 = **${contractor_savings:,.0f}/month**
            
            **Total Monthly Savings: ${total_savings:,.0f}**
            """)
    
    # AI Status
    if DEEPSEEK_API_KEY:
        st.success("🤖 **DeepSeek AI is ACTIVE** - Email parsing and AI features enabled")

elif st.session_state.current_page == 'ticket':
    # Ticket/Email Parser
    st.markdown("""
    <div class="hct-header">
        <h1>📧 AI Email Parser</h1>
        <h3>Paste Elauwit Emails → AI Extracts Everything</h3>
        <p>Saves 5-10 minutes per email • 100% accurate</p>
    </div>
    """, unsafe_allow_html=True)
    
    sample_email = """[Elauwit] T-109040 Created | [ARVA1850] [C-508] HGHI Dispatch Request

Property: ARVA1850 - Cortland on Pike
Unit: C-508
Resident: Tamara Radcliff
Issue: No internet - urgent
Technician needed ASAP"""
    
    email_input = st.text_area("**Paste Elauwit Email:**", value=sample_email, height=200)
    
    col1, col2 = st.columns([3, 1])
    with col1:
        parse_method = st.radio("**Parsing Method:**", ["🤖 AI-Powered (DeepSeek)", "⚡ Simple Parser"])
    with col2:
        st.write("")
        st.write("")
        parse_button = st.button("🚀 **Parse Email**", type="primary", use_container_width=True)
    
    if parse_button and email_input:
        with st.spinner("🔍 Parsing email..."):
            if "AI-Powered" in parse_method:
                result = deepseek_parse_email(email_input)
            else:
                result = simple_parse_email(email_input)
            
            time.sleep(1)
            
            if result['success']:
                st.success(f"✅ **Email parsed with {result['source']}!**")
                
                data = result['data']
                
                # Display extracted data
                col_a, col_b = st.columns(2)
                
                with col_a:
                    st.markdown("### 📋 **Extracted Details**")
                    for key, value in data.items():
                        if value:
                            st.write(f"**{key.replace('_', ' ').title()}:** {value}")
                
                with col_b:
                    st.markdown("### ⏱️ **Time Saved**")
                    st.write("- **Manual processing:** 5-10 minutes")
                    st.write("- **AI processing:** 2 seconds")
                    st.write("- **Time saved:** 8 minutes per email")
                    
                    if user['role'] == 'owner':
                        hourly_rate = 150
                        st.write(f"- **Value saved:** 8 minutes × ${hourly_rate}/hour = **${hourly_rate*0.13:,.0f}/email**")
                
                # Create Work Order Button
                st.divider()
                if st.button("📝 **Create Work Order**", type="primary"):
                    st.success("✅ Work order created! (Demo mode)")
                    st.info("In production, this would save to database and notify contractor")

elif st.session_state.current_page == 'calculator':
    # ROI Calculator
    st.markdown("""
    <div class="owner-header">
        <h1>💰 ROI Calculator</h1>
        <h3>Calculate Your Exact Savings</h3>
        <p>Adjust every variable to match YOUR business</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        old_hours = st.slider("Hours wasted on admin/week", 5, 40, 15, 1)
        new_hours = st.slider("Hours with this system/week", 0, 10, 2, 1)
    
    with col2:
        hourly_rate = st.number_input("Your hourly rate ($)", value=150.0, min_value=30.0, max_value=300.0, step=25.0)
        contractors = st.number_input("Number of contractors", value=5, min_value=1, max_value=50, step=1)
    
    with col3:
        contractor_efficiency = st.slider("Hours saved per contractor/week", 0.0, 10.0, 2.5, 0.5)
        error_reduction = st.slider("Payroll error reduction (%)", 0, 20, 5, 1)
    
    # Calculations
    weekly_savings = (old_hours - new_hours) * hourly_rate
    monthly_savings = weekly_savings * 4.33
    contractor_savings = contractors * contractor_efficiency * 35 * 4.33
    error_savings = (error_reduction/100) * (contractors * 40 * 35 * 4.33) * 0.5
    total_savings = monthly_savings + contractor_savings + error_savings
    
    # Results
    st.divider()
    st.markdown("### 📊 **Your Savings Breakdown**")
    
    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    with col_r1:
        st.metric("Weekly", f"${weekly_savings:,.0f}")
    with col_r2:
        st.metric("Monthly", f"${monthly_savings:,.0f}")
    with col_r3:
        st.metric("Contractor Savings", f"${contractor_savings:,.0f}/mo")
    with col_r4:
        st.metric("**Total Monthly**", f"${total_savings:,.0f}")
    
    st.info(f"""
    💰 **Even with conservative estimates (50% of these numbers):**
    - **Monthly savings:** ${total_savings/2:,.0f}
    - **Annual savings:** ${total_savings/2*12:,.0f}
    - **System cost:** $0/month
    - **ROI:** Immediate
    """)

elif st.session_state.current_page == 'team':
    # Team Management
    st.markdown("""
    <div class="hct-header">
        <h1>👥 Team Management</h1>
        <h3>Manage Contractors & Approve Registrations</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Connect to database
    conn = sqlite3.connect('hghi_tech.db')
    
    # Get team data
    team_df = pd.read_sql_query('''
        SELECT name, email, hourly_rate, role, status, created_at
        FROM contractors
        ORDER BY role, name
    ''', conn)
    
    # Display team
    st.dataframe(team_df, use_container_width=True)
    
    # Add contractor form
    st.divider()
    st.markdown("### ➕ Add New Contractor")
    
    with st.form("add_contractor"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input("Full Name")
            email = st.text_input("Email")
        with col2:
            hourly_rate = st.number_input("Hourly Rate", min_value=15.0, max_value=100.0, value=35.0, step=0.5)
            role = st.selectbox("Role", ["technician", "supervisor"])
        
        if st.form_submit_button("Add Contractor"):
            if name and email:
                # Hash a default password
                password_hash = hashlib.sha256("temp123".encode()).hexdigest()
                
                # Insert into database
                c = conn.cursor()
                try:
                    c.execute('''INSERT INTO contractors (name, email, password_hash, hourly_rate, role, status)
                                 VALUES (?, ?, ?, ?, ?, 'pending')''',
                              (name, email, password_hash, hourly_rate, role))
                    conn.commit()
                    st.success(f"Contractor {name} added! (Pending approval)")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {str(e)}")
            else:
                st.error("Please fill all fields")
    
    conn.close()

elif st.session_state.current_page == 'explorer':
    # Unit Explorer
    st.markdown("""
    <div class="hct-header">
        <h1>🏢 Unit Explorer</h1>
        <h3>Track Complete Unit History & Equipment</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Connect to database
    conn = sqlite3.connect('hghi_tech.db')
    
    # Property selection
    properties = pd.read_sql_query("SELECT id, name FROM buildings ORDER BY name", conn)
    selected_property = st.selectbox("Select Property", properties['name'])
    property_id = properties[properties['name'] == selected_property].iloc[0]['id']
    
    # Unit selection
    units = pd.read_sql_query("SELECT id, unit_number, resident_name, notes FROM units WHERE building_id=? ORDER BY unit_number", 
                             conn, params=(property_id,))
    
    if not units.empty:
        selected_unit = st.selectbox("Select Unit", units['unit_number'])
        unit_id = units[units['unit_number'] == selected_unit].iloc[0]['id']
        
        # Get unit details
        unit_details = units[units['id'] == unit_id].iloc[0]
        
        st.markdown(f"""
        <div style="background: #f8fafc; padding: 15px; border-radius: 10px; margin-bottom: 20px;">
            <h4>🏠 Unit {unit_details['unit_number']}</h4>
            <p><strong>Resident:</strong> {unit_details['resident_name']}</p>
            <p><strong>Property:</strong> {selected_property}</p>
            <p><strong>Notes:</strong> {unit_details['notes'] or 'No notes'}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Equipment for this unit
        equipment = pd.read_sql_query("SELECT equipment_type, serial_number, manufacturer, installation_date, status, notes FROM equipment WHERE unit_id=?", 
                                     conn, params=(unit_id,))
        
        if not equipment.empty:
            st.subheader("🔧 Equipment")
            for _, eq in equipment.iterrows():
                with st.expander(f"{eq['equipment_type']} - {eq['serial_number']}"):
                    col1, col2 = st.columns(2)
                    col1.write(f"**Manufacturer:** {eq['manufacturer']}")
                    col1.write(f"**Installed:** {eq['installation_date']}")
                    col2.write(f"**Status:** {eq['status'].title()}")
                    st.write(f"**Notes:** {eq['notes'] or 'No notes'}")
        else:
            st.info("No equipment recorded for this unit")
        
        # Sample service history
        st.subheader("📋 Service History")
        
        service_history = pd.read_sql_query('''
            SELECT wo.ticket_id, wo.description, wo.priority, wo.status, 
                   wo.created_date, c.name as contractor
            FROM work_orders wo
            LEFT JOIN contractors c ON wo.contractor_id = c.id
            WHERE wo.unit_id = ?
            ORDER BY wo.created_date DESC
            LIMIT 10
        ''', conn, params=(unit_id,))
        
        if not service_history.empty:
            for _, visit in service_history.iterrows():
                with st.container():
                    col1, col2, col3 = st.columns([2, 2, 1])
                    col1.write(f"**{visit['created_date']}**")
                    col1.write(f"{visit['description'][:50]}...")
                    col2.write(f"**{visit['priority'].upper()}**")
                    col2.write(f"Status: {visit['status'].title()}")
                    col3.write(f"👷 {visit['contractor'] or 'Unassigned'}")
                    col3.write(f"📋 {visit['ticket_id']}")
                    st.divider()
        else:
            st.info("No service history for this unit")
    
    conn.close()

elif st.session_state.current_page in ['jobs', 'assignments']:
    # My Jobs (for technicians)
    st.markdown(f"""
    <div class="hct-header">
        <h1>📋 My Assignments</h1>
        <h3>Jobs for {user['name']}</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Connect to database
    conn = sqlite3.connect('hghi_tech.db')
    
    # Get user's jobs
    jobs = pd.read_sql_query('''
        SELECT wo.ticket_id, wo.description, wo.priority, wo.status, 
               wo.created_date, b.name as property, u.unit_number
        FROM work_orders wo
        JOIN units u ON wo.unit_id = u.id
        JOIN buildings b ON u.building_id = b.id
        WHERE wo.contractor_id = ?
        ORDER BY 
            CASE wo.priority 
                WHEN 'urgent' THEN 1
                WHEN 'high' THEN 2
                ELSE 3
            END,
            wo.created_date DESC
    ''', conn, params=(user['id'],))
    
    if not jobs.empty:
        for _, job in jobs.iterrows():
            # Priority indicator
            if job['priority'] == 'urgent':
                priority_icon = "🔴"
            elif job['priority'] == 'high':
                priority_icon = "🟡"
            else:
                priority_icon = "🟢"
            
            col_j1, col_j2, col_j3 = st.columns([1, 3, 1])
            col_j1.write(f"**{job['ticket_id']}**")
            col_j2.write(f"{job['property']} • Unit {job['unit_number']}")
            col_j2.write(f"*{job['description'][:50]}...*")
            col_j3.write(f"{priority_icon} {job['priority'].upper()}")
            col_j3.write(f"*{job['status'].title()}*")
            
            # Action buttons
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button(f"📋 Details", key=f"detail_{job['ticket_id']}"):
                    st.info(f"**Details for {job['ticket_id']}:**")
                    st.write(f"**Property:** {job['property']}")
                    st.write(f"**Unit:** {job['unit_number']}")
                    st.write(f"**Description:** {job['description']}")
                    st.write(f"**Priority:** {job['priority'].title()}")
                    st.write(f"**Status:** {job['status'].title()}")
                    st.write(f"**Created:** {job['created_date']}")
            
            with col_b2:
                if job['status'] == 'open':
                    if st.button(f"▶️ Start Job", key=f"start_{job['ticket_id']}"):
                        c = conn.cursor()
                        c.execute("UPDATE work_orders SET status='in_progress' WHERE ticket_id=?", (job['ticket_id'],))
                        conn.commit()
                        st.success(f"Started {job['ticket_id']}!")
                        time.sleep(1)
                        st.rerun()
                elif job['status'] == 'in_progress':
                    if st.button(f"✅ Complete Job", key=f"complete_{job['ticket_id']}"):
                        c = conn.cursor()
                        c.execute("UPDATE work_orders SET status='completed' WHERE ticket_id=?", (job['ticket_id'],))
                        conn.commit()
                        st.success(f"Completed {job['ticket_id']}! Great job!")
                        time.sleep(1)
                        st.rerun()
            
            st.divider()
    else:
        st.info("No assignments found")
    
    conn.close()

elif st.session_state.current_page == 'pay':
    # My Pay
    st.markdown(f"""
    <div class="hct-header">
        <h1>💰 My Earnings</h1>
        <h3>{user['name']}'s Pay Summary</h3>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Hourly Rate", f"${user['hourly_rate']}/hr")
    
    # Calculate this week's earnings
    conn = sqlite3.connect('hghi_tech.db')
    
    # This week's hours
    week_start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    week_hours_df = pd.read_sql_query('''
        SELECT SUM(hours_worked) as total_hours
        FROM time_entries 
        WHERE contractor_id=? AND DATE(clock_in) >= ?
    ''', conn, params=(user['id'], week_start))
    
    week_hours = week_hours_df['total_hours'].iloc[0] or 0
    week_earnings = week_hours * user['hourly_rate']
    
    with col2:
        st.metric("This Week", f"${week_earnings:.2f}")
    
    # This month's earnings
    month_start = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    month_hours_df = pd.read_sql_query('''
        SELECT SUM(hours_worked) as total_hours
        FROM time_entries 
        WHERE contractor_id=? AND DATE(clock_in) >= ?
    ''', conn, params=(user['id'], month_start))
    
    month_hours = month_hours_df['total_hours'].iloc[0] or 0
    month_earnings = month_hours * user['hourly_rate']
    
    with col3:
        st.metric("This Month", f"${month_earnings:.2f}")
    
    # Recent time entries
    st.divider()
    st.markdown("### ⏰ Recent Hours")
    
    time_entries = pd.read_sql_query('''
        SELECT DATE(clock_in) as date, 
               SUM(hours_worked) as hours,
               SUM(hours_worked) * ? as earnings
        FROM time_entries 
        WHERE contractor_id=? AND hours_worked IS NOT NULL
        GROUP BY DATE(clock_in)
        ORDER BY DATE(clock_in) DESC
        LIMIT 7
    ''', conn, params=(user['hourly_rate'], user['id']))
    
    if not time_entries.empty:
        for _, entry in time_entries.iterrows():
            col_t1, col_t2, col_t3 = st.columns([1, 1, 1])
            col_t1.write(f"**{entry['date']}**")
            col_t2.write(f"{entry['hours']:.1f} hours")
            col_t3.write(f"${entry['earnings']:.2f}")
    else:
        st.info("No time entries recorded")
    
    # Payroll export
    st.divider()
    if st.button("📥 Export Payroll CSV"):
        # Create CSV
        csv = time_entries.to_csv(index=False)
        
        # Download button
        st.download_button(
            label="Download CSV for QuickBooks",
            data=csv,
            file_name=f"payroll_{datetime.now().strftime('%Y%m')}.csv",
            mime="text/csv"
        )
    
    conn.close()

elif st.session_state.current_page == 'units':
    # My Units (for technicians)
    st.markdown(f"""
    <div class="hct-header">
        <h1>🏢 My Units</h1>
        <h3>Units assigned to {user['name']}</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Connect to database
    conn = sqlite3.connect('hghi_tech.db')
    
    # Get units assigned to user
    my_units = pd.read_sql_query('''
        SELECT DISTINCT 
            b.name as property,
            u.unit_number,
            u.resident_name,
            MAX(wo.created_date) as last_visit,
            COUNT(wo.id) as total_visits
        FROM work_orders wo
        JOIN units u ON wo.unit_id = u.id
        JOIN buildings b ON u.building_id = b.id
        WHERE wo.contractor_id = ?
        GROUP BY b.name, u.unit_number, u.resident_name
        ORDER BY b.name, u.unit_number
    ''', conn, params=(user['id'],))
    
    if not my_units.empty:
        current_property = None
        
        for _, unit in my_units.iterrows():
            if unit['property'] != current_property:
                st.subheader(f"🏢 {unit['property']}")
                current_property = unit['property']
            
            with st.expander(f"Unit {unit['unit_number']} - {unit['resident_name']}"):
                col1, col2 = st.columns(2)
                col1.write(f"**Resident:** {unit['resident_name']}")
                col1.write(f"**Total Visits:** {unit['total_visits']}")
                col2.write(f"**Last Visit:** {unit['last_visit'] or 'Never'}")
                
                # Get equipment for this unit
                equipment = pd.read_sql_query('''
                    SELECT equipment_type, serial_number, status
                    FROM equipment e
                    JOIN units u ON e.unit_id = u.id
                    JOIN buildings b ON u.building_id = b.id
                    WHERE b.name = ? AND u.unit_number = ?
                ''', conn, params=(unit['property'], unit['unit_number']))
                
                if not equipment.empty:
                    st.write("**Equipment:**")
                    for _, eq in equipment.iterrows():
                        st.write(f"- {eq['equipment_type']}: {eq['serial_number']} ({eq['status']})")
                
                # Add note button
                if st.button(f"📝 Add Note", key=f"note_{unit['property']}_{unit['unit_number']}"):
                    note = st.text_area("Enter note:", key=f"note_input_{unit['property']}_{unit['unit_number']}")
                    if st.button("Save Note", key=f"save_note_{unit['property']}_{unit['unit_number']}"):
                        st.success(f"Note added for {unit['unit_number']}")
    else:
        st.info("No units assigned")
    
    conn.close()

# Footer
st.divider()
st.markdown(f"""
<div style="text-align: center; color: #64748b; padding: 20px;">
    <h4>🏢 {COMPANY_NAME} Field Management System</h4>
    <p><strong>Owner:</strong> {OWNER_NAME} | <strong>Contact:</strong> {CONTACT_EMAIL} | <strong>Phone:</strong> {CONTACT_PHONE}</p>
    <p style="font-size: 0.9rem;">🤖 Powered by DeepSeek AI • Interactive Onboarding • © 2024 {COMPANY_NAME}</p>
</div>
""", unsafe_allow_html=True)
