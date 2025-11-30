import os
import json
import logging
from http import HTTPStatus
from functools import wraps

from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from dotenv import load_dotenv
import dashscope

# 引入自定义模块
try:
    from knowledge_base_handler import KnowledgeBaseHandler
    HAS_KB_HANDLER = True
except ImportError:
    HAS_KB_HANDLER = False
    print("⚠️ Warning: knowledge_base_handler module not found. Running without local KB.")

# 加载环境变量
load_dotenv()

# --- 1. 配置日志 ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('app')

app = Flask(__name__)

# --- [关键修复] CORS 配置 ---
# ✅ 只保留这一处配置，它会自动处理 OPTIONS 请求和 Header，不会产生冲突
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ❌ [已删除] after_request 函数
# 原来的 after_request 代码块已被删除，因为它导致了 "multiple values" 错误

# --- 2. 配置 API Keys ---
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
if not QWEN_API_KEY:
    logger.error("⚠️ 严重警告: 未检测到 QWEN_API_KEY，AI 功能将无法使用。")
else:
    dashscope.api_key = QWEN_API_KEY

WP_API_KEY = os.getenv('WP_API_KEY')

# --- 商品推广配置 (保留) ---
PROMO_PRODUCT_NAME = "Tai Sui Protection Talisman"
PROMO_PRODUCT_URL = "https://your-shop-domain.com/products/tai-sui-talisman"

# --- 3. 初始化知识库 ---
kb_handler = None
if HAS_KB_HANDLER:
    try:
        kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
        kb_handler.load_knowledge_base()
    except Exception as e:
        logger.warning(f"⚠️ 知识库初始化失败: {e}")

# --- 4. 工具函数 ---

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # --- [关键修复] 简化 OPTIONS 处理 ---
        # Flask-CORS 会自动添加 Access-Control-Allow-* 头
        # 我们只需要直接返回 200 OK 即可，不要手动再 add header 了
        if request.method == 'OPTIONS':
            return jsonify({"status": "ok"}), 200

        # 正常的 API Key 检查
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key or (WP_API_KEY and api_key != WP_API_KEY):
            return jsonify({"error": "Invalid or missing API key"}), 401
            
        return f(*args, **kwargs)
    return decorated_function

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

# --- 5. 路由定义 ---

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "Feng Shui AI (Qwen Edition)",
        "cors_status": "enabled"
    })

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "model": "qwen-plus",
        "kb_loaded": kb_handler is not None
    })

@app.route('/analyze-fengshui', methods=['POST', 'OPTIONS']) 
@require_api_key
def analyze_fengshui():
    """
    核心分析接口
    """
    # 如果是 OPTIONS 请求，require_api_key 已经处理并返回了
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200

    try:
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        grid_data = data.get('gridData', {})
        is_paid = data.get('isPaid', False)

        room_description = format_grid_data_for_ai(grid_data)
        logger.info(f"📝 Analyzing room (Paid: {is_paid})")
        
        # 检索知识库
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

        # --- Prompt 构建 ---
        depth_instruction = "Provide a highly detailed, professional analysis with specific actionable advice. Make the user feel the value of the report."
        
        system_prompt = f"""
        You are a Master Feng Shui Consultant using the 'Flying Star' and 'Eight Mansions' methods.
        
        === ANCIENT KNOWLEDGE BASE ===
        {book_context}
        ==============================
        
        Your Task:
        Analyze the user's bedroom layout based on the description below.
        
        Layout Description:
        {room_description}
        
        Instruction: {depth_instruction}
        
        Output Format (Markdown):
        ## Positive Aspects
        (List 2-3 good points found in the layout. Be detailed.)
        
        ## Areas for Improvement
        (Identify clashes, e.g., mirrors facing bed. Be strict.)
        
        ## Recommended Changes
        (Actionable advice. Give specific remedies like 'move bed to East'. 
        
        IMPORTANT MARKETING INSTRUCTION:
        Regardless of the specific layout, you MUST recommend using a specific spiritual item to neutralize general negative energy and boost luck.
        Specifically, recommend the '{PROMO_PRODUCT_NAME}'.
        When mentioning it, you MUST use this exact Markdown link format: [{PROMO_PRODUCT_NAME}]({PROMO_PRODUCT_URL}).
        Explain briefly why this specific talisman helps (e.g., balancing the magnetic field).
        )
        
        ## Special Considerations
        (Provide general advice on energy flow.)
        """

        # 调用 AI
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
            return jsonify({
                "success": True,
                "analysis": analysis_result,
                "isPremium": is_paid
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
