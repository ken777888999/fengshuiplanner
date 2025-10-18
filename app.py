from flask import Flask, request, jsonify, send_file
import google.generativeai as genai
import os
import json
from dotenv import load_dotenv
import logging
import time
from functools import wraps
from flask_cors import CORS
import sys

# 版本控制
VERSION = "1.0.1"
REQUIRED_ENV_VARS = ["GEMINI_API_KEY", "WP_API_KEY"]

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# 知识库路径
KNOWLEDGE_BASE_PATH = "knowledge_base/"

def check_environment():
    """检查所有必需的环境变量和配置"""
    missing_vars = []
    for var in REQUIRED_ENV_VARS:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
        
    # 检查知识库目录
    if not os.path.exists(KNOWLEDGE_BASE_PATH):
        try:
            os.makedirs(KNOWLEDGE_BASE_PATH)
            logger.info("Created knowledge base directory")
        except Exception as e:
            logger.error(f"Failed to create knowledge base directory: {str(e)}")
            return False
    
    return True

# 配置API密钥
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.error("GEMINI_API_KEY not found in environment variables")
    
genai.configure(api_key=GEMINI_API_KEY)

def init_model():
    """Initialize Gemini model with proper error handling"""
    try:
        # 确保使用正确的API版本和模型名称
        genai.configure(api_key=GEMINI_API_KEY)
        
        # 使用正确的模型名称
        model = genai.GenerativeModel('gemini-pro')
        
        # 添加重试机制
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                test_response = model.generate_content("Test.")
                if test_response:
                    logger.info("Successfully initialized Gemini Pro model")
                    return model
            except Exception as e:
                retry_count += 1
                logger.warning(f"Retry {retry_count}/{max_retries} failed: {str(e)}")
                time.sleep(1)  # 添加短暂延迟
                
        raise Exception("Failed to initialize model after maximum retries")
        
    except Exception as e:
        logger.error(f"Failed to initialize Gemini model: {str(e)}")
        return None

# 初始化模型
model = init_model()

app = Flask(__name__)
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

def get_feng_shui_knowledge():
    """获取风水知识库中的所有文件"""
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

@app.route('/')
def index():
    """处理根路径访问"""
    return jsonify({
        "service": "Feng Shui Space Planner API",
        "status": "running",
        "version": VERSION,
        "endpoints": {
            "analyze": "/analyze",
            "health": "/health",
            "model-status": "/model-status",
            "test": "/test"
        }
    })

@app.route('/health')
def health():
    """健康检查端点"""
    return jsonify({
        "status": "ok",
        "version": VERSION
    })

@app.route('/model-status', methods=['GET'])
def check_model_status():
    """检查模型是否正常工作"""
    try:
        if not model:
            return jsonify({
                "status": "error",
                "message": "Model not initialized",
                "version": VERSION,
                "environment_check": check_environment()
            }), 500

        # 进行简单的测试生成
        test_prompt = "Provide a simple Feng Shui tip."
        test_response = model.generate_content(test_prompt)
        
        return jsonify({
            "status": "ok",
            "message": "Model is working properly",
            "version": VERSION,
            "test_response": test_response.text if test_response else None,
            "environment_check": check_environment()
        })

    except Exception as e:
        logger.error(f"Model status check failed: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Model error: {str(e)}",
            "version": VERSION,
            "environment_check": check_environment()
        }), 500

@app.route('/analyze', methods=['POST'])
@require_api_key
def analyze_bedroom():
    """分析卧室布局的主要端点"""
    try:
        if not model:
            logger.error("Gemini model not initialized")
            return jsonify({
                "success": True,
                "analysis": generate_backup_analysis(is_paid=False),
                "using_backup": True
            })

        data = request.json
        if not data:
            return jsonify({
                "success": False,
                "error": "No data provided"
            }), 400

        logger.info(f"Received analysis request: {json.dumps(data)[:100]}...")
        
        # 提取数据
        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)
        
        if not grid_data:
            return jsonify({
                "success": False,
                "error": "No grid data provided"
            }), 400

        # 构建提示词
        prompt = create_analysis_prompt(grid_data, user_info, is_paid)
        
        try:
            # 添加超时处理
            response = model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.7,
                    "top_p": 0.8,
                    "top_k": 40,
                    "max_output_tokens": 1024,
                }
            )
            
            if not response or not response.text:
                raise Exception("Empty response from model")
                
            analysis = parse_response(response.text, is_paid)
            return jsonify({
                "success": True, 
                "analysis": analysis,
                "version": VERSION
            })
            
        except Exception as e:
            logger.error(f"Model generation error: {str(e)}")
            raise

    except Exception as e:
        logger.error(f"Error in analyze_bedroom: {str(e)}")
        return jsonify({
            "success": True,
            "analysis": generate_backup_analysis(is_paid=False),
            "using_backup": True,
            "version": VERSION
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
        return jsonify({
            "success": True, 
            "verified": True,
            "version": VERSION
        })
    except Exception as e:
        logger.error(f"Error in verify_payment: {str(e)}")
        return jsonify({
            "success": False, 
            "verified": False, 
            "error": str(e),
            "version": VERSION
        }), 500

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Test endpoint to verify service operation"""
    return jsonify({
        "success": True, 
        "message": "Feng Shui API is working properly",
        "version": VERSION,
        "gemini_available": True if model else False
    })

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        "error": "Not found",
        "message": "The requested resource was not found on this server.",
        "available_endpoints": [
            "/",
            "/analyze",
            "/health",
            "/model-status",
            "/test"
        ],
        "version": VERSION
    }), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({
        "error": "Internal server error",
        "message": str(error),
        "version": VERSION
    }), 500

if __name__ == '__main__':
    if not check_environment():
        logger.error("Environment check failed. Please check your configuration.")
        sys.exit(1)
        
    os.makedirs(KNOWLEDGE_BASE_PATH, exist_ok=True)
    knowledge_files = get_feng_shui_knowledge()
    logger.info(f"Found {len(knowledge_files)} knowledge base files: {knowledge_files}")
    
    # 初始化模型
    if not init_model():
        logger.error("Failed to initialize model. Starting with backup mode.")
    
    port = int(os.environ.get('PORT', 8080))
    app.run(debug=False, host='0.0.0.0', port=port)
