import os
import json
import logging
from http import HTTPStatus
from functools import wraps

# 1. 移除了 flask_cors 引用，防止冲突
from flask import Flask, request, jsonify, make_response
from dotenv import load_dotenv
import dashscope

# 引入自定义模块
try:
    from knowledge_base_handler import KnowledgeBaseHandler
    HAS_KB_HANDLER = True
except ImportError:
    HAS_KB_HANDLER = False
    print("⚠️ Warning: knowledge_base_handler module not found.")

load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('app')

app = Flask(__name__)

# --- ❌ 已删除: CORS(app) ---
# 原因：它会和下面的 after_request 冲突，导致 "Double CORS Headers" 错误。

# --- ✅ 唯一 CORS 控制中心 ---
@app.after_request
def after_request(response):
    # 获取请求来源
    origin = request.headers.get('Origin')
    
    # 动态设置 Origin
    if origin:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = '*'
        
    # 允许的 Headers 和 Methods
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-API-Key'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, PUT, DELETE'
    
    # 关键：允许携带 Cookie/认证信息
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    
    return response

# --- 配置 API Keys ---
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
if not QWEN_API_KEY:
    logger.error("⚠️ 未检测到 QWEN_API_KEY")
else:
    dashscope.api_key = QWEN_API_KEY

WP_API_KEY = os.getenv('WP_API_KEY')

# --- 产品推广配置 ---
PRODUCT_URL = "https://fengshuispaceplanner.com/shop/"
PRODUCT_NAME = "太岁化煞符 (Tai Sui Protection Amulet)"

# --- 初始化知识库 ---
kb_handler = None
if HAS_KB_HANDLER:
    logger.info("🔄 正在初始化风水知识库...")
    try:
        kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
        kb_handler.load_knowledge_base()
        logger.info("✅ 风水知识库准备就绪。")
    except Exception as e:
        logger.warning(f"⚠️ 知识库初始化失败: {e}")

# --- 工具函数 ---
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
            
    if not description:
        return "The room is currently empty."
        
    return "\n".join(description)

# --- 计算Kua数字的工具函数 ---
def calculate_kua_number(gender, birth_year):
    if not gender or not birth_year:
        return None
        
    try:
        year = int(birth_year)
        last_digit = sum(int(digit) for digit in str(year)) % 9 or 9
        
        if gender.lower() == 'male':
            kua = (11 - last_digit) % 9 or 9
        else:  # female
            kua = (last_digit + 4) % 9 or 9
            
        return kua
    except:
        return None

# --- 获取有利方位的工具函数 ---
def get_favorable_directions(kua_number):
    if not kua_number:
        return {}
        
    # 东四命：1, 3, 4, 9
    east_group = [1, 3, 4, 9]
    # 西四命：2, 5, 6, 7, 8
    west_group = [2, 5, 6, 7, 8]
    
    kua_directions = {
        1: {
            "favorable": ["Southeast", "East", "South", "North"],
            "unfavorable": ["Northwest", "West", "Southwest", "Northeast"]
        },
        2: {
            "favorable": ["Northeast", "West", "Northwest", "Southwest"],
            "unfavorable": ["Southeast", "East", "South", "North"]
        },
        3: {
            "favorable": ["South", "North", "East", "Southeast"],
            "unfavorable": ["Southwest", "Northeast", "Northwest", "West"]
        },
        4: {
            "favorable": ["North", "South", "Southeast", "East"],
            "unfavorable": ["Southwest", "Northeast", "West", "Northwest"]
        },
        5: {  # 特殊情况，算作西四命
            "favorable": ["Northeast", "West", "Northwest", "Southwest"],
            "unfavorable": ["Southeast", "East", "South", "North"]
        },
        6: {
            "favorable": ["West", "Northeast", "Southwest", "Northwest"],
            "unfavorable": ["East", "Southeast", "North", "South"]
        },
        7: {
            "favorable": ["Northwest", "Southwest", "West", "Northeast"],
            "unfavorable": ["Southeast", "East", "South", "North"]
        },
        8: {
            "favorable": ["Southwest", "Northwest", "Northeast", "West"],
            "unfavorable": ["Southeast", "East", "South", "North"]
        },
        9: {
            "favorable": ["East", "South", "North", "Southeast"],
            "unfavorable": ["West", "Southwest", "Northwest", "Northeast"]
        }
    }
    
    result = kua_directions.get(kua_number, {})
    result["kua_number"] = kua_number
    result["group"] = "East Group" if kua_number in east_group else "West Group"
    
    return result

