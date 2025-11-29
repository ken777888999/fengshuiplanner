import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import dashscope
from http import HTTPStatus

# 引入自定义模块
from knowledge_base_handler import KnowledgeBaseHandler
from middleware import require_api_key

# 加载环境变量
load_dotenv()

app = Flask(__name__)
CORS(app) # 允许跨域

# 1. 配置 Qwen (DashScope)
qwen_api_key = os.getenv("QWEN_API_KEY")
if not qwen_api_key:
    print("⚠️ 警告: 未检测到 QWEN_API_KEY，AI 功能将无法使用。")
else:
    dashscope.api_key = qwen_api_key

# 2. 初始化知识库
print("🔄 正在初始化风水知识库...")
kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
kb_handler.load_knowledge_base()
print("✅ 风水知识库准备就绪。")

def format_grid_data_for_ai(grid_data):
    """
    将前端传来的九宫格 JSON 数据转换为 AI 可读的文本描述。
    """
    position_map = {
        "1": "Northwest (NW) - Mentor Luck",
        "2": "North (N) - Career Luck",
        "3": "Northeast (NE) - Knowledge Luck",
        "4": "West (W) - Children/Creativity Luck",
        "5": "Center (C) - Health/General Luck",
        "6": "East (E) - Family/Health Luck",
        "7": "Southwest (SW) - Love/Relationship Luck",
        "8": "South (S) - Fame/Recognition Luck",
        "9": "Southeast (SE) - Wealth Luck"
    }
    
    description = []
    
    for pos_key, items in grid_data.items():
        if not isinstance(items, list):
            continue
            
        pos_name = position_map.get(pos_key, f"Position {pos_key}")
        
        # 处理该格子里的物品
        readable_items = []
        for item in items:
            if item == 'bed':
                readable_items.append("Sleeping Bed")
            else:
                readable_items.append(item.capitalize())
        
        # 处理区域类型 (Private, Public 等)
        area_types = []
        if hasattr(items, 'areaTypes'): # 如果前端传了这种结构
             area_types = items.areaTypes
        # 或者如果前端是分开传的，这里简化处理，假设 items 里只包含物品名称
        
        if readable_items:
            description.append(f"- In the {pos_name}: contains {', '.join(readable_items)}.")
            
    if not description:
        return "The room is currently empty."
        
    return "\n".join(description)

@app.route('/')
def home():
    return "Feng Shui Planner API (Qwen Edition) is Running! 🚀"

@app.route('/analyze-fengshui', methods=['POST'])
@require_api_key
def analyze_fengshui():
    """
    适配前端的分析接口 (使用 Qwen 模型)
    """
    try:
        # 1. 获取 JSON 数据
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)

        # 2. 转换数据
        room_description = format_grid_data_for_ai(grid_data)
        
        # 3. 获取知识库上下文
        search_query = "bedroom feng shui layout bed position"
        if "mirror" in str(grid_data):
            search_query += " mirror facing bed"
        
        book_context = kb_handler.get_relevant_context(search_query)
        if not book_context:
            book_context = "General Feng Shui principles apply."

        # 4. 构建 Prompt
        system_prompt = f"""
        You are a Master Feng Shui Consultant using the 'Flying Star' and 'Form School' methods.
        
        === ANCIENT KNOWLEDGE BASE ===
        {book_context}
        ==============================
        
        Your Task:
        Analyze the user's bedroom layout.
        
        Layout Description:
        {room_description}
        
        User Info:
        Birth Year: {user_info.get('birthYear', 'Unknown')}
        Concerns: {user_info.get('concerns', 'General')}
        
        Output Format (Markdown):
        ## Positive Aspects
        (2-3 points)
        
        ## Areas for Improvement
        (2-3 points. Be strict about mirrors facing beds or beds aligned with doors.)
        
        ## Recommended Changes
        (Actionable advice)
        
        ## Special Considerations
        (Brief advice based on birth year)
        """

        # 5. 调用阿里云 Qwen API
        response = dashscope.Generation.call(
            model='qwen-plus', # 或者 'qwen-max' 效果更好
            messages=[
                {'role': 'system', 'content': 'You are a helpful Feng Shui expert.'},
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
            print(f"❌ Qwen API Error: {response.code} - {response.message}")
            return jsonify({
                "success": False, 
                "error": f"AI Service Error: {response.message}"
            }), 500

    except Exception as e:
        print(f"❌ Server Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
