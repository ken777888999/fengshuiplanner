import os
import logging
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# 引入知识库处理模块
from knowledge_base_handler import extract_knowledge_for_prompt

# 1. 加载环境变量
load_dotenv()

# [修改点 1] 使用 Render 上配置的变量名 QWEN_API_KEY
DASHSCOPE_API_KEY = os.getenv("QWEN_API_KEY")

# [修改点 2] 获取用于验证前端请求的 Key (Render 上配置为 WP_API_KEY)
EXPECTED_CLIENT_KEY = os.getenv("WP_API_KEY")

# 2. 初始化 Flask 应用
app = Flask(__name__)

# 3. 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 4. 允许跨域请求
# 建议：在生产环境中，最好限制 origins 为你的实际域名
CORS(app) 

# --- 辅助函数：将九宫格数据转换为自然语言描述 ---
def interpret_grid_data(grid_data):
    """
    将前端传来的 gridData (JSON对象) 转换为 AI 可读的文本描述。
    映射关系参考前端 HTML 的 Bagua Grid。
    """
    if not grid_data:
        return "User has not provided a specific layout."

    # 九宫格位置映射
    position_map = {
        "1": "Northwest (NW) - Helpful People & Travel sector",
        "2": "North (N) - Career & Life Path sector",
        "3": "Northeast (NE) - Skills & Knowledge sector",
        "4": "West (W) - Creativity & Children sector",
        "5": "Center (C) - Health & Wellbeing (Tai Chi) sector",
        "6": "East (E) - Family & Health sector",
        "7": "Southwest (SW) - Love & Relationships sector",
        "8": "South (S) - Fame & Reputation sector",
        "9": "Southeast (SE) - Wealth & Prosperity sector"
    }

    description_lines = []
    
    for pos_key, items in grid_data.items():
        pos_name = position_map.get(str(pos_key), f"Position {pos_key}")
        
        elements = []
        area_types = []
        
        # 尝试解析 items
        if isinstance(items, list):
            elements = [item for item in items if isinstance(item, str)]
        elif isinstance(items, dict):
            # 防御性编程，以防数据结构变化
            elements = items.get('elements', [])
            area_types = items.get('areaTypes', [])

        if elements:
            formatted_elements = ", ".join(elements).replace("bed", "Bed").replace("door", "Door").replace("mirror", "Mirror")
            description_lines.append(f"- In the {pos_name}, there is: {formatted_elements}.")
            
    if not description_lines:
        return "The bedroom layout is empty."
        
    return "\n".join(description_lines)

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "Feng Shui AI API"}), 200

# --- 核心接口 ---
@app.route('/analyze-fengshui', methods=['POST'])
def analyze_fengshui():
    
    # 1. 检查服务器端 API Key 配置
    if not DASHSCOPE_API_KEY:
        logger.error("QWEN_API_KEY (DASHSCOPE_API_KEY) is missing in environment variables.")
        return jsonify({"success": False, "error": "Server configuration error"}), 500

    # 2. [新增] 验证前端传来的 Key，防止被盗刷
    # 前端 JS 会在 header 中发送 'X-API-Key': 'FengShuiApiKey2025Simple'
    client_key = request.headers.get('X-API-Key')
    
    # 如果 Render 上配置了 WP_API_KEY，则进行验证
    if EXPECTED_CLIENT_KEY and client_key != EXPECTED_CLIENT_KEY:
        logger.warning(f"Unauthorized access attempt. Received: {client_key}, Expected: {EXPECTED_CLIENT_KEY}")
        return jsonify({"success": False, "error": "Unauthorized: Invalid API Key"}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        # 3. 解析前端数据
        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)
        
        concerns = user_info.get('concerns', 'General wellness and harmony')
        birth_year = user_info.get('birthYear', 'Not specified')

        # 4. 将 Grid 数据翻译成文本
        room_description = interpret_grid_data(grid_data)
        
        logger.info(f"Analyzing request. Premium: {is_paid}. Layout: {room_description[:50]}...")

        # 5. 读取书籍知识库
        feng_shui_knowledge = extract_knowledge_for_prompt()
        
        # 6. 构建 Prompt
        depth = "deep, comprehensive, and explicitly detailed" if is_paid else "basic and general"
        
        prompt = f"""
        Role: You are a master Feng Shui consultant combining Form School and Compass School methods.
        
        Task: Analyze the user's bedroom layout based on the provided [Reference Knowledge Base] and the [User's Layout].

        [User's Profile]
        - Birth Year: {birth_year}
        - Primary Concerns: {concerns}

        [User's Bedroom Layout Description]
        {room_description}
        
        [Reference Knowledge Base (Strictly adhere to these principles)]
        {feng_shui_knowledge}
        
        [Output Format Requirements]
        You must respond in Markdown format with exactly these headers:
        
        ## Positive Aspects
        (List 2-3 strengths of the layout)
        
        ## Areas for Improvement
        (List the negative aspects or conflicts found in the layout)
        
        ## Recommended Changes
        (Provide actionable advice to fix the issues)
        
        ## Special Considerations
        (Address the user's specific concerns: {concerns})
        
        {'## Premium Deep Dive' if is_paid else ''}
        {'(Provide advanced cures, element balancing advice, and "Why" it works)' if is_paid else ''}

        [Tone]
        Professional, encouraging, and mystical yet practical.
        {'IMPORTANT: Since this is a Premium user, give extremely specific advice.' if is_paid else 'IMPORTANT: Since this is a Free user, keep the advice helpful but brief. Do not give advanced cures.'}
        """

        # 7. 调用阿里云 Qwen API
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "qwen-plus",
            "input": {
                "messages": [
                    {"role": "system", "content": "You are an expert Feng Shui Master."},
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
                return jsonify({
                    "success": True, 
                    "analysis": ai_analysis
                })
            else:
                logger.error(f"Unexpected API response: {result}")
                return jsonify({"success": False, "error": "Failed to parse AI response"}), 500
        else:
            logger.error(f"API Error: {response.status_code} - {response.text}")
            return jsonify({"success": False, "error": "AI Service unavailable"}), 500

    except Exception as e:
        logger.error(f"Server Error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
