import os
import json
import logging
import uuid
import time
from http import HTTPStatus
from functools import wraps

# Flask imports
from flask import Flask, request, jsonify, make_response
from dotenv import load_dotenv
import dashscope

# Custom modules
try:
    from knowledge_base_handler import KnowledgeBaseHandler
    HAS_KB_HANDLER = True
except ImportError:
    HAS_KB_HANDLER = False
    print("⚠️ Warning: knowledge_base_handler module not found.")

load_dotenv()

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('app')

app = Flask(__name__)

# --- In-Memory Database (Simulated Redis) ---
# Stores full reports: { "uuid": { "content": "...", "created_at": timestamp } }
reports_db = {}

# --- CORS Control Center ---
@app.after_request
def after_request(response):
    origin = request.headers.get('Origin')
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = '*'
        
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-API-Key'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response

# --- API Keys Configuration ---
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
if not QWEN_API_KEY:
    logger.error("⚠️ QWEN_API_KEY not found in environment variables")
else:
    dashscope.api_key = QWEN_API_KEY

WP_API_KEY = os.getenv('WP_API_KEY')

# --- Product Promotion Configuration ---
PRODUCT_URL = "https://fengshuispaceplanner.com/shop/"
PRODUCT_NAME = "太岁化煞符 (Tai Sui Protection Amulet)"

# --- Initialize Knowledge Base ---
kb_handler = None
if HAS_KB_HANDLER:
    logger.info("🔄 Initializing Feng Shui Knowledge Base...")
    try:
        kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
        kb_handler.load_knowledge_base()
        logger.info("✅ Knowledge Base Ready.")
    except Exception as e:
        logger.warning(f"⚠️ Knowledge Base Init Failed: {e}")

# ==========================================
#  CORE LOGIC: Truncation / Paywall Filter
# ==========================================
def filter_report_for_free_tier(full_text):
    """
    Security Logic:
    1. Keep 'Positive Aspects' completely.
    2. Keep ONLY the 1st bullet point of 'Areas for Improvement'.
    3. DELETE everything else (Recommended Changes, Special Considerations).
    """
    lines = full_text.split('\n')
    output_lines = []
    
    found_improvement_section = False
    bullet_count = 0
    
    # Headers must match the System Prompt exactly
    IMPROVEMENT_HEADER = "## Areas for Improvement"
    
    for line in lines:
        stripped_line = line.strip()

        # 1. Check if we hit the "Areas for Improvement" section
        if IMPROVEMENT_HEADER in line:
            found_improvement_section = True
            output_lines.append(line)
            continue
            
        # 2. Before that section, keep everything (Intro, Positive Aspects)
        if not found_improvement_section:
            output_lines.append(line)
            continue
            
        # 3. Inside "Areas for Improvement"
        if found_improvement_section:
            # Check for list items (-, *, 1.)
            is_list_item = stripped_line.startswith(('-', '*', '1.'))
            
            if is_list_item:
                bullet_count += 1
                if bullet_count == 1:
                    # Keep only the first issue
                    output_lines.append(line)
                else:
                    # STOP processing immediately after the first issue
                    break
            else:
                # Keep text that isn't a bullet point (e.g., intro sentence to the section)
                if bullet_count < 2:
                    output_lines.append(line)

    # 4. Append the Paywall Message
    truncated_content = "\n".join(output_lines)
    
    paywall_message = (
        "\n\n"
        "> 🔒 **PREMIUM CONTENT HIDDEN**\n"
        ">\n"
        "> Only the first issue is visible. \n"
        "> **Unlock the full report** to see the remaining issues, \n"
        "> detailed **Recommended Changes**, and the **Cure Selection**."
    )
    
    return truncated_content + paywall_message

