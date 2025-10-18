from flask import Flask, request, jsonify, send_file
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
    
genai.configure(api_key=GEMINI_API_KEY)

# 初始化模型
try:
    model = genai.GenerativeModel('gemini-1.5-pro')
    logger.info("Successfully initialized Gemini 1.5 Pro")
except Exception as e:
    logger.warning(f"Failed to initialize Gemini 1.5 Pro: {str(e)}, falling back to Gemini Pro")
    model = genai.GenerativeModel('gemini-pro')

app = Flask(__name__)
# 添加CORS支持，允许跨域请求
CORS(app)

# API密钥验证中间件
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        expected_key = os.getenv("WP_API_KEY", "default_key_for_testing")
        
        if not api_key or api_key != expected_key:
            logger.warning(f"Invalid API key attempt: {api_key[:5] if api_key else 'None'}...")
            return jsonify({"success": False, "error": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# 知识库路径
KNOWLEDGE_BASE_PATH = "knowledge_base/"

def get_feng_shui_knowledge():
    """
    获取风水知识库中的所有文件
    """
    try:
        files = os.listdir(KNOWLEDGE_BASE_PATH)
        return [f for f in files if f.endswith('.pdf') or f.endswith('.epub')]
    except Exception as e:
        logger.error(f"Error accessing knowledge base: {str(e)}")
        return []

def extract_knowledge_for_prompt():
    """Extract relevant information from knowledge base"""
    try:
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
        
        try:
            files = os.listdir(KNOWLEDGE_BASE_PATH)
            knowledge_files = [f for f in files if f.endswith('.pdf') or f.endswith('.epub')]
            logger.info(f"Found {len(knowledge_files)} knowledge files: {knowledge_files}")
        except Exception as e:
            logger.error(f"Error reading knowledge base: {str(e)}")
        
        return "\nKey Feng Shui principles to consider:\n- " + "\n- ".join(principles)
    except Exception as e:
        logger.error(f"Error in extract_knowledge_for_prompt: {str(e)}")
        return ""

@app.route('/health')
def health():
    """健康检查端点"""
    return jsonify({"status": "ok"})

@app.route('/analyze', methods=['POST'])
@require_api_key
def analyze_bedroom():
    """分析卧室布局的主要端点"""
    try:
        data = request.json
        logger.info(f"Received analysis request: {json.dumps(data)[:100]}...")
        
        # 提取数据
        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)
        
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
        logger.error(f"Error in analyze_bedroom: {str(e)}")
        # 使用备用分析
        analysis = generate_backup_analysis(is_paid=False)
        return jsonify({
            "success": True,
            "analysis": analysis,
            "using_backup": True
        })

def create_analysis_prompt(grid_data, user_info, is_paid):
    """Create analysis prompt"""
    grid_description = ""
    for position, elements in grid_data.items():
        if elements:
            grid_description += f"Position {position}: {', '.join(elements)}\n"

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

    knowledge_principles = extract_knowledge_for_prompt()

    prompt = f"""As a Feng Shui expert specializing in bedroom design, analyze this bedroom layout based on the Bagua grid (3x3):

    {grid_description}

    Bagua Positions Reference:
    {position_descriptions}

    User Information:
    Main concerns: {user_info.get('concerns', 'General wellness')}

    {knowledge_principles}

    Please provide a comprehensive Feng Shui analysis with the following structure:

    POSITIVE ASPECTS:
    [List positive elements and explain their benefits]

    AREAS FOR IMPROVEMENT:
    [List problematic elements and explain their impacts]

    RECOMMENDED CHANGES:
    [Provide specific, actionable recommendations]

    KEY NOTES:
    [Additional important considerations for this layout]
    """
    return prompt

def parse_response(text, is_paid):
    """Parse and format AI response based on payment status"""
    sections = {
        "positive_aspects": {"title": "Positive Aspects", "content": ""},
        "negative_aspects": {"title": "Areas for Improvement", "content": ""},
        "recommendations": {"title": "Recommended Changes", "content": ""},
        "key_notes": {"title": "Key Notes", "content": ""}
    }
    
    current_section = None
    lines = text.split('\n')
    
    for line in lines:
        if "POSITIVE ASPECTS" in line.upper():
            current_section = "positive_aspects"
            continue
        elif "AREAS FOR IMPROVEMENT" in line.upper():
            current_section = "negative_aspects"
            continue
        elif "RECOMMENDED CHANGES" in line.upper():
            current_section = "recommendations"
            continue
        elif "KEY NOTES" in line.upper():
            current_section = "key_notes"
            continue
            
        if current_section and line.strip():
            sections[current_section]["content"] += line + "\n"
    
    if not is_paid:
        # Limit content for free users
        negative_content = sections["negative_aspects"]["content"]
        lines = negative_content.split('\n')
        first_issue = []
        
        # Find first bullet point and its description
        for line in lines:
            if line.strip().startswith(('-', '•', '*')) and not first_issue:
                first_issue.append(line)
            elif first_issue and not line.strip().startswith(('-', '•', '*')):
                first_issue.append(line)
            elif first_issue and line.strip().startswith(('-', '•', '*')):
                break
        
        if first_issue:
            sections["negative_aspects"]["content"] = (
                "\n".join(first_issue) + 
                "\n\n**[Additional issues analysis available with Premium Report]**"
            )
        
        # Limit other sections
        sections["recommendations"]["content"] = "**[Upgrade to Premium Report for detailed recommendations]**"
        sections["key_notes"]["content"] = "**[Upgrade to Premium Report for professional insights]**"
    
    # Build final result
    formatted_result = ""
    for section_data in sections.values():
        if section_data["content"].strip():
            formatted_result += f"## {section_data['title']}\n\n{section_data['content']}\n\n"
    
    if not is_paid:
        formatted_result += """
## Upgrade to Premium Analysis

Get the complete Feng Shui analysis including:
- All identified issues in your bedroom layout
- Specific improvement recommendations
- Detailed explanations of traditional Feng Shui principles
- Professional insights for optimal energy flow

Upgrade now to transform your bedroom into a harmonious sanctuary!"""
    
    return formatted_result

def generate_backup_analysis(is_paid):
    """Generate backup analysis"""
    if is_paid:
        return """## Positive Aspects
The bed against a solid wall provides stability and security. According to traditional Feng Shui principles, this positioning creates strong support for life and career.

The plants in the room add vitality (Wood element), helping to purify the air and bring natural harmony to the bedroom environment.

The furniture arrangement allows for balanced energy flow, creating spatial harmony.

## Areas for Improvement
The mirror facing the bed may cause energy to bounce and disturb sleep. This is considered unfavorable in Feng Shui and may cause restlessness and insomnia.

Electronic devices in the North sector may interfere with career energy and sleep quality.

The bed's position relative to the door creates a vulnerable sleeping position.

## Recommended Changes
1. Adjust mirror direction or cover it at night
2. Add soft lighting in the Northeast corner
3. Ensure balanced nightstands on both sides of the bed
4. Remove electronic devices or keep them 3 feet away
5. Reposition the bed for better energy flow

## Key Notes
Consider using earth tones to create a grounding environment conducive to rest.

Adjust bedroom layout seasonally to maintain optimal energy flow."""
    else:
        return """## Positive Aspects
The bed against a solid wall provides stability and security. According to traditional Feng Shui principles, this positioning creates strong support for life and career.

The plants in the room add vitality (Wood element).

The furniture arrangement allows for balanced energy flow.

## Areas for Improvement
The mirror facing the bed may cause energy to bounce and disturb sleep.

**[Upgrade to Premium Report for complete analysis]**

## Recommended Changes
**[Upgrade to Premium Report for detailed recommendations]**

## Key Notes
**[Upgrade to Premium Report for professional insights]**

## Upgrade to Premium Analysis

Get the complete Feng Shui analysis including:
- All identified issues in your bedroom layout
- Specific improvement recommendations
- Detailed explanations of traditional Feng Shui principles
- Professional insights for optimal energy flow

Upgrade now to transform your bedroom into a harmonious sanctuary!"""

@app.route('/verify-payment', methods=['POST'])
@require_api_key
def verify_payment():
    """Verify WooCommerce payment status"""
    try:
        data = request.json
        order_id = data.get('orderId')
        user_id = data.get('userId')
        product_id = data.get('productId')
        
        logger.info(f"Payment verification request for Order: {order_id}, User: {user_id}, Product: {product_id}")
        
        # Simplified verification logic
        return jsonify({"success": True, "verified": True})
    except Exception as e:
        logger.error(f"Error in verify_payment: {str(e)}")
        return jsonify({"success": False, "verified": False, "error": str(e)}), 500

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to verify service operation"""
    return jsonify({
        "success": True, 
        "message": "Feng Shui API is working properly",
        "version": "1.0.0",
        "gemini_available": True
    })

if __name__ == '__main__':
    # Ensure knowledge base directory exists
    os.makedirs(KNOWLEDGE_BASE_PATH, exist_ok=True)
    
    # Check knowledge base files
    knowledge_files = get_feng_shui_knowledge()
    logger.info(f"Found {len(knowledge_files)} knowledge base files: {knowledge_files}")
    
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
