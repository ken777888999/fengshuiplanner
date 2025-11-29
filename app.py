import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import dashscope
from http import HTTPStatus

# 引入自定义模块 (确保这些文件在同一目录下)
from knowledge_base_handler import KnowledgeBaseHandler
from middleware import require_api_key

# 加载环境变量
load_dotenv()

app = Flask(__name__)
CORS(app) # 允许跨域请求

# 1. 配置 Qwen (DashScope) - 完全移除 OpenAI
qwen_api_key = os.getenv("QWEN_API_KEY")
if not qwen_api_key:
    # 修复：添加了开头的引号
    print("⚠️ 警告: 未检测到 QWEN_API_KEY，AI 功能将无法使用。")
else:
    dashscope.api_key = qwen_api_key

# 2. 初始化知识库
print("🔄 正在初始化风水知识库...")
try:
    kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
    kb_handler.load_knowledge_base()
    print("✅ 风水知识库准备就绪。")
except Exception as e:
    print(f"⚠️ 知识库初始化失败 (非致命错误): {e}")
    kb_handler = None

def format_grid_data_for_ai(grid_data):
    """
    将前端传来的九宫格 JSON 数据转换为 AI 可读的文本描述。
    
    修复后的数据结构示例:
    {
        "1": { "items": ["bed", "lamp"], "areaTypes": ["private"] },
        "2": { "items": [], "areaTypes": ["public"] }
    }
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
    
    for pos_key, cell_data in grid_data.items():
        # 初始化变量
        items = []
        area_types = []

        # 健壮性处理：确保能解析字典结构
        if isinstance(cell_data, dict):
            items = cell_data.get('items', [])
            area_types = cell_data.get('areaTypes', [])
        elif isinstance(cell_data, list):
            # 旧格式兼容（如果有旧缓存）
            items = cell_data
            
        # 如果这个格子既没有物品也没有区域标记，跳过
        if not items and not area_types:
            continue
            
        pos_name = position_map.get(pos_key, f"Position {pos_key}")
        
        # 构建描述部分
        desc_parts = []
        
        # 1. 处理物品
        if items:
            readable_items = []
            for item in items:
                if item == 'bed':
                    readable_items.append("Sleeping Bed")
                else:
                    readable_items.append(item.capitalize())
            desc_parts.append(f"contains {', '.join(readable_items)}")
            
        # 2. 处理区域类型 (Private, Public 等)
        if area_types:
            readable_types = [t.capitalize() for t in area_types]
            desc_parts.append(f"is marked as {', '.join(readable_types)} area")
            
        # 组合描述
        if desc_parts:
            description.append(f"- In the {pos_name}: {', and '.join(desc_parts)}.")
            
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
    核心分析接口 (使用 Qwen 模型)
    """
    try:
        # 1. 获取 JSON 数据
        data = request.json
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)

        # 2. 转换数据为文本描述
        room_description = format_grid_data_for_ai(grid_data)
        print(f"📝 生成的房间描述:\n{room_description}") # 调试日志
        
        # 3. 获取知识库上下文
        search_query = "bedroom feng shui layout bed position"
        # 如果有镜子，增加相关搜索
        if "mirror" in room_description.lower():
            search_query += " mirror facing bed"
        
        book_context = ""
        if kb_handler:
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
        # 使用 qwen-plus 或 qwen-max
        response = dashscope.Generation.call(
            model='qwen-plus', 
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
