import os
import logging
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS
from openai import OpenAI

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('app')

app = Flask(__name__)

# 1. 基础 CORS 配置 (作为第一道防线)
CORS(app, resources={r"/*": {"origins": "*"}})

# 获取 API Key
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# 2. 强力补丁：在每一个响应发出前，强制添加 CORS 头
# 这是为了解决 flask-cors 可能偶尔失效的问题
@app.after_request
def add_cors_headers(response):
    # 允许所有来源 (调试阶段最稳妥)
    response.headers['Access-Control-Allow-Origin'] = '*'
    # 允许的请求头
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    # 允许的方法
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy"}), 200

@app.route('/analyze-fengshui', methods=['POST', 'OPTIONS'])
def analyze_fengshui():
    # 3. 显式处理 OPTIONS 预检请求
    if request.method == 'OPTIONS':
        logger.info("Received OPTIONS request")
        response = make_response()
        # 这里的 headers 会被上面的 after_request 再次加强，双重保险
        return response, 200

    try:
        logger.info(f"📝 Received request from Origin: {request.headers.get('Origin')}")
        
        data = request.json
        if not data:
            logger.error("❌ No JSON data received")
            return jsonify({"error": "No data provided"}), 400

        # 提取数据
        room_type = data.get('roomType', 'General')
        birth_date = data.get('birthDate', 'Unknown')
        gender = data.get('gender', 'Unknown')
        direction = data.get('direction', 'Unknown')
        
        # 构建 Prompt
        prompt = f"""
        Act as a Feng Shui Master. Analyze this room:
        - Room Type: {room_type}
        - User Birth Date: {birth_date}
        - Gender: {gender}
        - House Facing Direction: {direction}

        Provide a detailed Feng Shui analysis including:
        1. Energy Flow (Qi) analysis.
        2. Lucky directions based on Kua number (calculate from birth date/gender).
        3. Color recommendations.
        4. Furniture placement advice.
        5. Any cures for bad sectors.
        
        Format the output in clean HTML (using <h3>, <p>, <ul>, <li> tags) so it can be directly displayed on a website. Do not include ```html or markdown tags.
        """

        logger.info("📝 Analyzing room layout...")

        # 调用 OpenAI
        completion = client.chat.completions.create(
            model="gpt-4o-mini",  # 或者 gpt-3.5-turbo
            messages=[
                {"role": "system", "content": "You are a helpful Feng Shui expert."},
                {"role": "user", "content": prompt}
            ]
        )

        analysis_result = completion.choices[0].message.content
        logger.info("✅ Analysis generated successfully.")
        
        return jsonify({"analysis": analysis_result})

    except Exception as e:
        logger.error(f"❌ Error processing request: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Render 会自动设置 PORT 环境变量，本地测试默认 10000
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