# --- 路由定义 ---
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

# ✅ 核心接口
@app.route('/analyze-fengshui', methods=['POST', 'OPTIONS'])
def analyze_fengshui():
    # ✅ 1. 优先处理 OPTIONS 预检请求
    if request.method == 'OPTIONS':
        logger.info("Received OPTIONS request")
        # 直接返回空响应，状态码 200
        # headers 会由 after_request 自动补全，不要在这里手动加
        return make_response('', 200)

    # ✅ 2. 处理 POST 请求
    logger.info(f"📝 Received request from Origin: {request.headers.get('Origin')}")
    
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    
    if WP_API_KEY and api_key != WP_API_KEY:
        logger.warning(f"❌ Invalid API Key: {api_key}")
        return jsonify({"error": "Invalid or missing API key"}), 401
    
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        grid_data = data.get('gridData', {})
        is_paid = data.get('isPaid', False)
        
        # 获取个人信息
        personal_info = data.get('personalInfo', {})
        gender = personal_info.get('gender', '')
        birth_date = personal_info.get('birthDate', '')
        
        # 提取出生年份并计算Kua数字
        birth_year = birth_date.split('-')[0] if birth_date and '-' in birth_date else ''
        if not birth_year and birth_date and '/' in birth_date:
            birth_year = birth_date.split('/')[0]
            
        kua_number = None
        favorable_directions = {}
        
        if gender and birth_year:
            kua_number = calculate_kua_number(gender, birth_year)
            favorable_directions = get_favorable_directions(kua_number)
            logger.info(f"📊 计算出Kua数字: {kua_number}, 群组: {favorable_directions.get('group', '未知')}")

        room_description = format_grid_data_for_ai(grid_data)
        logger.info(f"📝 Analyzing room layout with Qwen...")
        
        search_query = "bedroom feng shui layout bed position"
        if "mirror" in room_description.lower():
            search_query += " mirror facing bed"
        if "door" in room_description.lower():
            search_query += " bed facing door"
        
        book_context = ""
        if kb_handler:
            book_context = kb_handler.get_relevant_context(search_query)
        
        if not book_context:
            book_context = "General Feng Shui principles apply. Avoid mirrors facing beds."

        # 添加Kua信息到提示中
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
        (Identify clashes, e.g., mirrors facing bed, bed in death line. Be strict but constructive.)
        
        ## Recommended Changes
        (Provide specific, actionable remedies for every issue identified.)
        
        *** IMPORTANT MARKETING INSTRUCTION ***
        In the "Recommended Changes" section, you MUST recommend the user to use a specific spiritual item to balance the energy.
        Product Name: "{PRODUCT_NAME}"
        Link URL: {PRODUCT_URL}
        
        Requirement: 
        1. Contextualize this product naturally.
        2. You MUST create a clickable link using Markdown format: [{PRODUCT_NAME}]({PRODUCT_URL}).
        3. Do not make it look like an ad, but like a professional prescription.
        ***************************************
        
        ## Special Considerations
        (Provide general advice on energy flow and room balance based on the layout provided.)
        """

        # ⚠️ 警告：qwen-plus 速度较慢，容易导致前端超时 (net::ERR_FAILED)
        # 如果部署后仍然报错，请尝试临时改为 'qwen-turbo' 测试
        response = dashscope.Generation.call(
            model='qwen-plus', 
            messages=[
                {'role': 'system', 'content': 'You are a helpful and traditional Feng Shui expert.'},
                {'role': 'user', 'content': system_prompt}
            ],
            result_format='message'
        )

        if response.status_code == HTTPStatus.OK:
            analysis_result = response.output.choices[0].message.content
            logger.info("✅ Analysis generated successfully.")
            return jsonify({
                "success": True,
                "analysis": analysis_result,
                "isPremium": is_paid,
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
