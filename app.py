import os
import logging
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# 引入知识库处理模块 (确保 knowledge_base_handler.py 在同一目录下)
from knowledge_base_handler import extract_knowledge_for_prompt

# 1. 加载环境变量
load_dotenv()
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# 2. 初始化 Flask 应用
app = Flask(__name__)

# 3. 配置日志 (方便在 Render 后台看报错)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 4. 允许跨域请求 (允许 WordPress 前端访问)
CORS(app)

@app.route('/health', methods=['GET'])
def health_check():
    """健康检查接口，用于 Render 确认服务是否存活"""
    return jsonify({"status": "healthy", "service": "Feng Shui AI API"}), 200

@app.route('/analyze', methods=['POST'])
def analyze_fengshui():
    """核心分析接口"""
    
    # 检查 API Key 是否存在
    if not DASHSCOPE_API_KEY:
        logger.error("DASHSCOPE_API_KEY is missing in environment variables.")
        return jsonify({"error": "Server configuration error: API Key missing"}), 500

    try:
        # 获取前端发送的数据
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        room_description = data.get('roomDescription', '')
        concerns = data.get('concerns', '')
        # 暂时跳过复杂的支付验证，直接读取前端传来的布尔值 (默认为 False)
        is_paid = data.get('isPremium', False)

        logger.info(f"Received request. Premium: {is_paid}")

        # --- 关键步骤：从真实书籍中提取知识 ---
        # 这会去读取 knowledge_base 文件夹里的 PDF/EPUB
        feng_shui_knowledge = extract_knowledge_for_prompt()
        
        # 确定分析深度
        depth = "comprehensive and detailed" if is_paid else "basic and concise"
        
        # --- 构建提示词 (Prompt) ---
        # 结构化 Prompt，让 AI 更好地区分“用户情况”和“参考书内容”
        prompt = f"""
        Role: You are a professional Feng Shui Master.
        
        Task: Analyze the user's bedroom layout based STRICTLY on the provided [Reference Knowledge Base] and general Feng Shui principles.

        [User's Bedroom Layout]
        {room_description}
        
        [User's Specific Concerns]
        {concerns}
        
        [Reference Knowledge Base (From uploaded books)]
        {feng_shui_knowledge}
        
        [Output Instructions]
        Provide a {depth} Feng Shui analysis.
        Please format your response using the following Markdown headers:
        
        ## Positive Aspects
        (Identify elements that align with the principles in the reference texts)
        
        ## Areas for Improvement
        (Identify conflicts with the principles in the reference texts)
        
        ## Recommended Changes
        (Provide 3-5 actionable steps)
        
        ## Special Considerations
        (Personalized advice based on user concerns)
        
        {'IMPORTANT: Since this is a Premium user, provide advanced remedies, specific object placement advice, and explain the "Why" behind the principles.' if is_paid else 'IMPORTANT: Since this is a Free user, keep the advice general and brief. Do not go into deep detail.'}
        """

        # --- 调用阿里云 Qwen (通义千问) API ---
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "qwen-turbo",  # 或者使用 qwen-plus 获得更好效果
            "input": {
                "messages": [
                    {"role": "system", "content": "You are a helpful and wise Feng Shui consultant."},
                    {"role": "user", "content": prompt}
                ]
            },
            "parameters": {
                "result_format": "text"
            }
        }

        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            if "output" in result and "text" in result["output"]:
                ai_analysis = result["output"]["text"]
                return jsonify({"result": ai_analysis})
            else:
                logger.error(f"Unexpected API response structure: {result}")
                return jsonify({"error": "Failed to parse AI response"}), 500
        else:
            logger.error(f"API Error: {response.status_code} - {response.text}")
            return jsonify({"error": "AI Service currently unavailable"}), 500

    except Exception as e:
        logger.error(f"Server Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # 本地运行时开启 Debug 模式
    app.run(debug=True, port=5000)