# --- Helper Functions ---
def format_grid_data_for_ai(grid_data):
    position_map = {
        "1": "Northwest (NW) - Mentor Luck (Qian Trigram)",
        "2": "North (N) - Career Luck (Kan Trigram)",
        "3": "Northeast (NE) - Knowledge Luck (Gen Trigram)",
        "4": "West (W) - Children/Creativity Luck (Dui Trigram)",
        "5": "Center (C) - Health/General Luck",
        "6": "East (E) - Family/Health Luck (Zhen Trigram)",
        "7": "Southwest (SW) - Love/Relationship Luck (Kun Trigram)",
        "8": "South (S) - Fame/Recognition Luck (Li Trigram)",
        "9": "Southeast (SE) - Wealth Luck (Xun Trigram)"
    }
    
    description = []
    for pos_key, cell_data in grid_data.items():
        items = []
        area_types = []
        if isinstance(cell_data, dict):
            items = cell_data.get('items', [])
            area_types = cell_data.get('areaTypes', [])
        elif isinstance(cell_data, list):
            items = cell_data
            
        if not items and not area_types:
            continue
            
        pos_name = position_map.get(str(pos_key), f"Position {pos_key}")
        desc_parts = []
        if items:
            readable_items = [("Sleeping Bed" if i == 'bed' else i.capitalize()) for i in items]
            desc_parts.append(f"contains {', '.join(readable_items)}")
        if area_types:
            readable_types = [t.capitalize() for t in area_types]
            desc_parts.append(f"is marked as {', '.join(readable_types)} area")
            
        if desc_parts:
            description.append(f"- In the {pos_name}: {', and '.join(desc_parts)}.")
            
    return "\n".join(description) if description else "The room is currently empty."

def calculate_kua_number(gender, birth_year):
    if not gender or not birth_year:
        return None
    try:
        year = int(birth_year)
        last_digit = sum(int(digit) for digit in str(year)) % 9 or 9
        if gender.lower() == 'male':
            kua = (11 - last_digit) % 9 or 9
        else:
            kua = (last_digit + 4) % 9 or 9
        return kua
    except:
        return None

def get_favorable_directions(kua_number):
    if not kua_number:
        return {}
    east_group = [1, 3, 4, 9]
    kua_directions = {
        1: {"favorable": ["Southeast", "East", "South", "North"], "unfavorable": ["Northwest", "West", "Southwest", "Northeast"]},
        2: {"favorable": ["Northeast", "West", "Northwest", "Southwest"], "unfavorable": ["Southeast", "East", "South", "North"]},
        3: {"favorable": ["South", "North", "East", "Southeast"], "unfavorable": ["Southwest", "Northeast", "Northwest", "West"]},
        4: {"favorable": ["North", "South", "Southeast", "East"], "unfavorable": ["Southwest", "Northeast", "West", "Northwest"]},
        5: {"favorable": ["Northeast", "West", "Northwest", "Southwest"], "unfavorable": ["Southeast", "East", "South", "North"]},
        6: {"favorable": ["West", "Northeast", "Southwest", "Northwest"], "unfavorable": ["East", "Southeast", "North", "South"]},
        7: {"favorable": ["Northwest", "Southwest", "West", "Northeast"], "unfavorable": ["Southeast", "East", "South", "North"]},
        8: {"favorable": ["Southwest", "Northwest", "Northeast", "West"], "unfavorable": ["Southeast", "East", "South", "North"]},
        9: {"favorable": ["East", "South", "North", "Southeast"], "unfavorable": ["West", "Southwest", "Northwest", "Northeast"]}
    }
    result = kua_directions.get(kua_number, {})
    result["kua_number"] = kua_number
    result["group"] = "East Group" if kua_number in east_group else "West Group"
    return result

# --- Routes ---

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "Feng Shui API (Qwen Edition)",
        "domain": "fengshuispaceplanner.com"
    })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "model": "qwen-plus",
        "kb_loaded": kb_handler is not None
    })

