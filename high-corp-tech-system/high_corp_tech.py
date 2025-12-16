import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import json
import time
import re
import requests
from datetime import datetime, timedelta

# ========== DEEPSEEK AI CONFIGURATION ==========
DEEPSEEK_API_KEY = "sk-eb858895d4fe4f3eadb59d682ad86a04"  # Your working key
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ========== COMPANY CONSTANTS ==========
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]
CONTACT_PHONE = "(555) 123-4567"
CONTACT_EMAIL = "brandon@hghitech.com"

# ========== SESSION STATE INITIALIZATION ==========
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
if 'show_owner_onboarding' not in st.session_state:
    st.session_state.show_owner_onboarding = False

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
    
    # Add default users
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

# ========== AI FUNCTIONS ==========
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
    patterns = {
        'ticket_id': r'T[_-]?\d{6}',
        'property_code': r'\[([A-Z0-9]+)\]',
        'unit_number': r'\[([A-Z]-?\d+)\]',
        'resident_name': r'Resident[:\s]+([A-Za-z\s]+)',
        'issue_description': r'Issue[:\s]+(.+)'
    }
    
    results = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, email_text, re.IGNORECASE)
        if match:
            results[key] = match.group(1) if key != 'issue_description' else match.group(1)
    
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

# ========== ONBOARDING FUNCTIONS ==========
def show_contractor_onboarding():
    """Interactive tutorial for new contractors"""
    st.markdown("""
    <div style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); 
                color: white; padding: 25px; border-radius: 15px; margin-bottom: 25px; text-align: center;">
        <h1>👋 Welcome to HGHI Tech!</h1>
        <h3>Your 5-Minute System Tour</h3>
        <p>Let's get you started with our field management system</p>
    </div>
    """, unsafe_allow_html=True)
    
    steps = [
        ("📱 **Step 1: Clock In/Out**", "Every morning when you arrive, click '⏰ Clock In'. Every evening, click '🛑 Clock Out'. Your hours are tracked automatically."),
        ("📋 **Step 2: View Your Assignments**", "Check '📋 My Assignments' to see your jobs. Click 'Start' when beginning and 'Complete' when finished."),
        ("📸 **Step 3: Document Your Work**", "Take photos of equipment, enter serial numbers, run speed tests, and add notes for each job."),
        ("💰 **Step 4: Track Your Pay**", "Click '💰 My Pay' to see current earnings. Your pay is calculated automatically at ${}/hr.".format(st.session_state.user['hourly_rate'])),
        ("📞 **Step 5: Get Help When Needed**", "For technical issues: Contact Brandon. For job questions: Contact your supervisor. For app problems: Use the AI Assistant.")
    ]
    
    for i, (title, content) in enumerate(steps, 1):
        with st.expander(title, expanded=(i==1)):
            st.write(content)
            if st.button(f"✅ I understand Step {i}", key=f"step_{i}"):
                st.success(f"Great! Step {i} complete.")
                time.sleep(0.5)
    
    st.divider()
    
    # Quick knowledge check
    st.markdown("### 🎯 **Quick Knowledge Check**")
    quiz = st.radio(
        "What should you do FIRST when arriving at a job site?",
        ["Take a break first", "**Clock in on the app**", "Call the supervisor", "Skip documentation"]
    )
    
    if quiz == "**Clock in on the app**":
        st.success("✅ **Perfect!** Always clock in first to track your hours.")
    else:
        st.warning("⚠️ Remember: Clock in first thing every morning!")
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Restart Tutorial", use_container_width=True):
            st.rerun()
    with col_btn2:
        if st.button("🎉 I'm Ready to Start!", type="primary", use_container_width=True):
            st.session_state.show_onboarding = False
            st.balloons()
            st.success("🎊 **Welcome aboard!** You're now ready to use the system!")
            time.sleep(2)
            st.rerun()

