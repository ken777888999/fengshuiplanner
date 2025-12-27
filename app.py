import requests
import os
import json
import logging
import uuid
import time
from http import HTTPStatus
from flask import Flask, request, jsonify
from flask_cors import CORS 
from dotenv import load_dotenv
import dashscope

# --- 自定义模块引入 ---
# 尝试引入知识库模块，如果没有也不报错，只是禁用相关功能
try:
    from knowledge_base_handler import KnowledgeBaseHandler
    HAS_KB_HANDLER = True
except ImportError:
    HAS_KB_HANDLER = False
    print("⚠️ Warning: knowledge_base_handler module not found. Running without KB.")

# 加载环境变量
load_dotenv()

# --- 日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('app')

app = Flask(__name__)

# --- 关键修改：CORS 配置 (允许跨域) ---
# 这行代码解决了前端 fetch 报错的问题
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# --- 内存数据库 (模拟 Redis) ---
# 用于存储完整报告，格式: { "uuid": { "content": "...", "created_at": timestamp, ... } }
reports_db = {}

# --- WooCommerce 配置 ---
WOO_CK = os.getenv("WOO_CK") or "ck_1164e779c5af0df880fbf3fb3ddd38a808dc0e56"
WOO_CS = os.getenv("WOO_CS") or "cs_cce2d28d979f992aa9a9a8183f79dd3c8ba76612"
WOO_URL = "https://fengshuispaceplanner.com" 

# --- API Keys 配置 ---
# 优先读取 QWEN_API_KEY，如果没有则尝试读取 DASHSCOPE_API_KEY
QWEN_API_KEY = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
if not QWEN_API_KEY:
    logger.error("⚠️ 未检测到 API Key (QWEN_API_KEY 或 DASHSCOPE_API_KEY)")
else:
    dashscope.api_key = QWEN_API_KEY

WP_API_KEY = os.getenv('WP_API_KEY')

# --- 产品推广配置 ---
PRODUCT_URL = "https://fengshuispaceplanner.com/product/personalized-feng-shui-talisman/"
PRODUCT_NAME = "Personalized Feng Shui Talisman"

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

# ==========================================
#  核心逻辑: 内容截断 / 付费墙过滤器
# ==========================================
def filter_report_for_free_tier(full_text):
    """
    安全逻辑:
    1. 保留 'Positive Aspects' (积极方面)。
    2. 只保留 'Areas for Improvement' (改进建议) 的第 1 条。
    3. 删除所有后续内容 (Recommended Changes, Special Considerations)。
    """
    lines = full_text.split('\n')
    output_lines = []
    
    found_improvement_section = False
    bullet_count = 0
    
    # 必须与 System Prompt 中的标题完全一致
    IMPROVEMENT_HEADER = "## Areas for Improvement"
    
    for line in lines:
        stripped_line = line.strip()

        # 1. 检查是否到达 "Areas for Improvement" 区域
        if IMPROVEMENT_HEADER in line:
            found_improvement_section = True
            output_lines.append(line)
            continue
            
        # 2. 在该区域之前的内容全部保留 (简介, Positive Aspects)
        if not found_improvement_section:
            output_lines.append(line)
            continue
            
        # 3. 进入 "Areas for Improvement" 区域后的处理
        if found_improvement_section:
            # 检查是否为列表项 (-, *, 1.)
            is_list_item = ( stripped_line.startswith(('-', '*')) or (stripped_line and stripped_line[0].isdigit() and stripped_line[1:].startswith('.')) )
            
            if is_list_item:
                bullet_count += 1
                if bullet_count == 1:
                    # 只保留第一条问题
                    output_lines.append(line)
                else:
                    # 遇到第二条问题时，立即停止处理
                    break
            else:
                # 保留非列表项的文本 (例如该段落的介绍语)
                if bullet_count < 2:
                    output_lines.append(line)

    # 4. 追加付费墙提示信息
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

# --- 辅助工具函数 ---
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
    """计算命卦 (Kua Number)"""
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
    """获取吉凶方位"""
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

