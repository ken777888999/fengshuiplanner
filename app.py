from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import logging
import random
import string
import time
import re
from datetime import datetime
import openai
import traceback
# 导入知识库处理模块
from knowledge_base_handler import extract_knowledge_for_prompt

# 创建应用实例
app = Flask(__name__)
CORS(app)  # 允许跨域请求

# 配置日志
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 配置环境
API_KEYS = {
    "BSQ+a+q&5`Kv0O!3hons/-hb`I/-!M": "client1"
}

# 获取OpenAI API密钥
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
if not OPENAI_API_KEY:
    logger.warning("OpenAI API key not found in environment variables")
else:
    openai.api_key = OPENAI_API_KEY
    logger.info("OpenAI API key configured successfully")

# 初始化计数器
request_counter = 0

# 区域名称映射
BAGUA_POSITIONS = {
    "1": "Northwest (Knowledge)",
    "2": "North (Career)",
    "3": "Northeast (Wisdom)",
    "4": "West (Children)",
    "5": "Center (Health)",
    "6": "East (Family)",
    "7": "Southwest (Relationships)",
    "8": "South (Fame)",
    "9": "Southeast (Wealth)"
}

# 元素类型映射
ELEMENT_TYPES = {
    "bed": "bed",
    "door": "door",
    "window": "window",
    "mirror": "mirror",
    "device": "electronic device",
    "sofa": "sofa",
    "table": "table",
    "plant": "plant"
}

# 区域类型映射
AREA_TYPES = {
    "private": "private area",
    "public": "public area", 
    "work": "work area",
    "entertain": "entertainment area"
}

# API密钥验证装饰器
def require_api_key(f):
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if api_key not in API_KEYS:
            logger.warning(f"Invalid API key attempt: {api_key}")
            return jsonify({"success": False, "message": "Invalid API key"}), 401
        return f(*args, **kwargs)
    decorated_function.__name__ = f.__name__
    return decorated_function

# 生成唯一会话ID
def generate_session_id():
    timestamp = int(time.time())
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    return f"{timestamp}-{random_str}"

# 格式化布局数据
def format_layout_data(grid_data):
    layout_description = []
    
    for position in sorted(grid_data.keys(), key=int):
        if not grid_data[position]:
            continue
            
        bagua_name = BAGUA_POSITIONS.get(position, f"Position {position}")
        elements = grid_data[position]
        
        # 处理元素
        element_names = []
        area_types = []
        
        for item in elements:
            if item in ELEMENT_TYPES:
                element_names.append(ELEMENT_TYPES[item])
                
        # 处理区域类型
        if 'areaTypes' in grid_data[position]:
            for area_type in grid_data[position]['areaTypes']:
                if area_type in AREA_TYPES:
                    area_types.append(AREA_TYPES[area_type])
        
        # 构建描述
        if element_names:
            elements_text = ", ".join(element_names)
            layout_description.append(f"In the {bagua_name} area, there is a {elements_text}")
        
        if area_types:
            types_text = ", ".join(area_types)
            layout_description.append(f"The {bagua_name} area is marked as a {types_text}")
    
    return ". ".join(layout_description) + "."

# 调用OpenAI API分析风水
def analyze_feng_shui(prompt, retries=3, model="gpt-3.5-turbo"):
    logger.info(f"Analyzing feng shui with prompt length: {len(prompt)}")
    
    for attempt in range(retries):
        try:
            completion = openai.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a Feng Shui expert specializing in bedroom designs."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=1200
            )
            logger.info(f"OpenAI API call successful on attempt {attempt+1}")
            return completion.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API call failed on attempt {attempt+1}: {str(e)}")
            if attempt < retries - 1:
                time.sleep(2)  # 重试前暂停
            else:
                logger.error(f"All {retries} attempts failed")
                return None

