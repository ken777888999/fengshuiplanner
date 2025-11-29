import os
import json
import logging
from http import HTTPStatus
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import dashscope

# 引入自定义模块 (确保 knowledge_base_handler.py 在同一目录下)
# 如果没有这个文件，请注释掉相关行，我会提供一个降级方案
try:
    from knowledge_base_handler import KnowledgeBaseHandler
    HAS_KB_HANDLER = True
except ImportError:
    HAS_KB_HANDLER = False
    print("⚠️ Warning: knowledge_base_handler module not found. Running without local KB.")

# 加载环境变量
load_dotenv()

# --- 1. 配置日志 (来自 Code 2) ---
# 这对于在 Render 后台排查错误非常有用
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('app')

app = Flask(__name__)
CORS(app)

# --- 2. 配置 API Keys ---
# Qwen 的 Key (用于调用 AI)
QWEN_API_KEY = os.getenv("QWEN_API_KEY")
if not QWEN_API_KEY:
    logger.error("⚠️ 严重警告: 未检测到 QWEN_API_KEY，AI 功能将无法使用。")
else:
    dashscope.api_key = QWEN_API_KEY

# 前端验证 Key (用于保护你的接口不被滥用)
WP_API_KEY = os.getenv('WP_API_KEY')

# --- 3. 初始化知识库 (来自 Code 1) ---
kb_handler = None
if HAS_KB_HANDLER:
    logger.info("🔄 正在初始化风水知识库...")
    try:
        kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
        kb_handler.load_knowledge_base()
        logger.info("✅ 风水知识库准备就绪。")
    except Exception as e:
        logger.warning(f"⚠️ 知识库初始化失败 (非致命错误): {e}")

# --- 4. 工具函数 ---

# API 密钥验证装饰器 (来自 Code 2 - 更方便，不需要额外 middleware 文件)
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 尝试从 Header 或 URL 参数获取 Key
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        # 验证 Key 是否匹配环境变量中的 WP_API_KEY
        if not api_key or (WP_API_KEY and api_key != WP_API_KEY):
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# 格式化数据函数 (来自 Code 1 - 极其重要，保留方位映射)
def format_grid_data_for_ai(grid_data):
    """
    将前端传来的九宫格 JSON 数据转换为 AI 可读的文本描述。
    """
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

        # 健壮性处理：确保能解析字典结构
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
        "endpoints": {
            "/analyze-fengshui": "POST - Main analysis",
            "/health": "GET - Health check"
        }
    })

# 健康检查 (来自 Code 2 - Render 部署必备)
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "ok",
        "model": "qwen-plus",
        "kb_loaded": kb_handler is not None
    })

@app.route('/analyze-fengshui', methods=['POST'])
@require_api_key
def analyze_fengshui():
    """
    核心分析接口 (使用 Qwen 模型 + 健壮的错误处理)
    """
    try:
        # 1. 获取并验证数据
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)

        # 2. 转换数据为文本描述
        room_description = format_grid_data_for_ai(grid_data)
        logger.info(f"📝 Analyzing room for user (Paid: {is_paid})")
        
        # 3. 获取知识库上下文 (动态检索)
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

        # 4. 构建 Prompt
        # 根据是否付费调整输出深度
        depth_instruction = "Provide a highly detailed, professional analysis." if is_paid else "Provide a concise but helpful analysis."
        
        system_prompt = f"""
        You are a Master Feng Shui Consultant using the 'Flying Star' and 'Eight Mansions' methods.
        
        === ANCIENT KNOWLEDGE BASE ===
        {book_context}
        ==============================
        
        Your Task:
        Analyze the user's bedroom layout based on the description below.
        
        Layout Description:
        {room_description}
        
        User Info:
        Birth Year: {user_info.get('birthYear', 'Unknown')}
        Gender: {user_info.get('gender', 'Unknown')}
        Concerns: {user_info.get('concerns', 'General Well-being')}
        
        Instruction: {depth_instruction}
        
        Output Format (Markdown):
        ## Positive Aspects
        (List 2-3 good points found in the layout)
        
        ## Areas for Improvement
        (Identify clashes, e.g., mirrors facing bed, bed in death line. Be strict.)
        
        ## Recommended Changes
        (Actionable advice. If paid user, give specific remedies like 'add a metal wu lou'.)
        
        ## Special Considerations
        (Brief advice based on birth year/Kua number if applicable)
        """

        # 5. 调用阿里云 Qwen API
        # 建议使用 qwen-plus 或 qwen-max 以获得更好的逻辑推理
        response = dashscope.Generation.call(
            model='qwen-plus', 
            messages=[
                {'role': 'system', 'content': 'You are a helpful and traditional Feng Shui expert.'},
                {'role': 'user', 'content': system_prompt}
            ],
            result_format='message'
        )

        # 6. 处理响应
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