# --- 路由定义 ---

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "Feng Shui API (Qwen Edition - V2 Logic)",
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
#  接口 1: 分析 (生成 + 存储 + 截断)
# ==========================================
@app.route('/analyze-fengshui', methods=['POST', 'OPTIONS'])
def analyze_fengshui():
    # 处理预检请求 (OPTIONS)
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    logger.info(f"📝 Received request from Origin: {request.headers.get('Origin')}")
    
    # API Key 验证 (可选，如果前端没传可以注释掉)
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if WP_API_KEY and api_key != WP_API_KEY:
        logger.warning("Invalid API Key attempt")
        # return jsonify({"error": "Invalid or missing API key"}), 401 
        # 暂时注释掉 401，以免前端没配 Key 导致调不通，正式上线可开启

    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        grid_data = data.get('gridData', {})
        is_paid = data.get('isPaid', False) 
        
        # 1. 处理个人信息与命卦 (V2 特性)
        personal_info = data.get('personalInfo', {})
        gender = personal_info.get('gender', '')
        birth_date = personal_info.get('birthDate', '')
        
        birth_year = ''
        if birth_date:
            if '-' in birth_date:
                birth_year = birth_date.split('-')[0]
            elif '/' in birth_date:
                birth_year = birth_date.split('/')[0]
            
        kua_number = None
        favorable_directions = {}
        
        if gender and birth_year:
            kua_number = calculate_kua_number(gender, birth_year)
            favorable_directions = get_favorable_directions(kua_number)

        room_description = format_grid_data_for_ai(grid_data)
        
        # 2. 准备 Prompt
        search_query = "bedroom feng shui layout bed position"
        if "mirror" in room_description.lower(): search_query += " mirror facing bed"
        if "door" in room_description.lower(): search_query += " bed facing door"
        
        book_context = ""
        if kb_handler:
            book_context = kb_handler.get_relevant_context(search_query)
        if not book_context:
            book_context = "General Feng Shui principles apply."

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
        3. Do not make it look like an ad, but like a professional prescription.
        4. ALWAYS provide SPECIFIC PLACEMENT INSTRUCTIONS for the talisman (e.g., "Northeast corner", "Under your bed", "On the Southwest wall") based on the user's unique bedroom layout and identified feng shui issues.
        5. Emphasize that each talisman is personalized to address the specific energy imbalances found in their analysis, making it more effective than generic solutions.

        ***************************************
        
        ## Special Considerations
        (Provide general advice on energy flow.)
        """

        # 3. 调用 AI
        logger.info(f"📝 Calling Qwen API (qwen-plus)...")
        # 使用 dashscope.Generation.call (兼容旧版和新版SDK)
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
            
            # 4. 生成 Report ID 并存储完整版 (V2 特性)
            report_id = str(uuid.uuid4())
            
            reports_db[report_id] = {
                "full_content": full_analysis,
                "created_at": time.time(),
                "kua": kua_number,
                "favorableDirections": favorable_directions
            }
            
            # 5. 根据付费状态决定返回内容 (V2 特性)
            final_content = full_analysis
            is_locked = False
            
            if not is_paid:
                # 应用截断逻辑
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
        return jsonify({"success": False, "error": str(e)}), 500

# ==========================================
#  接口 2: 验证订单号并解锁报告 (修改版)
# ==========================================
@app.route('/unlock-report', methods=['POST', 'OPTIONS'])
def unlock_report():
    # 处理预检请求
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
        
    data = request.json
    report_id = data.get('reportId')
    order_id = data.get('orderId') # 新增：获取用户输入的订单号
    
    # 1. 基础检查
    if not report_id or report_id not in reports_db:
        return jsonify({"success": False, "error": "Report session expired. Please click Analyze again."}), 404
    
    if not order_id:
        return jsonify({"success": False, "error": "Please enter your Order ID."}), 400

    # 2. 去 WooCommerce 查单 (核心逻辑)
    logger.info(f"🔍 Verifying Order ID: {order_id} for Report: {report_id}")
    
    try:
        # 构造 WooCommerce API URL
        # 注意：WooCommerce 订单号通常是数字
        wc_api_url = f"{WOO_URL}/wp-json/wc/v3/orders/{order_id}"
        
        response = requests.get(
            wc_api_url, 
            auth=(WOO_CK, WOO_CS),
            timeout=10
        )
        
        if response.status_code != 200:
            logger.warning(f"❌ Order check failed: {response.status_code}")
            return jsonify({"success": False, "error": "Invalid Order ID or Order not found."}), 404
            
        order_data = response.json()
        order_status = order_data.get('status')
        
        # 3. 验证订单状态
        # 允许的状态: completed (完成), processing (处理中 - 用户付完款通常是这个状态)
        valid_statuses = ['completed', 'processing']
        
        if order_status in valid_statuses:
            logger.info(f"✅ Order {order_id} is valid ({order_status}). Unlocking...")
            
            report_data = reports_db[report_id]
            return jsonify({
                "success": True,
                "reportId": report_id,
                "analysis": report_data['full_content'], # 返回完整内容
                "isLocked": False,
                "kua": report_data.get('kua'),
                "favorableDirections": report_data.get('favorableDirections')
            })
        else:
            return jsonify({
                "success": False, 
                "error": f"Order status is '{order_status}'. Payment not confirmed yet."
            }), 400

    except Exception as e:
        logger.error(f"❌ WooCommerce API Error: {str(e)}")
        return jsonify({"success": False, "error": "Verification failed. Please try again."}), 500