# 生成分析提示
def generate_analysis_prompt(layout_description, user_info, is_paid=False, format_type="structured"):
    # 从知识库获取专业知识
    feng_shui_knowledge = extract_knowledge_for_prompt()
    
    # 基础提示
    base_prompt = f"""
As a professional Feng Shui consultant specializing in bedrooms, please analyze this bedroom layout and provide advice:

Bedroom Layout: {layout_description}

User Information:
- Birth Year: {user_info.get('birthYear', 'Not specified')}
- Gender: {user_info.get('gender', 'Not specified')}
- Main Concerns: {user_info.get('concerns', 'General wellness and sleep quality')}

{feng_shui_knowledge}
"""
    
    # 添加格式要求
    if format_type == "structured":
        format_instructions = """
Please organize your analysis into these four sections with their respective headings:

STRENGTHS: 
List the positive aspects and elements that follow good Feng Shui principles in the bedroom.

WEAKNESSES: 
Point out problems and elements that don't follow good Feng Shui principles.

IMPROVEMENT RECOMMENDATIONS: 
Provide 3-5 specific suggestions for improvement, preferably in a list format.

ADDITIONAL CONSIDERATIONS: 
Offer more personalized advice based on the user's specific situation.
"""
    else:
        format_instructions = """
Please first highlight the positive aspects of the bedroom layout, then identify any issues, and finally provide specific recommendations for improvement.
"""
    
    # 付费用户获得更详细的分析
    if is_paid:
        detail_level = """
Please provide a detailed analysis and recommendations, including:
- Whether the bed position and orientation are appropriate
- If the relationship between doors, windows and the bed follows Feng Shui principles
- Whether mirrors and electronic devices are properly placed
- If energy flows smoothly through the space
- An analysis of elemental balance in the bedroom based on Five Elements theory
- Personalized improvement suggestions
"""
    else:
        detail_level = """
Please provide a basic analysis, but for the detailed solutions and personalized advice sections, only give a brief overview without specific implementation steps.
"""
    
    full_prompt = base_prompt + format_instructions + detail_level
    return full_prompt

# 保存请求日志
def log_request(api_key, user_id, request_data, response_data, is_successful):
    client_name = API_KEYS.get(api_key, "Unknown client")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    log_entry = {
        "timestamp": timestamp,
        "client": client_name,
        "user_id": user_id,
        "success": is_successful,
        "request_data": request_data,
        "response_data": response_data
    }
    
    # 这里可以连接数据库存储日志
    # 简单起见，这里只是打印到控制台
    logger.info(f"Request Log: {log_entry}")

# 路由：首页
@app.route('/')
def index():
    return "Feng Shui Analyzer API is running!"

# 路由：健康检查
@app.route('/health')
def health_check():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# 路由：分析风水
@app.route('/analyze', methods=['POST'])
@require_api_key
def analyze():
    global request_counter
    request_counter += 1
    session_id = generate_session_id()
    logger.info(f"New analysis request received. Session ID: {session_id}, Request #{request_counter}")
    
    # 获取请求数据
    try:
        data = request.json
        if not data:
            return jsonify({"success": False, "message": "No data provided"}), 400
            
        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)
        user_id = data.get('userId', 0)
        format_type = data.get('format', 'freeform')  # 默认为自由格式
        
        logger.info(f"Analysis request for user ID: {user_id}, Paid status: {is_paid}")
        
        # 检查是否有床
        has_bed = False
        for position in grid_data.values():
            if isinstance(position, list) and 'bed' in position:
                has_bed = True
                break
        
        if not has_bed:
            return jsonify({"success": False, "message": "No bed found in layout"}), 400
            
        # 格式化布局数据
        layout_description = format_layout_data(grid_data)
        logger.info(f"Formatted layout description: {layout_description}")
        
        # 生成分析提示
        prompt = generate_analysis_prompt(layout_description, user_info, is_paid, format_type)
        
        # 调用OpenAI API或使用备用回答
        if OPENAI_API_KEY:
            analysis = analyze_feng_shui(prompt)
            if not analysis:
                logger.warning("OpenAI analysis failed, using backup analysis")
                analysis = generate_backup_analysis(is_paid, format_type)
        else:
            logger.warning("No OpenAI API key, using backup analysis")
            analysis = generate_backup_analysis(is_paid, format_type)
        
        response = {
            "success": True,
            "sessionId": session_id,
            "analysis": analysis,
            "isPaid": is_paid
        }
        
        # 记录成功的请求
        log_request(
            api_key=request.headers.get('X-API-Key'),
            user_id=user_id,
            request_data={"grid": "data omitted", "user_info": user_info},
            response_data={"session_id": session_id, "analysis_length": len(analysis)},
            is_successful=True
        )
        
        return jsonify(response)
        
    except Exception as e:
        error_details = traceback.format_exc()
        logger.error(f"Error processing request: {str(e)}\n{error_details}")
        
        # 记录失败的请求
        try:
            log_request(
                api_key=request.headers.get('X-API-Key'),
                user_id=data.get('userId', 0) if 'data' in locals() else 0,
                request_data={"error": "could not parse"},
                response_data={"error": str(e)},
                is_successful=False
            )
        except:
            logger.error("Error logging failed request")
        
        return jsonify({
            "success": False,
            "message": "An error occurred while processing your request",
            "error": str(e)
        }), 500

