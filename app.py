import os
import logging
from functools import wraps
from http import HTTPStatus

from flask import Flask, request, jsonify
from flask_cors import CORS
import dashscope

# --- 1. 初始化 Flask 应用 ---
app = Flask(__name__)

# ✅ [核心修复] 允许所有跨域请求。
# Flask-CORS 会自动处理 OPTIONS 请求，千万不要自己写代码去拦截 OPTIONS！
CORS(app, resources={r"/*": {"origins": "*"}})

# --- 2. 配置日志 ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('app')

# --- 3. 读取环境变量 ---
QWEN_API_KEY = os.environ.get("QWEN_API_KEY")
WP_API_KEY = os.environ.get("WP_API_KEY")

# 配置 Dashscope (阿里云 Qwen)
if QWEN_API_KEY:
    dashscope.api_key = QWEN_API_KEY
    logger.info("✅ Qwen API Key loaded.")
else:
    logger.error("❌ Qwen API Key NOT found in environment variables!")

# --- 4. 鉴权装饰器 ---
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 如果是 OPTIONS 请求（浏览器预检），直接放行，CORS 库会处理 Header
        if request.method == 'OPTIONS':
            return jsonify({"status": "ok"}), 200

        # 获取前端传来的 Key
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        # 验证 Key (如果环境变量里设置了 WP_API_KEY)
        if WP_API_KEY and api_key != WP_API_KEY:
            logger.warning(f"⛔ Invalid API Key attempt: {api_key}")
            return jsonify({"error": "Invalid API key"}), 401
            
        return f(*args, **kwargs)
    return decorated_function

# --- 5. 辅助函数：格式化数据给 AI ---
def format_grid_data(grid_data):
    if not grid_data:
        return "An empty bedroom."
    
    desc = []
    for pos, data in grid_data.items():
        items = data.get('items', [])
        area = data.get('areaTypes', [])
        
        # 转换一下床的描述，更易读
        readable_items = []
        for item in items:
            if "Bed" in item:
                readable_items.append(item) # 保留床的方向描述
            else:
                readable_items.append(item.capitalize())

        if readable_items or area:
            item_str = ", ".join(readable_items) if readable_items else "empty space"
            area_str = f"(Area Type: {', '.join(area)})" if area else ""
            desc.append(f"- Position {pos}: {item_str} {area_str}")
            
    return "\n".join(desc)

# --- 6. 路由定义 ---

@app.route('/')
def home():
    """健康检查接口"""
    return jsonify({
        "status": "online", 
        "message": "Feng Shui Server is running!",
        "qwen_key_set": bool(QWEN_API_KEY)
    })

@app.route('/analyze-fengshui', methods=['POST'])
@require_api_key
def analyze_fengshui():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data received"}), 400

        grid_data = data.get('gridData', {})
        is_paid = data.get('isPaid', False)

        logger.info(f"🔮 Receiving analysis request. Paid: {is_paid}")

        # 1. 准备 Prompt
        room_desc = format_grid_data(grid_data)
        
        # 根据付费状态调整 Prompt
        role_desc = "You are a Grandmaster of Feng Shui."
        if is_paid:
            instruction = "Provide a DEEP, DETAILED analysis using Flying Star Feng Shui. Give specific remedies."
        else:
            instruction = "Provide a brief, general summary of the layout."

        system_prompt = f"""
        {role_desc}
        
        User's Bedroom Layout:
        {room_desc}
        
        Task: {instruction}
        
        Output Format (Markdown):
        ## General Energy
        ...
        ## Specific Issues
        ...
        ## Remedies & Suggestions
        ...
        """

        # 2. 调用 Qwen API
        if not QWEN_API_KEY:
            return jsonify({"success": False, "error": "Server configuration error: Missing AI Key"}), 500

        response = dashscope.Generation.call(
            model='qwen-plus',
            messages=[
                {'role': 'system', 'content': 'You are a helpful Feng Shui assistant.'},
                {'role': 'user', 'content': system_prompt}
            ],
            result_format='message'
        )

        # 3. 处理响应
        if response.status_code == HTTPStatus.OK:
            ai_text = response.output.choices[0].message.content
            return jsonify({
                "success": True,
                "analysis": ai_text,
                "isPremium": is_paid
            })
        else:
            error_msg = response.message
            logger.error(f"❌ AI API Error: {error_msg}")
            return jsonify({"success": False, "error": f"AI Service Error: {error_msg}"}), 500

    except Exception as e:
        logger.error(f"❌ Internal Server Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    # Render 要求监听 0.0.0.0
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
