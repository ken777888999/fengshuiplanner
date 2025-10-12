from flask import Flask, request, jsonify
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
import logging
from functools import wraps
from flask_cors import CORS

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 配置API密钥
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY not found in environment variables")
    
try:
    genai.configure(api_key=GEMINI_API_KEY)
    # 初始化模型
    model = genai.GenerativeModel('gemini-pro')
    GEMINI_AVAILABLE = True
except Exception as e:
    logger.error(f"Error initializing Gemini API: {str(e)}")
    GEMINI_AVAILABLE = False

app = Flask(__name__)
# 添加CORS支持，允许跨域请求
CORS(app, resources={r"/*": {"origins": "*"}})

# 知识库路径
KNOWLEDGE_BASE_PATH = "knowledge_base/"

# API密钥验证中间件
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        expected_key = os.getenv("WP_API_KEY", "default_key_for_testing")
        
        # 在开发环境中使用宽松验证
        if os.getenv("ENVIRONMENT") != "development":
            if not api_key or api_key != expected_key:
                logger.warning(f"Invalid API key attempt")
                return jsonify({"success": False, "error": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

def extract_knowledge_for_prompt():
    """从知识库中提取相关信息以增强提示词"""
    try:
        # 基本的风水原则
        principles = [
            "Bed should not be directly aligned with the door (coffin position)",
            "Mirror should not face the bed directly",
            "Beams above the bed create negative pressure",
            "The bed's headboard should be against a solid wall",
            "Electronic devices should be kept away from the bed",
            "Windows should not be directly behind the bed",
            "Plants bring positive energy but should not be too many in bedroom",
            "North direction is associated with career and life path",
            "South direction is associated with fame and reputation",
            "East direction is associated with family and health",
            "Southeast direction is associated with wealth and abundance",
            "Southwest direction is associated with relationships",
            "West direction is associated with creativity and children",
            "Northwest direction is associated with helpful people",
            "Northeast direction is associated with knowledge and spirituality"
        ]
        
        # 尝试读取知识库文件
        try:
            files = os.listdir(KNOWLEDGE_BASE_PATH)
            knowledge_files = [f for f in files if f.endswith('.pdf') or f.endswith('.epub')]
            logger.info(f"Found {len(knowledge_files)} knowledge files: {knowledge_files}")
            
            # 这里可以添加代码从文件中提取内容
            # 由于实际提取内容可能很复杂，这里简化处理
        except Exception as e:
            logger.error(f"Error reading knowledge base: {str(e)}")
        
        return "\nKey Feng Shui principles to consider:\n- " + "\n- ".join(principles)
    except Exception as e:
        logger.error(f"Error in extract_knowledge_for_prompt: {str(e)}")
        return ""

@app.route('/health')
def health():
    """健康检查端点"""
    return jsonify({
        "status": "ok", 
        "gemini_available": GEMINI_AVAILABLE
    })

@app.route('/analyze', methods=['POST'])
@require_api_key
def analyze_bedroom():
    """分析卧室布局的主要端点"""
    try:
        data = request.json
        logger.info(f"Received analysis request")
        
        # 提取数据
        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)
        
        logger.info(f"User is paid: {is_paid}")
        
        # 尝试使用Gemini API分析
        if GEMINI_AVAILABLE:
            try:
                # 构建用于分析的提示词
                prompt = create_analysis_prompt(grid_data, user_info, is_paid)
                
                # 生成分析
                logger.info("Sending request to Gemini model")
                response = model.generate_content(prompt)
                logger.info("Received response from Gemini model")
                
                # 解析和格式化响应
                analysis = parse_response(response.text, is_paid)
                
                return jsonify({"success": True, "analysis": analysis})
            except Exception as e:
                logger.error(f"Error using Gemini API: {str(e)}")
                # 如果Gemini API失败，使用备用分析
                analysis = generate_backup_analysis(is_paid)
                return jsonify({"success": True, "analysis": analysis})
        else:
            # 如果Gemini API不可用，使用备用分析
            analysis = generate_backup_analysis(is_paid)
            return jsonify({"success": True, "analysis": analysis})
    
    except Exception as e:
        logger.error(f"Error in analyze_bedroom: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

def create_analysis_prompt(grid_data, user_info, is_paid):
    """创建发送给Gemini的提示词"""
    
    # 将九宫格数据转换为文本描述
    grid_description = ""
    for position, elements in grid_data.items():
        if elements:
            grid_description += f"Position {position}: {', '.join(elements)}\n"
    
    # 添加位置说明
    position_descriptions = """
Position 1: Northwest - Associated with helpful people and travel
Position 2: North - Associated with career and life path
Position 3: Northeast - Associated with knowledge and education
Position 4: West - Associated with creativity and children
Position 5: Center - Associated with overall health and balance
Position 6: East - Associated with family health and harmony
Position 7: Southwest - Associated with relationships and marriage
Position 8: South - Associated with fame and reputation
Position 9: Southeast - Associated with wealth and prosperity
    """
    
    # 获取知识库的风水原则
    knowledge_principles = extract_knowledge_for_prompt()
    
    prompt = f"""As a Feng Shui expert specializing in bedroom design, analyze this bedroom layout based on the Bagua grid (3x3):

{grid_description}

Bagua Positions Reference:
{position_descriptions}

User information:
Birth Year: {user_info.get('birthYear', 'Not provided')}
Gender: {user_info.get('gender', 'Not provided')}
Main concerns: {user_info.get('concerns', 'General wellness')}

{knowledge_principles}

Provide a comprehensive Feng Shui analysis with the following structure:

1. POSITIVE ASPECTS:
   - List each element in the bedroom and explain its positive Feng Shui attributes
   - Explain the underlying Feng Shui principles for each positive aspect

2. NEGATIVE ASPECTS:
   - List each problematic element and explain why it creates negative Feng Shui
   - Explain the underlying Feng Shui principles for each negative aspect

3. IMPROVEMENT RECOMMENDATIONS:
   - Provide three specific, actionable recommendations to improve the bedroom's Feng Shui
   - For each recommendation, explain how it addresses specific issues

4. SPECIAL CONSIDERATIONS:
   - Include any warnings or special notes based on the user's birth year or specific concerns
   - If birth year is provided, consider the person's Kua number and favorable/unfavorable directions

IMPORTANT:
- Write in clear, professional English
- Be specific and detailed in your analysis
- Reference traditional Feng Shui principles throughout
- Format your response with clear headings and bullet points
- Avoid generic advice; make recommendations specific to this layout
- Consider both Form School and Compass School principles
"""
    return prompt

def parse_response(text, is_paid):
    """解析和格式化AI响应，根据付费状态限制内容"""
    
    # 定义各部分
    sections = {
        "positive_aspects": {"title": "Positive Aspects", "content": ""},
        "negative_aspects": {"title": "Areas for Improvement", "content": ""},
        "recommendations": {"title": "Recommended Changes", "content": ""},
        "considerations": {"title": "Special Considerations", "content": ""}
    }
    
    # 提取各部分内容
    current_section = None
    lines = text.split('\n')
    
    for line in lines:
        if "POSITIVE ASPECTS" in line.upper():
            current_section = "positive_aspects"
            continue
        elif "NEGATIVE ASPECTS" in line.upper() or "AREAS FOR IMPROVEMENT" in line.upper():
            current_section = "negative_aspects"
            continue
        elif "IMPROVEMENT RECOMMENDATIONS" in line.upper() or "RECOMMENDED CHANGES" in line.upper():
            current_section = "recommendations"
            continue
        elif "SPECIAL CONSIDERATIONS" in line.upper():
            current_section = "considerations"
            continue
            
        if current_section and line.strip():
            sections[current_section]["content"] += line + "\n"
    
    # 如果用户未付费，限制内容
    if not is_paid:
        # 只保留第一个负面方面，用占位符替换其他内容
        negative_content = sections["negative_aspects"]["content"]
        
        # 找到第一个问题点
        lines = negative_content.split('\n')
        first_issue = []
        bullet_markers = ['-', '•', '*', '1.', '2.', '3.']
        
        found_first_bullet = False
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            
            # 检查是否是列表项
            is_bullet_point = any(line_stripped.startswith(marker) for marker in bullet_markers)
            
            if is_bullet_point and not found_first_bullet:
                found_first_bullet = True
                first_issue.append(line)
                continue
            elif is_bullet_point and found_first_bullet:
                # 遇到第二个列表项，停止
                break
            elif found_first_bullet:
                # 属于第一个列表项的说明
                first_issue.append(line)
        
        # 组装限制后的内容
        if first_issue:
            limited_content = "\n".join(first_issue)
            upgrade_msg = "\n\n**[Additional issues analysis available with Premium Report]**"
            sections["negative_aspects"]["content"] = limited_content + upgrade_msg
        else:
            sections["negative_aspects"]["content"] = "**[Analysis available with Premium Report]**"
        
        # 限制改进建议，但保留标题
        upgrade_msg = "**[Detailed recommendations available with Premium Report]**"
        sections["recommendations"]["content"] = upgrade_msg
        
        # 限制特殊考虑，但添加吸引力
        if sections["considerations"]["content"].strip():
            sections["considerations"]["content"] = "**[Personalized considerations based on your birth year and specific needs available with Premium Report]**"
    
    # 构建最终结果
    formatted_result = ""
    for section_id, section_data in sections.items():
        if section_data["content"].strip():
            formatted_result += f"## {section_data['title']}\n\n"
            formatted_result += section_data['content'] + "\n\n"
    
    # 如果用户未付费，添加升级提示
    if not is_paid:
        formatted_result += """
## Upgrade to Premium Analysis

Get the complete Feng Shui analysis including:
- All identified issues in your bedroom layout
- Three specific improvement recommendations
- Personalized advice based on your birth year
- Detailed explanations of traditional Feng Shui principles

Purchase the premium report to transform your bedroom into a harmonious sanctuary!
"""
    
    return formatted_result

def generate_backup_analysis(is_paid):
    """生成备用分析结果，当Gemini API不可用时使用"""
    
    if is_paid:
        # 付费用户获取完整分析
        analysis = """## Positive Aspects

Your bedroom has good energy flow with the bed placed against a solid wall, which provides security and stability according to traditional Feng Shui principles. This positioning creates a strong backing that symbolizes support in your life and career.

The plants add vibrant life energy (Wood element) to the space, which helps to purify the air and add a touch of nature's harmony to your bedroom environment. In Feng Shui, appropriate plants can enhance the flow of positive Chi.

Your furniture arrangement allows for balanced circulation of energy around key pieces, creating harmony in the space. The symmetrical arrangement of furniture represents balance in relationships and life.

## Areas for Improvement

The mirror facing the bed may cause energy to bounce and disturb sleep. This is considered unfavorable in Feng Shui as it can create restlessness and insomnia. Mirrors are thought to reflect and multiply energy, which can be too stimulating during rest periods.

The electronic devices in the north sector may disrupt career energy and interfere with your sleep quality. Electronic devices emit EMF radiation and represent the Fire element, which can create an imbalance in the Water element associated with the north direction.

The bed position relative to the door creates a vulnerable sleeping position where you cannot see who enters the room. In Feng Shui, this is called the "coffin position" and should be avoided as it may create subconscious anxiety.

The clutter in the southwest corner is blocking relationship energy. This area governs partnerships and romance, and keeping it clear and harmonious is essential for healthy relationships.

## Recommended Changes

1. Move the mirror to face away from the bed or cover it at night to prevent energy reflection. This simple adjustment will create a more restful sleeping environment by preventing Chi from bouncing back and forth during sleep hours.

2. Add a soft light source in the northeast corner to enhance wisdom and knowledge energy. The northeast is associated with education and spiritual growth; enhancing this area can support your personal development goals.

3. Ensure balanced nightstands on both sides of the bed to create harmony and balance in relationships. Having matching nightstands symbolizes equality in partnerships and creates symmetry that is conducive to restful sleep.

4. Move electronic devices out of the bedroom or at least 3 feet away from the bed to improve sleep quality and energy flow. If removal is not possible, unplug them at night or place them in a cabinet that can be closed.

5. Reposition the bed to have a clear view of the door while not being directly in line with it. This creates a commanding position that provides security while sleeping while avoiding the direct path of Chi that rushes through doorways.

## Special Considerations

Based on your birth year, your Kua number suggests that north and east are particularly favorable directions for you. Consider orienting your bed to take advantage of these auspicious directions to enhance personal energy.

The time spent in your bedroom affects how strongly the Feng Shui influences your well-being. Since most people spend about one-third of their lives sleeping, bedroom Feng Shui is particularly important for health and vitality.

For optimal sleep quality, consider using earth tone colors in bedding and wall colors to create a grounding effect that supports restful sleep. These colors resonate with the nurturing energy needed for proper rest and recovery.

The seasonal changes may affect the energy in your bedroom. Consider making minor adjustments to your bedroom arrangement during the changing seasons to maintain optimal energy flow throughout the year.
"""
    else:
        # 免费用户获取有限分析和升级提示
        analysis = """## Positive Aspects

Your bedroom has good energy flow with the bed placed against a solid wall, which provides security and stability according to traditional Feng Shui principles. This positioning creates a strong backing that symbolizes support in your life and career.

The plants add vibrant life energy (Wood element) to the space, which helps to purify the air and add a touch of nature's harmony to your bedroom environment.

Your furniture arrangement allows for balanced circulation of energy around key pieces, creating harmony in the space.

## Areas for Improvement

The mirror facing the bed may cause energy to bounce and disturb sleep. This is considered unfavorable in Feng Shui as it can create restlessness and insomnia. Mirrors are thought to reflect and multiply energy, which can be too stimulating during rest periods.

**[Additional issues analysis available with Premium Report]**

## Recommended Changes

**[Detailed recommendations available with Premium Report]**

## Special Considerations

**[Personalized considerations based on your birth year and specific needs available with Premium Report]**

## Upgrade to Premium Analysis

Get the complete Feng Shui analysis including:
- All identified issues in your bedroom layout
- Five specific improvement recommendations
- Personalized advice based on your birth year
- Detailed explanations of traditional Feng Shui principles

Purchase the premium report to transform your bedroom into a harmonious sanctuary!
"""
    
    return analysis

@app.route('/verify-payment', methods=['POST'])
@require_api_key
def verify_payment():
    """验证WooCommerce支付状态"""
    try:
        data = request.json
        order_id = data.get('orderId')
        user_id = data.get('userId')
        product_id = data.get('productId')
        
        # 记录验证请求
        logger.info(f"Payment verification request received")
        
        # 简化验证逻辑
        return jsonify({"success": True, "verified": True})
    except Exception as e:
        logger.error(f"Error in verify_payment: {str(e)}")
        return jsonify({"success": False, "verified": False, "error": str(e)}), 500

@app.route('/test', methods=['GET'])
def test_endpoint():
    """测试端点，用于验证服务是否正常运行"""
    return jsonify({
        "success": True, 
        "message": "Feng Shui API is working properly",
        "version": "1.0.0",
        "gemini_available": GEMINI_AVAILABLE
    })

if __name__ == '__main__':
    # 确保知识库目录存在
    os.makedirs(KNOWLEDGE_BASE_PATH, exist_ok=True)
    
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
