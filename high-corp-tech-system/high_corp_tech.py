import streamlit as st
import pandas as pd
import numpy as np
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
import pytz

# Optional imports - handled gracefully
try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

# ========== DEEPSEEK AI CONFIGURATION ==========
DEEPSEEK_API_KEY = "sk-eb858895d4fe4f3eadb59d682ad86a04"  # ✅ YOUR API KEY ADDED
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ========== COMPANY CONSTANTS ==========
COMPANY_NAME = "HGHI Tech"
OWNER_NAME = "Darrell Kelly"
SUPERVISORS = ["Brandon Alves", "Andre Ampey"]

# ========== DEEPSEEK AI FUNCTIONS ==========
def deepseek_parse_email(email_text):
    """
    Use DeepSeek AI to parse Elauwit emails
    Returns structured JSON with ticket details
    """
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
        
        # Fallback to simple parser
        return simple_parse_email(email_text)
        
    except Exception as e:
        st.warning(f"AI parsing failed: {str(e)[:50]}... Using simple parser")
        return simple_parse_email(email_text)

def deepseek_generate_report(work_data):
    """Use DeepSeek AI to generate professional reports"""
    if not DEEPSEEK_API_KEY:
        return simple_generate_report(work_data)
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""Generate a professional work completion report for HGHI Tech.

    Work Data: {json.dumps(work_data, indent=2)}

    Include:
    1. Executive Summary
    2. Key Metrics (jobs completed, average time, efficiency)
    3. Notable Issues Found
    4. Recommendations for Maintenance
    5. Equipment Status Summary
    6. Client Satisfaction Notes
    
    Format professionally with sections and bullet points."""
    
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 1000
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
    except:
        pass
    
    return simple_generate_report(work_data)

def deepseek_analyze_photo(photo_description):
    """Use DeepSeek AI to analyze equipment photos"""
    if not DEEPSEEK_API_KEY:
        return "AI analysis not available"
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""Analyze this equipment photo description for HGHI Tech field service:

    Description: {photo_description}

    Provide:
    1. Equipment type identification
    2. Potential issues spotted
    3. Maintenance recommendations
    4. Parts that might need replacement
    5. Safety concerns if any
    
    Be concise and technical."""
    
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 300
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
    except:
        pass
    
    return "Analysis not available"

def deepseek_suggest_assignments(ticket_details, contractors):
    """Use DeepSeek AI to suggest optimal contractor assignments"""
    if not DEEPSEEK_API_KEY:
        return simple_suggest_assignments(ticket_details, contractors)
    
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = f"""Suggest optimal contractor assignments for HGHI Tech.

    Ticket Details: {json.dumps(ticket_details, indent=2)}
    
    Available Contractors: {json.dumps(contractors, indent=2)}

    Consider:
    1. Contractor skills and experience
    2. Location proximity to property
    3. Current workload
    4. Hourly rates for cost efficiency
    5. Historical performance on similar jobs
    
    Return top 3 suggestions with reasoning."""
    
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 500
    }
    
    try:
        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content']
    except:
        pass
    
    return simple_suggest_assignments(ticket_details, contractors)

# ========== SIMPLE FALLBACK FUNCTIONS ==========
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

def simple_generate_report(work_data):
    """Simple report generator (fallback)"""
    report = f"""
    HGHI TECH WORK COMPLETION REPORT
    =================================
    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
    
    SUMMARY:
    - Total jobs: {len(work_data)}
    - Average time per job: Calculated from database
    - Common issues: Network connectivity, equipment replacement
    
    RECOMMENDATIONS:
    1. Schedule regular maintenance for high-usage units
    2. Maintain spare equipment inventory
    3. Continue training for new technologies
    
    Generated by {COMPANY_NAME} System
    """
    return report

