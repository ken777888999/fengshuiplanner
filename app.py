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
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# 2. 初始化 Flask 应用
app = Flask(__name__)

# 3. 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 4. 允许跨域请求
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
        
        # 提取物品 (List of strings)
        # 注意：前端传来的 items 是一个数组，可能包含字符串(物品)
        # 前端 JS 逻辑：gridData[position].push(el.type)
        # 另外 JS 中 gridData[position].areaTypes 是附加属性，JSON序列化时可能会丢失
        # 我们主要处理物品列表
        
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

# --- 核心接口：名称已修正为 /analyze-fengshui 以匹配前端 ---
@app.route('/analyze-fengshui', methods=['POST'])
def analyze_fengshui():
    
    if not DASHSCOPE_API_KEY:
        logger.error("DASHSCOPE_API_KEY is missing.")
        return jsonify({"success": False, "error": "Server configuration error"}), 500

    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        # 1. 解析前端数据
        # 前端传参结构: { gridData: {...}, userInfo: {...}, isPaid: bool, ... }
        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)  # 对应前端 IS_PREMIUM_USER
        
        # 提取用户关注点
        concerns = user_info.get('concerns', 'General wellness and harmony')
        birth_year = user_info.get('birthYear', 'Not specified')

        # 2. 将 Grid 数据翻译成文本
        room_description = interpret_grid_data(grid_data)
        
        logger.info(f"Analyzing request. Premium: {is_paid}. Layout: {room_description[:50]}...")

        # 3. 读取书籍知识库
        feng_shui_knowledge = extract_knowledge_for_prompt()
        
        # 4. 构建 Prompt
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

        # 5. 调用阿里云 Qwen API
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "qwen-plus", # 建议使用 qwen-plus 获得更好的逻辑分析能力
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
                
                # --- 关键修正：返回格式必须匹配前端 processAnalysisResponse ---
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