# 生成备用分析
def generate_backup_analysis(is_paid=False, format_type="structured"):
    # 根据是否付费和格式类型，生成相应的备用分析
    if format_type == "structured":
        # 结构化的四部分格式
        strengths = "Your bedroom layout follows basic Feng Shui principles. The bed position allows you to feel secure and supported, not directly in line with doors or windows. The overall energy flow in the room is conducive to good sleep and restoration."
        
        weaknesses = "The mirror directly facing the bed may cause sleep disturbances. Too many electronic devices create unfavorable electromagnetic fields and disrupt energy flow. The bed headboard is not against a solid wall, which reduces support and security. Some furniture pieces block the smooth flow of chi energy, potentially causing energy stagnation."
        
        recommendations = "- Adjust mirror placement to avoid direct reflection of the bed\n- Remove or reduce electronic devices in the bedroom\n- Ensure the bed headboard is placed against a solid wall for stability\n- Rearrange furniture to allow smooth energy flow\n- Add metal elements in the northwest area to balance the room's energy"
        
        considerations = "Based on your birth year, you may particularly benefit from enhancing the southeast area of your bedroom. Consider placing some energetically positive objects like crystals or green plants in this area. Bedroom colors in neutral warm tones are recommended to promote relaxation."
        
        if not is_paid:
            # 非付费用户只显示部分内容
            weaknesses = weaknesses.split('.')[0] + "."
            recommendations = "- Adjust mirror placement to avoid direct reflection of the bed"
            considerations = "Upgrade to the premium version for more personalized recommendations."
        
        return f"STRENGTHS:\n{strengths}\n\nWEAKNESSES:\n{weaknesses}\n\nIMPROVEMENT RECOMMENDATIONS:\n{recommendations}\n\nADDITIONAL CONSIDERATIONS:\n{considerations}"
    else:
        # 自由格式
        if is_paid:
            return """
Your bedroom layout generally follows good Feng Shui principles. The bed position allows you to feel secure and supported. The energy flow in the room is generally conducive to good sleep.

However, I've noticed several areas that need improvement:

1. The mirror directly facing the bed may cause sleep disturbances; consider repositioning or covering it at night
2. Too many electronic devices in the bedroom create unfavorable electromagnetic fields and should be removed
3. The bed headboard is not against a solid wall, which reduces support and security
4. Some furniture pieces block the smooth flow of chi energy, potentially causing energy stagnation

Recommended improvements:
- Adjust mirror placement to avoid direct reflection of the bed
- Remove or reduce electronic devices in the bedroom
- Ensure the bed headboard is placed against a solid wall for stability
- Rearrange furniture to allow smooth energy flow
- Add metal elements in the northwest area to balance the room's energy

Based on your birth year, you may particularly benefit from enhancing the southeast area of your bedroom. Consider placing some energetically positive objects like crystals or green plants in this area.
"""
        else:
            return """
Your bedroom layout generally follows good Feng Shui principles. The bed position allows you to feel secure and supported. The energy flow in the room is generally conducive to good sleep.

However, I've noticed that the mirror directly facing the bed may cause sleep disturbances, which is a key issue to address.

A simple improvement would be to adjust the mirror placement or cover it at night.

Upgrade to the premium version for more detailed analysis and personalized recommendations.
"""

# 启动服务器
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