def simple_suggest_assignments(ticket_details, contractors):
    """Simple assignment logic (fallback)"""
    suggestions = []
    for i, contractor in enumerate(contractors[:3]):
        suggestions.append(f"{i+1}. {contractor['name']} - ${contractor['hourly_rate']}/hr")
    return "\n".join(suggestions)

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
                  role TEXT DEFAULT 'pending',
                  status TEXT DEFAULT 'pending',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  approved_by INTEGER,
                  approved_at TIMESTAMP)''')
    
    # Time entries table
    c.execute('''CREATE TABLE IF NOT EXISTS time_entries
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  contractor_id INTEGER NOT NULL,
                  clock_in TIMESTAMP NOT NULL,
                  clock_out TIMESTAMP,
                  location TEXT,
                  hours_worked REAL,
                  verified BOOLEAN DEFAULT 0,
                  approved BOOLEAN DEFAULT 0,
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
                  assigned_date TIMESTAMP,
                  completed_date TIMESTAMP,
                  email_text TEXT,
                  email_screenshot BLOB,
                  FOREIGN KEY(unit_id) REFERENCES units(id),
                  FOREIGN KEY(contractor_id) REFERENCES contractors(id))''')
    
    # Service history table
    c.execute('''CREATE TABLE IF NOT EXISTS service_history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
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
                  FOREIGN KEY(work_order_id) REFERENCES work_orders(id))''')
    
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
                  photo BLOB,
                  FOREIGN KEY(unit_id) REFERENCES units(id))''')
    
    # Photos table
    c.execute('''CREATE TABLE IF NOT EXISTS photos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  work_order_id INTEGER,
                  contractor_id INTEGER NOT NULL,
                  photo_type TEXT,
                  photo_data BLOB,
                  serial_number TEXT,
                  ai_analysis TEXT,
                  timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(work_order_id) REFERENCES work_orders(id),
                  FOREIGN KEY(contractor_id) REFERENCES contractors(id))''')
    
    # Payroll table
    c.execute('''CREATE TABLE IF NOT EXISTS payroll
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  contractor_id INTEGER NOT NULL,
                  period_start DATE NOT NULL,
                  period_end DATE NOT NULL,
                  total_hours REAL DEFAULT 0,
                  total_pay REAL DEFAULT 0,
                  status TEXT DEFAULT 'pending',
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  approved_by INTEGER,
                  paid_date DATE,
                  FOREIGN KEY(contractor_id) REFERENCES contractors(id))''')
    
    # Notifications table
    c.execute('''CREATE TABLE IF NOT EXISTS notifications
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER NOT NULL,
                  message TEXT NOT NULL,
                  type TEXT DEFAULT 'info',
                  read BOOLEAN DEFAULT 0,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES contractors(id))''')
    
    # Unit notes history
    c.execute('''CREATE TABLE IF NOT EXISTS unit_notes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  unit_id INTEGER NOT NULL,
                  contractor_id INTEGER,
                  note_type TEXT,
                  content TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY(unit_id) REFERENCES units(id),
                  FOREIGN KEY(contractor_id) REFERENCES contractors(id))''')
    
    # Add default users if not exist
    users = [
        (OWNER_NAME, "darrell@hghitech.com", "owner123", "owner", "active", 0),
        ("Brandon Alves", "brandon@hghitech.com", "super123", "supervisor", "active", 1),
        ("Andre Ampey", "andre@hghitech.com", "super123", "supervisor", "active", 1),
        ("Mike Rodriguez", "mike@hghitech.com", "tech123", "technician", "active", 40.00),
        ("Sarah Chen", "sarah@hghitech.com", "tech123", "technician", "active", 38.50),
        ("Admin", "tuesuccess3@gmail.com", "admin123", "admin", "active", 0)
    ]
    
    for name, email, password, role, status, rate in users:
        c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email,))
        if c.fetchone()[0] == 0:
            password_hash = hashlib.sha256(password.encode()).hexdigest()
            c.execute('''INSERT INTO contractors (name, email, password_hash, role, status, hourly_rate, approved_by)
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (name, email, password_hash, role, status, rate, 1))
    
    # Add sample buildings if none exist
    c.execute("SELECT COUNT(*) FROM buildings")
    if c.fetchone()[0] == 0:
        sample_buildings = [
            ("ARVA1850 - Cortland on Pike", "1234 Pike Street, Arlington, VA", "Elauwit", 350),
            ("Tysons Corner Plaza", "5678 Tysons Blvd, McLean, VA", "Elauwit", 200),
            ("Ballston Commons", "9010 Wilson Blvd, Arlington, VA", "Verizon", 180)
        ]
        for building in sample_buildings:
            c.execute('''INSERT INTO buildings (name, address, property_manager, total_units)
                         VALUES (?, ?, ?, ?)''', building)
            
            # Add sample units for this building
            building_id = c.lastrowid
            for floor in range(1, 4):
                for unit in range(1, 11):
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
        if user[4] == 'pending':
            return None, "Account pending approval. Contact supervisor."
        elif user[4] == 'inactive':
            return None, "Account inactive. Contact supervisor."
        
        return {
            'id': user[0],
            'name': user[1],
            'role': user[2],
            'hourly_rate': user[3],
            'status': user[4]
        }, "Success"
    
    return None, "Invalid credentials"

def register_contractor(name, email, password, phone, hourly_rate):
    """Register new contractor (pending approval)"""
    conn = sqlite3.connect('field_management.db')
    c = conn.cursor()
    
    # Check if email exists
    c.execute("SELECT COUNT(*) FROM contractors WHERE email=?", (email,))
    if c.fetchone()[0] > 0:
        conn.close()
        return False, "Email already registered"
    
    # Validate hourly rate
    try:
        rate = float(hourly_rate)
        if rate < 15 or rate > 100:
            return False, "Hourly rate must be between $15 and $100"
    except:
        return False, "Invalid hourly rate"
    
    # Hash password and insert
    password_hash = hash_password(password)
    c.execute('''INSERT INTO contractors (name, email, password_hash, phone, hourly_rate, role, status)
                 VALUES (?, ?, ?, ?, ?, 'technician', 'pending')''',
              (name, email, password_hash, phone, rate))
    
    # Notify supervisors
    c.execute("SELECT id FROM contractors WHERE role IN ('supervisor', 'owner')")
    supervisors = c.fetchall()
    for sup_id in supervisors:
        c.execute('''INSERT INTO notifications (user_id, message, type)
                     VALUES (?, ?, ?)''',
                  (sup_id[0], f"New contractor registration: {name} (${rate}/hr)", "warning"))
    
    conn.commit()
    conn.close()
    return True, "Registration submitted for supervisor approval"

# ========== PAYROLL FUNCTIONS ==========
def calculate_payroll(contractor_id, start_date, end_date):
    """Calculate payroll for a contractor in a period"""
    conn = sqlite3.connect('field_management.db')
    
    # Get time entries
    query = '''
    SELECT te.clock_in, te.clock_out, te.hours_worked, te.approved,
           c.hourly_rate
    FROM time_entries te
    JOIN contractors c ON te.contractor_id = c.id
    WHERE te.contractor_id = ? 
      AND DATE(te.clock_in) BETWEEN ? AND ?
      AND te.clock_out IS NOT NULL
    ORDER BY te.clock_in
    '''
    
    time_data = pd.read_sql_query(query, conn, params=(contractor_id, start_date, end_date))
    
    if time_data.empty:
        conn.close()
        return None
    
    # Calculate totals
    total_hours = time_data['hours_worked'].sum()
    hourly_rate = time_data['hourly_rate'].iloc[0]
    
    # Calculate overtime (1.5x after 40 hours)
    regular_hours = min(total_hours, 40)
    overtime_hours = max(total_hours - 40, 0)
    
    regular_pay = regular_hours * hourly_rate
    overtime_pay = overtime_hours * hourly_rate * 1.5
    total_pay = regular_pay + overtime_pay
    
    # Check if all entries are approved
    all_approved = time_data['approved'].all()
    
    conn.close()
    
    return {
        'total_hours': total_hours,
        'regular_hours': regular_hours,
        'overtime_hours': overtime_hours,
        'hourly_rate': hourly_rate,
        'regular_pay': regular_pay,
        'overtime_pay': overtime_pay,
        'total_pay': total_pay,
        'all_approved': all_approved,
        'period': f"{start_date} to {end_date}"
    }

def generate_payroll_csv(payroll_data):
    """Generate CSV for payroll export"""
    df = pd.DataFrame([payroll_data])
    csv = df.to_csv(index=False)
    return csv

# ========== IMAGE HANDLING FUNCTIONS ==========
def save_image_to_db(image_file):
    """Convert image to base64 for database storage"""
    if image_file is None:
        return None
    
    try:
        # Read image file
        image_bytes = image_file.read()
        
        # Convert to base64
        encoded_string = base64.b64encode(image_bytes).decode('utf-8')
        return encoded_string
    except:
        return None

def display_image_from_db(image_base64):
    """Display image from base64 string"""
    if image_base64:
        try:
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_bytes))
            return image
        except:
            return None
    return None

# ========== UNIT HISTORY FUNCTIONS ==========
def get_unit_service_history(unit_id):
    """Get complete service history for a unit"""
    conn = sqlite3.connect('field_management.db')
    
    query = '''
    SELECT sh.service_date, sh.service_type, sh.equipment_serial, sh.notes,
           sh.speed_test_download, sh.speed_test_upload, sh.speed_test_ping,
           c.name as contractor_name, wo.ticket_id
    FROM service_history sh
    LEFT JOIN contractors c ON sh.contractor_id = c.id
    LEFT JOIN work_orders wo ON sh.work_order_id = wo.id
    WHERE sh.unit_id = ?
    ORDER BY sh.service_date DESC
    '''
    
    history = pd.read_sql_query(query, conn, params=(unit_id,))
    conn.close()
    
    return history

def get_unit_equipment(unit_id):
    """Get all equipment for a unit"""
    conn = sqlite3.connect('field_management.db')
    
    query = '''
    SELECT equipment_type, serial_number, manufacturer, model,
           installation_date, last_service_date, status, notes
    FROM equipment
    WHERE unit_id = ?
    ORDER BY equipment_type
    '''
    
    equipment = pd.read_sql_query(query, conn, params=(unit_id,))
    conn.close()
    
    return equipment

def get_unit_notes(unit_id):
    """Get all notes for a unit"""
    conn = sqlite3.connect('field_management.db')
    
    query = '''
    SELECT un.note_type, un.content, un.created_at,
           c.name as contractor_name
    FROM unit_notes un
    LEFT JOIN contractors c ON un.contractor_id = c.id
    WHERE un.unit_id = ?
    ORDER BY un.created_at DESC
    '''
    
    notes = pd.read_sql_query(query, conn, params=(unit_id,))
    conn.close()
    
    return notes

# ========== SESSION STATE ==========
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user' not in st.session_state:
    st.session_state.user = None
if 'clocked_in' not in st.session_state:
    st.session_state.clocked_in = False
if 'current_time_entry' not in st.session_state:
    st.session_state.current_time_entry = None
if 'show_registration' not in st.session_state:
    st.session_state.show_registration = False
if 'current_unit' not in st.session_state:
    st.session_state.current_unit = None
if 'ai_enabled' not in st.session_state:
    st.session_state.ai_enabled = bool(DEEPSEEK_API_KEY)

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
    .metric-card {{
        background: white;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 15px rgba(0,0,0,0.08);
        border-left: 5px solid #3b82f6;
        transition: transform 0.2s;
    }}
    .metric-card:hover {{
        transform: translateY(-5px);
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
    .role-pending {{ background: #f3f4f6; color: #6b7280; }}
    .ai-response {{
        background: #f0f9ff;
        border-left: 4px solid #3b82f6;
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
    }}
    .notification-badge {{
        background: #ef4444;
        color: white;
        border-radius: 50%;
        width: 20px;
        height: 20px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        margin-left: 5px;
    }}
    .unit-card {{
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 15px;
        margin: 10px 0;
    }}
    .ticket-card {{
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 15px;
        margin: 8px 0;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }}
</style>
""", unsafe_allow_html=True)

# Initialize database
init_database()

# ========== LOGIN/REGISTRATION PAGE ==========
if not st.session_state.logged_in:
    if st.session_state.show_registration:
        # ========== REGISTRATION PAGE ==========
        st.markdown(f"""
        <div class="hct-header" style="text-align: center;">
            <h1>👷 Contractor Registration</h1>
            <h3>Join {COMPANY_NAME} Team</h3>
            <p>Set your own hourly rate • Supervisor approval required</p>
        </div>
        """, unsafe_allow_html=True)
        
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("registration_form"):
                st.subheader("Personal Information")
                
                name = st.text_input("Full Name", placeholder="John Smith")
                email = st.text_input("Email Address", placeholder="john@example.com")
                phone = st.text_input("Phone Number", placeholder="(555) 123-4567")
                hourly_rate = st.number_input("Desired Hourly Rate ($)", 
                                            min_value=15.0, 
                                            max_value=100.0, 
                                            value=35.0,
                                            step=0.5,
                                            help="Your requested pay rate. Supervisors may adjust this.")
                
                st.subheader("Account Security")
                password = st.text_input("Password", type="password", 
                                       help="Minimum 8 characters")
                confirm_password = st.text_input("Confirm Password", type="password")
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    submit = st.form_submit_button("🚀 Submit Registration", use_container_width=True)
                with col_btn2:
                    cancel = st.form_submit_button("← Back to Login", use_container_width=True)
                
                if cancel:
                    st.session_state.show_registration = False
                    st.rerun()
                
                if submit:
                    if not all([name, email, phone, password]):
                        st.error("Please fill all required fields")
                    elif len(password) < 8:
                        st.error("Password must be at least 8 characters")
                    elif password != confirm_password:
                        st.error("Passwords don't match")
                    else:
                        success, message = register_contractor(name, email, password, phone, hourly_rate)
                        if success:
                            st.success(f"✅ {message}")
                            st.info("A supervisor will review your application within 24 hours. You'll receive an email when approved.")
                            time.sleep(3)
                            st.session_state.show_registration = False
                            st.rerun()
                        else:
                            st.error(f"❌ {message}")
    
    else:
        # ========== LOGIN PAGE ==========
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
            
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("🚀 Login", type="primary", use_container_width=True):
                    user, message = verify_login(email, password)
                    if user:
                        st.session_state.logged_in = True
                        st.session_state.user = user
                        
                        # Check if clocked in
                        conn = sqlite3.connect('field_management.db')
                        c = conn.cursor()
                        c.execute('''SELECT id, clock_in FROM time_entries 
                                     WHERE contractor_id=? AND clock_out IS NULL''',
                                  (user['id'],))
                        entry = c.fetchone()
                        conn.close()
                        
                        if entry:
                            st.session_state.clocked_in = True
                            st.session_state.current_time_entry = {
                                'id': entry[0],
                                'clock_in': datetime.strptime(entry[1], '%Y-%m-%d %H:%M:%S')
                            }
                        
                        st.success(f"Welcome back, {user['name']}!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(message)
            
            with col_btn2:
                if st.button("🆕 New Contractor", use_container_width=True):
                    st.session_state.show_registration = True
                    st.rerun()
            
            st.divider()
            
            # Quick login buttons for demo
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

# ========== MAIN APPLICATION ==========
user = st.session_state.user

# ========== SIDEBAR ==========
with st.sidebar:
    # User profile
    role_class = f"role-{user['role']}"
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); 
                color: white; padding: 20px; border-radius: 12px; margin-bottom: 20px;">
        <h4>👤 {user['name']}</h4>
        <p><span class="role-badge {role_class}">{user['role'].upper()}</span></p>
        <p><strong>Rate:</strong> ${user['hourly_rate']}/hr</p>
        <p><strong>Status:</strong> {user['status'].title()}</p>
    </div>
    """, unsafe_allow_html=True)
    
    # AI Status
    if st.session_state.ai_enabled:
        st.success("🤖 DeepSeek AI: Enabled")
    else:
        st.warning("🤖 DeepSeek AI: Not Configured")
        if st.button("Add API Key", key="add_api_key"):
            st.session_state.show_api_config = True
    
    # Notifications
    conn = sqlite3.connect('field_management.db')
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM notifications 
                 WHERE user_id=? AND read=0''', (user['id'],))
    unread_count = c.fetchone()[0]
    conn.close()
    
    if unread_count > 0:
        st.markdown(f"### 📢 Notifications <span class='notification-badge'>{unread_count}</span>", unsafe_allow_html=True)
        if st.button("View Notifications", use_container_width=True):
            st.session_state.show_notifications = True
    
    # Time Clock
    st.markdown("### ⏱️ Time Clock")
    
    if st.session_state.clocked_in:
        current_time = datetime.now()
        clock_in_time = st.session_state.current_time_entry['clock_in']
        hours_worked = (current_time - clock_in_time).total_seconds() / 3600
        
        st.markdown(f"<div style='font-size: 2rem; font-weight: bold; color: #10b981; text-align: center;'>{hours_worked:.2f} hours</div>", unsafe_allow_html=True)
        st.write(f"**Clocked in:** {clock_in_time.strftime('%I:%M %p')}")
        
        if st.button("🛑 Clock Out", type="secondary", use_container_width=True):
            conn = sqlite3.connect('field_management.db')
            c = conn.cursor()
            c.execute('''UPDATE time_entries SET clock_out=CURRENT_TIMESTAMP, 
                         hours_worked=? WHERE id=?''',
                      (hours_worked, st.session_state.current_time_entry['id']))
            conn.commit()
            conn.close()
            
            st.session_state.clocked_in = False
            st.session_state.current_time_entry = None
            st.success("Clocked out successfully!")
            time.sleep(1)
            st.rerun()
    else:
        if st.button("⏰ Clock In", type="primary", use_container_width=True):
            conn = sqlite3.connect('field_management.db')
            c = conn.cursor()
            c.execute('''INSERT INTO time_entries (contractor_id, clock_in, location)
                         VALUES (?, CURRENT_TIMESTAMP, ?)''',
                      (user['id'], "Field Location"))
            conn.commit()
            
            c.execute('''SELECT id, clock_in FROM time_entries 
                         WHERE contractor_id=? AND clock_out IS NULL ORDER BY id DESC LIMIT 1''',
                      (user['id'],))
            entry = c.fetchone()
            conn.close()
            
            if entry:
                st.session_state.clocked_in = True
                st.session_state.current_time_entry = {
                    'id': entry[0],
                    'clock_in': datetime.strptime(entry[1], '%Y-%m-%d %H:%M:%S')
                }
                st.success("Clocked in successfully!")
                time.sleep(1)
                st.rerun()
    
    st.divider()
    
    # Navigation based on role
    st.markdown("### 📱 Navigation")
    
    if user['role'] in ['owner', 'supervisor', 'admin']:
        nav_options = [
            "📊 Dashboard",
            "👥 Team Management", 
            "💰 Payroll",
            "📋 Ticket Manager",
            "🏢 Unit Explorer",
            "🤖 AI Assistant",
            "📈 Reports",
            "⚙️ Settings"
        ]
    else:
        nav_options = [
            "📊 My Dashboard",
            "📋 My Assignments",
            "⏰ My Time Sheet",
            "💰 My Pay",
            "📸 Photo Upload",
            "🏢 My Units"
        ]
    
    for option in nav_options:
        if st.button(option, use_container_width=True, key=f"nav_{option}"):
            st.session_state.current_page = option.split(" ")[1].lower()
            st.rerun()
    
    st.divider()
    
    # Quick stats
    conn = sqlite3.connect('field_management.db')
    c = conn.cursor()
    
    # Today's hours
    today = datetime.now().strftime('%Y-%m-%d')
    c.execute('''SELECT SUM(hours_worked) FROM time_entries 
                 WHERE contractor_id=? AND DATE(clock_in)=?''',
              (user['id'], today))
    today_hours = c.fetchone()[0] or 0
    
    # This week's earnings
    week_start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    c.execute('''SELECT SUM(hours_worked) FROM time_entries 
                 WHERE contractor_id=? AND DATE(clock_in) >= ?''',
              (user['id'], week_start))
    week_hours = c.fetchone()[0] or 0
    week_earnings = week_hours * user['hourly_rate']
    
    conn.close()
    
    col_s1, col_s2 = st.columns(2)
    col_s1.metric("Today", f"{today_hours:.1f}h")
    col_s2.metric("Week", f"${week_earnings:.0f}")
    
    st.divider()
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.clocked_in = False
        st.session_state.current_time_entry = None
        st.rerun()