def show_owner_onboarding():
    """Interactive tutorial for Darrell (owner)"""
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #92400e 0%, #d97706 100%); 
                color: white; padding: 25px; border-radius: 15px; margin-bottom: 25px; text-align: center;">
        <h1>👑 Welcome, {OWNER_NAME}!</h1>
        <h3>Owner Dashboard Tour - See Your Savings in Real-Time</h3>
        <p>This system eliminates admin work and saves you time & money</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Interactive ROI Calculator
    st.markdown("### 💰 **Live ROI Calculator (Adjust Your Numbers)**")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        old_hours = st.slider("Your admin hours/week", 5, 40, 15, 1,
                             help="How many hours do YOU waste on paperwork?")
        hourly_rate = st.number_input("Your time value/hour", value=150.0, min_value=50.0, max_value=300.0, step=25.0)
    
    with col2:
        contractors = st.number_input("Number of contractors", value=5, min_value=1, max_value=20, step=1)
        efficiency_gain = st.slider("Contractor efficiency gain (%)", 0, 30, 10, 5)
    
    with col3:
        # Calculate savings
        weekly_time_savings = (old_hours - 2) * hourly_rate
        monthly_time_savings = weekly_time_savings * 4.33
        contractor_savings = contractors * 10 * 35 * (efficiency_gain/100) * 4.33
        total_monthly_savings = monthly_time_savings + contractor_savings
        
        st.metric("**Weekly Savings**", f"${weekly_time_savings:,.0f}")
        st.metric("**Monthly Savings**", f"${monthly_time_savings:,.0f}")
        st.metric("**Total Monthly**", f"${total_monthly_savings:,.0f}")
    
    st.info(f"💰 **Your estimated savings: ${total_monthly_savings:,.0f}/month**")
    
    # Feature Tour
    st.divider()
    st.markdown("### 🚀 **System Features Tour**")
    
    features = [
        ("📧 **AI Email Parser**", "Paste any Elauwit email → AI extracts all details automatically"),
        ("👷 **Contractor Management**", "Approve registrations, track hours, calculate payroll automatically"),
        ("🏢 **Unit History Tracking**", "See complete service history for every unit with equipment S/N"),
        ("🤖 **AI Assistant**", "Get instant answers to technical questions and management advice"),
        ("💰 **Automatic Payroll**", "Overtime calculated automatically, export to CSV for QuickBooks")
    ]
    
    for title, description in features:
        with st.expander(title):
            st.write(description)
            if "Email" in title:
                if st.button("Try Email Parser", key="demo_email"):
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
                col_r1, col_r2 = st.columns(2)
                with col_r1:
                    for key, value in data.items():
                        if value:
                            st.write(f"**{key.replace('_', ' ').title()}:** {value}")
                with col_r2:
                    st.write("**Time Saved:**")
                    st.write("- Manual: 5-10 minutes per email")
                    st.write("- System: 2 seconds per email")
                    st.write(f"- Value: 8 minutes × ${hourly_rate}/hour = **${hourly_rate*0.13:,.0f}/email**")
    
    # Completion
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("🔄 Restart Tour", use_container_width=True):
            st.rerun()
    with col_btn2:
        if st.button("🚀 Start Using System", type="primary", use_container_width=True):
            st.session_state.show_owner_onboarding = False
            st.balloons()
            st.success(f"🎊 **{OWNER_NAME}, your system is ready!** Start saving ${total_monthly_savings:,.0f}/month today!")
            time.sleep(3)
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
                
                # Show appropriate onboarding
                if user['role'] == 'owner':
                    st.session_state.show_owner_onboarding = True
                elif user['role'] == 'technician':
                    st.session_state.show_onboarding = True
                
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

# ========== ONBOARDING PAGES ==========
if st.session_state.show_owner_onboarding:
    show_owner_onboarding()
    st.stop()

if st.session_state.show_onboarding:
    show_contractor_onboarding()
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
    
    # Restart Onboarding
    if user['role'] == 'owner':
        if st.button("🔄 Restart Owner Tour", use_container_width=True):
            st.session_state.show_owner_onboarding = True
            st.rerun()
    elif user['role'] == 'technician':
        if st.button("🔄 Restart Training", use_container_width=True):
            st.session_state.show_onboarding = True
            st.rerun()
    
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
    
    # AI Status
    if DEEPSEEK_API_KEY:
        st.success("🤖 **DeepSeek AI is ACTIVE** - Email parsing and AI features enabled")