# ==========================================
#  ENDPOINT 1: Analyze (Generates & Truncates)
# ==========================================
@app.route('/analyze-fengshui', methods=['POST', 'OPTIONS'])
def analyze_fengshui():
    if request.method == 'OPTIONS':
        return make_response('', 200)

    logger.info(f"📝 Received request from Origin: {request.headers.get('Origin')}")
    
    # API Key Check
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if WP_API_KEY and api_key != WP_API_KEY:
        return jsonify({"error": "Invalid or missing API key"}), 401
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        grid_data = data.get('gridData', {})
        is_paid = data.get('isPaid', False) # Frontend can send this if user is already logged in/paid
        
        # Personal Info & Kua Calculation
        personal_info = data.get('personalInfo', {})
        gender = personal_info.get('gender', '')
        birth_date = personal_info.get('birthDate', '')
        
        birth_year = birth_date.split('-')[0] if birth_date and '-' in birth_date else ''
        if not birth_year and birth_date and '/' in birth_date:
            birth_year = birth_date.split('/')[0]
            
        kua_number = None
        favorable_directions = {}
        
        if gender and birth_year:
            kua_number = calculate_kua_number(gender, birth_year)
            favorable_directions = get_favorable_directions(kua_number)

        room_description = format_grid_data_for_ai(grid_data)
        
        # Prepare Prompt
        search_query = "bedroom feng shui layout bed position"
        if "mirror" in room_description.lower(): search_query += " mirror facing bed"
        if "door" in room_description.lower(): search_query += " bed facing door"
        
        book_context = kb_handler.get_relevant_context(search_query) if kb_handler else "General Feng Shui principles apply."

        kua_info = ""
        if kua_number and favorable_directions:
            kua_info = f"""
            === PERSONAL KUA INFORMATION ===
            Kua Number: {kua_number}
            Group: {favorable_directions.get('group', 'Unknown')}
            Favorable Directions: {', '.join(favorable_directions.get('favorable', []))}
            Unfavorable Directions: {', '.join(favorable_directions.get('unfavorable', []))}
            ================================
            """

        system_prompt = f"""
        You are a Master Feng Shui Consultant using the 'Flying Star' and 'Eight Mansions' methods.
        
        === ANCIENT KNOWLEDGE BASE ===
        {book_context}
        ==============================
        
        {kua_info}
        
        Your Task:
        Analyze the user's bedroom layout based on the description below.
        
        Layout Description:
        {room_description}
        
        Instruction: Provide a highly detailed, professional, and empathetic analysis.
        
        Output Format (Markdown):
        ## Positive Aspects
        (List 2-3 good points found in the layout)
        
        ## Areas for Improvement
        (Identify critical clashes. Be strict but constructive.)
        
        ## Recommended Changes
        (Provide specific, actionable remedies for every issue identified.)
        
        *** IMPORTANT MARKETING INSTRUCTION ***
        In the "Recommended Changes" section, you MUST recommend the user to use a specific spiritual item to balance the energy.
        Product Name: "{PRODUCT_NAME}"
        Link URL: {PRODUCT_URL}
        
        Requirement: 
        1. Contextualize this product naturally.
        2. You MUST create a clickable link using Markdown format: [{PRODUCT_NAME}]({PRODUCT_URL}).
        ***************************************
        
        ## Special Considerations
        (Provide general advice on energy flow.)
        """

        # Call AI
        logger.info(f"📝 Calling Qwen API...")
        response = dashscope.Generation.call(
            model='qwen-plus', 
            messages=[
                {'role': 'system', 'content': 'You are a helpful and traditional Feng Shui expert.'},
                {'role': 'user', 'content': system_prompt}
            ],
            result_format='message'
        )

        if response.status_code == HTTPStatus.OK:
            full_analysis = response.output.choices[0].message.content
            
            # 1. Generate Report ID
            report_id = str(uuid.uuid4())
            
            # 2. Save FULL report to memory
            reports_db[report_id] = {
                "full_content": full_analysis,
                "created_at": time.time(),
                "kua": kua_number,
                "favorableDirections": favorable_directions
            }
            
            # 3. Determine what to send back
            final_content = full_analysis
            is_locked = False
            
            if not is_paid:
                # Apply the Truncation Logic
                final_content = filter_report_for_free_tier(full_analysis)
                is_locked = True
                logger.info(f"✂️ Returning TRUNCATED report for ID: {report_id}")
            else:
                logger.info(f"🔓 Returning FULL report for ID: {report_id}")

            return jsonify({
                "success": True,
                "reportId": report_id,
                "analysis": final_content,
                "isLocked": is_locked,
                "kua": kua_number,
                "favorableDirections": favorable_directions
            })
        else:
            logger.error(f"❌ Qwen API Error: {response.code} - {response.message}")
            return jsonify({
                "success": False, 
                "error": f"AI Service Error: {response.message}"
            }), 500

    except Exception as e:
        logger.error(f"❌ Server Error: {str(e)}")
        return jsonify({"success": False, "error": "Internal Server Error"}), 500

# ==========================================
#  ENDPOINT 2: Unlock Report (Post-Payment)
# ==========================================
@app.route('/unlock-report', methods=['POST', 'OPTIONS'])
def unlock_report():
    if request.method == 'OPTIONS':
        return make_response('', 200)
        
    data = request.json
    report_id = data.get('reportId')
    
    # In a real app, you would verify a payment token here
    # payment_token = data.get('paymentToken')
    
    if not report_id or report_id not in reports_db:
        return jsonify({"success": False, "error": "Report not found"}), 404
        
    logger.info(f"🔓 Unlocking report: {report_id}")
    
    report_data = reports_db[report_id]
    
    return jsonify({
        "success": True,
        "reportId": report_id,
        "analysis": report_data['full_content'], # Return the full text
        "isLocked": False,
        "kua": report_data.get('kua'),
        "favorableDirections": report_data.get('favorableDirections')
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