# ========== MAIN CONTENT ==========
st.markdown(f"""
<div class="hct-header">
    <h1>🏢 {COMPANY_NAME} Field Management</h1>
    <h3>Welcome back, {user['name']}! • {datetime.now().strftime('%A, %B %d, %Y')}</h3>
</div>
""", unsafe_allow_html=True)

# AI Configuration Modal
if st.session_state.get('show_api_config', False):
    with st.sidebar:
        st.subheader("🤖 Configure DeepSeek AI")
        api_key = st.text_input("DeepSeek API Key", type="password", 
                               value=DEEPSEEK_API_KEY, disabled=True)
        st.info("API key already configured in the system")
        
        if st.button("Close"):
            st.session_state.show_api_config = False
            st.rerun()

# ========== PAGE ROUTING ==========
if st.session_state.get('current_page'):
    page = st.session_state.current_page
else:
    page = "dashboard" if user['role'] in ['owner', 'supervisor', 'admin'] else "dashboard"

# Show AI Status Badge
if st.session_state.ai_enabled:
    st.success("🤖 **DeepSeek AI is ACTIVE** - All AI features enabled")

# Role-based dashboard
if page == "dashboard":
    if user['role'] in ['owner', 'supervisor', 'admin']:
        # ========== ADMIN/SUPERVISOR DASHBOARD ==========
        st.subheader(f"👑 {user['role'].upper()} DASHBOARD")
        
        # Metrics for supervisors
        conn = sqlite3.connect('field_management.db')
        
        # Get team stats
        team_query = '''
        SELECT 
            COUNT(CASE WHEN status='active' THEN 1 END) as active_contractors,
            COUNT(CASE WHEN status='pending' THEN 1 END) as pending_approvals,
            COUNT(CASE WHEN role='technician' THEN 1 END) as total_technicians,
            AVG(hourly_rate) as avg_rate
        FROM contractors
        WHERE role IN ('technician', 'pending')
        '''
        team_stats = pd.read_sql_query(team_query, conn).iloc[0]
        
        # Get work stats
        work_query = '''
        SELECT 
            COUNT(CASE WHEN status='open' THEN 1 END) as open_jobs,
            COUNT(CASE WHEN status='in_progress' THEN 1 END) as in_progress_jobs,
            COUNT(CASE WHEN status='completed' THEN 1 END) as completed_today,
            SUM(CASE WHEN status='completed' AND DATE(completed_date)=DATE('now') THEN 1 ELSE 0 END) as today_completed
        FROM work_orders
        '''
        work_stats = pd.read_sql_query(work_query, conn).iloc[0]
        
        conn.close()
        
        # Display metrics
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Active Contractors", int(team_stats['active_contractors']))
        with col2:
            st.metric("Pending Approvals", int(team_stats['pending_approvals']), 
                     delta_color="off" if team_stats['pending_approvals'] == 0 else "inverse")
        with col3:
            st.metric("Open Jobs", int(work_stats['open_jobs']))
        with col4:
            st.metric("Completed Today", int(work_stats['today_completed']))
        
        st.divider()
        
        # Quick Actions
        st.subheader("🚀 Quick Actions")
        col_q1, col_q2, col_q3 = st.columns(3)
        
        with col_q1:
            if st.button("📧 Parse New Email", use_container_width=True):
                st.session_state.current_page = "ticket"
                st.rerun()
        
        with col_q2:
            if st.button("👷 Assign Jobs", use_container_width=True):
                st.session_state.current_page = "team"
                st.rerun()
        
        with col_q3:
            if st.button("💰 Run Payroll", use_container_width=True):
                st.session_state.current_page = "payroll"
                st.rerun()
        
        # AI Assistant Quick Access
        if st.session_state.ai_enabled:
            st.divider()
            st.subheader("🤖 AI Assistant")
            
            ai_query = st.text_input("Ask AI a quick question:", 
                                    placeholder="e.g., 'Show me today's urgent tickets'")
            
            if ai_query:
                with st.spinner("AI is thinking..."):
                    headers = {
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json"
                    }
                    
                    prompt = f"""As an AI assistant for HGHI Tech management, answer this query: {ai_query}
                    
                    Provide a concise, actionable answer."""
                    
                    payload = {
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 200
                    }
                    
                    try:
                        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=5)
                        if response.status_code == 200:
                            result = response.json()
                            ai_response = result['choices'][0]['message']['content']
                            st.markdown(f"<div class='ai-response'>{ai_response}</div>", unsafe_allow_html=True)
                    except:
                        st.info("AI assistant is temporarily unavailable")
        
        # Recent Activity
        st.divider()
        st.subheader("📋 Recent Activity")
        
        conn = sqlite3.connect('field_management.db')
        recent_work = pd.read_sql_query('''
            SELECT wo.ticket_id, wo.description, wo.status, wo.priority,
                   b.name as property, u.unit_number, c.name as contractor,
                   wo.created_date
            FROM work_orders wo
            JOIN units u ON wo.unit_id = u.id
            JOIN buildings b ON u.building_id = b.id
            LEFT JOIN contractors c ON wo.contractor_id = c.id
            ORDER BY wo.created_date DESC
            LIMIT 10
        ''', conn)
        conn.close()
        
        if not recent_work.empty:
            for _, row in recent_work.iterrows():
                with st.container():
                    col_t1, col_t2, col_t3 = st.columns([3, 1, 1])
                    col_t1.write(f"**{row['ticket_id']}** - {row['property']}")
                    col_t1.write(f"Unit {row['unit_number']} • {row['description'][:50]}...")
                    
                    col_t2.write(f"**{row['priority'].upper()}**")
                    col_t3.write(f"Status: {row['status'].replace('_', ' ').title()}")
                    
                    if row['contractor']:
                        col_t3.write(f"👷 {row['contractor']}")
                    
                    st.divider()
        else:
            st.info("No recent activity")
    
    else:
        # ========== CONTRACTOR DASHBOARD ==========
        st.subheader(f"👷 CONTRACTOR DASHBOARD")
        
        # Contractor-specific metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("My Hourly Rate", f"${user['hourly_rate']:.2f}")
        with col2:
            # Calculate this month's earnings
            month_start = datetime.now().replace(day=1).strftime('%Y-%m-%d')
            payroll = calculate_payroll(user['id'], month_start, datetime.now().strftime('%Y-%m-%d'))
            if payroll:
                st.metric("This Month", f"${payroll['total_pay']:.0f}")
            else:
                st.metric("This Month", "$0")
        with col3:
            # Get active assignments
            conn = sqlite3.connect('field_management.db')
            c = conn.cursor()
            c.execute('''SELECT COUNT(*) FROM work_orders 
                         WHERE contractor_id=? AND status IN ('open', 'in_progress')''',
                      (user['id'],))
            active_jobs = c.fetchone()[0]
            conn.close()
            st.metric("Active Jobs", active_jobs)
        
        st.divider()
        
        # Quick Actions for Contractors
        st.subheader("🚀 Quick Actions")
        col_q1, col_q2, col_q3 = st.columns(3)
        
        with col_q1:
            if st.button("📋 View Assignments", use_container_width=True):
                st.session_state.current_page = "assignments"
                st.rerun()
        
        with col_q2:
            if st.button("📸 Upload Photos", use_container_width=True):
                st.session_state.current_page = "photos"
                st.rerun()
        
        with col_q3:
            if st.button("⏰ Log Time", use_container_width=True):
                if not st.session_state.clocked_in:
                    st.info("Please clock in first from the sidebar")
                else:
                    st.success("Clocked in and ready to work!")
        
        # AI Help for Contractors
        if st.session_state.ai_enabled:
            st.divider()
            st.subheader("🤖 AI Technical Assistant")
            
            tech_question = st.text_input("Ask technical question:", 
                                         placeholder="e.g., 'How to fix ONT no signal?'")
            
            if tech_question:
                with st.spinner("AI is researching..."):
                    headers = {
                        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json"
                    }
                    
                    prompt = f"""As a field technician AI assistant for HGHI Tech, answer this technical question: {tech_question}
                    
                    Provide step-by-step troubleshooting guidance."""
                    
                    payload = {
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1,
                        "max_tokens": 300
                    }
                    
                    try:
                        response = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=5)
                        if response.status_code == 200:
                            result = response.json()
                            ai_response = result['choices'][0]['message']['content']
                            st.markdown(f"<div class='ai-response'>{ai_response}</div>", unsafe_allow_html=True)
                    except:
                        st.info("AI assistant is temporarily unavailable")
        
        # Recent Jobs
        st.divider()
        st.subheader("📋 Recent Jobs")
        
        conn = sqlite3.connect('field_management.db')
        my_jobs = pd.read_sql_query('''
            SELECT wo.ticket_id, wo.description, wo.status, wo.priority,
                   b.name as property, u.unit_number, wo.created_date
            FROM work_orders wo
            JOIN units u ON wo.unit_id = u.id
            JOIN buildings b ON u.building_id = b.id
            WHERE wo.contractor_id = ?
            ORDER BY wo.created_date DESC
            LIMIT 5
        ''', conn, params=(user['id'],))
        conn.close()
        
        if not my_jobs.empty:
            for _, row in my_jobs.iterrows():
                with st.container():
                    col_t1, col_t2 = st.columns([3, 1])
                    col_t1.write(f"**{row['ticket_id']}** - {row['property']}")
                    col_t1.write(f"Unit {row['unit_number']} • {row['description'][:50]}...")
                    
                    col_t2.write(f"**{row['priority'].upper()}**")
                    col_t2.write(f"Status: {row['status'].replace('_', ' ').title()}")
                    
                    st.divider()
        else:
            st.info("No recent jobs")

# ========== FOOTER ==========
st.divider()
st.markdown(f"""
<div style="text-align: center; color: #64748b; padding: 20px;">
    <h4>🏢 {COMPANY_NAME} Field Management System v4.0</h4>
    <p><strong>Owner:</strong> {OWNER_NAME} | <strong>Supervisors:</strong> {', '.join(SUPERVISORS)}</p>
    <p>🔧 Built by Brandon Alves • 📧 tuesuccess3@gmail.com • 📱 (555) 123-4567</p>
    <p style="font-size: 0.9rem;">🤖 Powered by DeepSeek AI • © 2024 {COMPANY_NAME}. All rights reserved.</p>
</div>
""", unsafe_allow_html=True)