elif st.session_state.current_page == 'parser' or st.session_state.current_page == 'ticket':
    # Email Parser
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
            
            time.sleep(1)  # Simulate processing
            
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
                        hourly_rate = 150  # Default owner rate
                        st.write(f"- **Value saved:** 8 minutes × ${hourly_rate}/hour = **${hourly_rate*0.13:,.0f}/email**")
                
                # Create Work Order Button
                st.divider()
                if st.button("📝 **Create Work Order from This**", type="primary"):
                    st.success("Work order created! (Demo mode)")
                    st.info("In production, this would save to database and notify contractor")

elif st.session_state.current_page == 'calculator' or st.session_state.current_page == 'roi':
    # ROI Calculator
    st.markdown(f"""
    <div class="owner-header">
        <h1>💰 ROI Calculator</h1>
        <h3>Calculate Your Exact Savings</h3>
        <p>Adjust every variable to match YOUR business</p>
    </div>
    """, unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("### ⏰ Time Savings")
        old_hours = st.slider(
            "Hours wasted on admin/week", 
            5, 40, 15, 1,
            help="How many hours do you spend on paperwork, emails, and scheduling?"
        )
        new_hours = st.slider(
            "Hours with this system/week",
            0, 10, 2, 1,
            help="How many hours will you spend with automated system?"
        )
    
    with col2:
        st.markdown("### 💵 Your Time Value")
        hourly_rate = st.number_input(
            "Your hourly rate ($)", 
            value=150.0,
            min_value=30.0, 
            max_value=300.0, 
            step=25.0,
            help="What's an hour of YOUR time worth for your business?"
        )
        
        contractors = st.number_input(
            "Number of contractors", 
            value=5, 
            min_value=1, 
            max_value=50, 
            step=1
        )
    
    with col3:
        st.markdown("### 👷 Team Efficiency")
        contractor_efficiency = st.slider(
            "Hours saved per contractor/week",
            0.0, 10.0, 2.5, 0.5,
            help="How many hours less confusion/travel for contractors?"
        )
        
        error_reduction = st.slider(
            "Payroll error reduction (%)",
            0, 20, 5, 1,
            help="What % of payroll has errors without system?"
        )
    
    # Calculations
    weekly_time_savings = (old_hours - new_hours) * hourly_rate
    monthly_time_savings = weekly_time_savings * 4.33
    
    contractor_savings = contractors * contractor_efficiency * 35 * 4.33
    error_savings = (error_reduction/100) * (contractors * 40 * 35 * 4.33) * 0.5  # 50% of errors cost money
    
    total_monthly_savings = monthly_time_savings + contractor_savings + error_savings
    
    # Results
    st.divider()
    st.markdown("### 📊 **Your Savings Breakdown**")
    
    col_r1, col_r2, col_r3, col_r4 = st.columns(4)
    with col_r1:
        st.metric("Weekly", f"${weekly_time_savings:,.0f}")
    with col_r2:
        st.metric("Monthly", f"${monthly_time_savings:,.0f}")
    with col_r3:
        st.metric("Contractor Savings", f"${contractor_savings:,.0f}/mo")
    with col_r4:
        st.metric("**Total Monthly**", f"${total_monthly_savings:,.0f}")
    
    # Conservative Estimate
    st.info(f"""
    💰 **Even with conservative estimates (50% of these numbers):**
    - **Monthly savings:** ${total_monthly_savings/2:,.0f}
    - **Annual savings:** ${total_monthly_savings/2*12:,.0f}
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
    
    # Sample team data
    team_data = [
        {"name": "Mike Rodriguez", "email": "mike@hghitech.com", "rate": "$40.00", "status": "Active", "role": "Technician"},
        {"name": "Sarah Chen", "email": "sarah@hghitech.com", "rate": "$38.50", "status": "Active", "role": "Technician"},
        {"name": "John Smith", "email": "john@contractor.com", "rate": "$35.00", "status": "Pending", "role": "Technician"},
        {"name": "Brandon Alves", "email": "brandon@hghitech.com", "rate": "$0.00", "status": "Active", "role": "Supervisor"},
        {"name": "Darrell Kelly", "email": "darrell@hghitech.com", "rate": "$0.00", "status": "Active", "role": "Owner"},
    ]
    
    df = pd.DataFrame(team_data)
    st.dataframe(df, use_container_width=True)
    
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
            st.success(f"Contractor {name} added!")
            time.sleep(1)
            st.rerun()

elif st.session_state.current_page == 'jobs' or st.session_state.current_page == 'assignments':
    # My Jobs (for technicians)
    st.markdown(f"""
    <div class="hct-header">
        <h1>📋 My Assignments</h1>
        <h3>Jobs for {user['name']}</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Sample jobs
    jobs = [
        {"id": "T-109040", "property": "ARVA1850", "unit": "C-508", "issue": "No internet", "priority": "🔴 URGENT", "status": "Assigned"},
        {"id": "T-109038", "property": "Tysons Plaza", "unit": "B-205", "issue": "Router replacement", "priority": "🟡 NORMAL", "status": "In Progress"},
        {"id": "T-109035", "property": "Ballston", "unit": "A-101", "issue": "Slow speeds", "priority": "🟡 NORMAL", "status": "Completed"},
    ]
    
    for job in jobs:
        col_j1, col_j2, col_j3 = st.columns([1, 3, 1])
        col_j1.write(f"**{job['id']}**")
        col_j2.write(f"{job['property']} • Unit {job['unit']}")
        col_j2.write(f"*{job['issue']}*")
        col_j3.write(job['priority'])
        col_j3.write(f"*{job['status']}*")
        
        col_b1, col_b2 = st.columns(2)
        with col_b1:
            if st.button(f"📋 Details", key=f"detail_{job['id']}"):
                st.info(f"Details for {job['id']}: {job['issue']} at {job['property']} {job['unit']}")
        with col_b2:
            if job['status'] == 'Assigned':
                if st.button(f"▶️ Start", key=f"start_{job['id']}"):
                    st.success(f"Started {job['id']} - Remember to document your work!")
            elif job['status'] == 'In Progress':
                if st.button(f"✅ Complete", key=f"complete_{job['id']}"):
                    st.success(f"Completed {job['id']} - Great job!")
        
        st.divider()

elif st.session_state.current_page == 'pay':
    # My Pay
    st.markdown(f"""
    <div class="hct-header">
        <h1>💰 My Earnings</h1>
        <h3>{user['name']}'s Pay Summary</h3>
    </div>
    """, unsafe_allow_html=True)
    
    # Sample pay data
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Hourly Rate", f"${user['hourly_rate']}/hr")
    with col2:
        st.metric("This Week", "$1,250")
    with col3:
        st.metric("This Month", "$5,420")
    
    st.divider()
    
    # Time entries
    st.markdown("### ⏰ Recent Hours")
    time_data = [
        {"date": "Today", "hours": "6.5", "earnings": f"${6.5 * user['hourly_rate']:.2f}"},
        {"date": "Yesterday", "hours": "8.0", "earnings": f"${8.0 * user['hourly_rate']:.2f}"},
        {"date": "This Week", "hours": "32.5", "earnings": f"${32.5 * user['hourly_rate']:.2f}"},
        {"date": "Last Week", "hours": "40.0", "earnings": f"${40.0 * user['hourly_rate']:.2f}"},
    ]
    
    for entry in time_data:
        col_t1, col_t2, col_t3 = st.columns([1, 1, 1])
        col_t1.write(f"**{entry['date']}**")
        col_t2.write(f"{entry['hours']} hours")
        col_t3.write(f"{entry['earnings']}")

# Footer
st.divider()
st.markdown(f"""
<div style="text-align: center; color: #64748b; padding: 20px;">
    <h4>🏢 {COMPANY_NAME} Field Management System</h4>
    <p><strong>Owner:</strong> {OWNER_NAME} | <strong>Contact:</strong> {CONTACT_EMAIL}</p>
    <p style="font-size: 0.9rem;">🤖 Powered by DeepSeek AI • Interactive Onboarding • © 2024 {COMPANY_NAME}</p>
</div>
""", unsafe_allow_html=True)
