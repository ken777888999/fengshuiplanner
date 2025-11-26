# 导入部分修改 - 位于文件顶部
import os
import time
import logging
# 替换 import google.generativeai as genai
import cohere
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from functools import wraps
from knowledge_base_handler import extract_knowledge_for_prompt

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('app')

# 获取环境变量 - 修改环境变量名
# GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
COHERE_API_KEY = os.getenv('COHERE_API_KEY', 'xeJWwYbXgmFnKDmaAHvtkcmHo2jknduhR8FPG1Dm')
APP_API_KEY = os.getenv('APP_API_KEY')  # 用于API认证

# 初始化Flask应用
app = Flask(__name__)
CORS(app)  # 启用CORS

# API密钥验证装饰器 - 无需修改
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key or api_key != APP_API_KEY:
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# 完全替换init_model函数
def init_model():
    """Initialize Cohere model with error handling"""
    try:
        # 检查API密钥
        if not COHERE_API_KEY:
            logger.error("COHERE_API_KEY not properly set")
            return None
            
        # 初始化Cohere客户端
        logger.info("Initializing Cohere client")
        co = cohere.Client(COHERE_API_KEY)
        
        # 测试连接
        try:
            logger.info("Testing Cohere connection...")
            # 简单测试调用
            response = co.chat(message="Test connection")
            logger.info(f"Cohere connection successful: {response.text[:20]}...")
            return co
        except Exception as e:
            logger.error(f"Cohere connection test failed: {str(e)}")
            return None
                
    except Exception as e:
        logger.error(f"Failed to initialize Cohere client: {str(e)}")
        return None

# 初始化模型 - 变量名修改
cohere_client = init_model()

# 替换风水分析函数
def analyze_fengshui(grid_data, user_info, is_paid=False):
    """风水分析逻辑"""
    try:
        if not cohere_client:
            return {
                "error": "Cohere model not available",
                "fallback_response": "Service temporarily unavailable"
            }, 503

        # 构建提示词
        room_description = ""
        for position, items in grid_data.items():
            if isinstance(items, list):  # 确保items是列表
                room_description += f"Position {position}: {', '.join(items)}. "
            elif items and not isinstance(items, dict):  # 如果是简单类型而非字典
                room_description += f"Position {position}: {items}. "

        concerns = user_info.get('concerns', 'general feng shui')
        
        # 从知识库获取专业知识
        feng_shui_knowledge = extract_knowledge_for_prompt()
        
        # 根据是否付费用户提供不同深度的分析
        depth = "detailed" if is_paid else "basic"
        
        # 提示词结构
        prompt = f"""
        As a Feng Shui expert, analyze this room arrangement:
        {room_description}
        
        User's specific concerns: {concerns}
        
        {feng_shui_knowledge}
        
        Provide a {depth} Feng Shui analysis formatted in these four sections with their respective headings:
        
        ## Positive Aspects
        List the positive aspects and elements that follow good Feng Shui principles in the bedroom.
        
        ## Areas for Improvement
        Point out problems and elements that don't follow good Feng Shui principles.
        
        ## Recommended Changes
        Provide 3-5 specific suggestions for improvement, preferably in a list format.
        
        ## Additional Considerations
        Offer more personalized advice based on the user's specific situation.
        
        {' Include advanced remedies and specific timing recommendations in your analysis.' if is_paid else 'For the non-paid version, keep the analysis brief but insightful. Add a final section about upgrading to premium.'}
        
        ## Upgrade to Premium Analysis
        {'' if is_paid else 'Get the complete Feng Shui analysis including:\n- All identified issues in your bedroom layout\n- Three specific improvement recommendations\n- Detailed explanations of traditional Feng Shui principles\n\nPurchase the premium report to transform your bedroom into a harmonious sanctuary!'}
        """

        # 生成分析
        response = cohere_client.chat(
            message=prompt,
            model="command" if is_paid else "command-light",
            temperature=0.7,
            max_tokens=1000 if is_paid else 500
        )

        return {
            "success": True,
            "analysis": response.text,
            "type": "detailed" if is_paid else "basic"
        }

    except Exception as e:
        logger.error(f"Feng Shui analysis error: {str(e)}")
        return {
            "error": f"Analysis failed: {str(e)}",
            "fallback_response": "Unable to complete analysis. Please try again."
        }, 500

# 修改API信息端点
@app.route('/api-info', methods=['GET'])
@require_api_key
def api_info():
    """提供API版本和可用模型的信息"""
    try:
        info = {
            "api": "Cohere API Service",
            "available_models": ["command", "command-light", "command-r", "command-r-plus"]
        }
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 修改生成文本端点
@app.route('/generate', methods=['POST'])
@require_api_key
def generate_text():
    """使用Cohere模型生成文本"""
    try:
        data = request.json
        
        # 验证输入
        if not data or not data.get('prompt'):
            return jsonify({"error": "Missing prompt in request"}), 400
            
        prompt = data.get('prompt')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 800))
        
        # 检查模型是否可用
        if not cohere_client:
            return jsonify({
                "error": "Cohere model not available",
                "fallback_response": "Cohere API is currently unavailable. Please try again later."
            }), 503
            
        # 生成文本
        try:
            response = cohere_client.chat(
                message=prompt,
                model="command",
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # 返回结果
            return jsonify({
                "success": True,
                "generated_text": response.text,
                "model_used": "Cohere command"
            })
        except Exception as e:
            logger.error(f"Text generation error: {str(e)}")
            return jsonify({
                "error": f"Text generation failed: {str(e)}",
                "fallback_response": "Failed to generate text with Cohere. Please try a different prompt."
            }), 500
            
    except Exception as e:
        logger.error(f"Request processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 风水分析端点 - 无需修改
# 健康检查端点 - 需修改
@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    status = {
        "status": "ok",
        "cohere_model_available": cohere_client is not None,
        "timestamp": time.time(),
        "api_key_configured": bool(COHERE_API_KEY)
    }
    return jsonify(status)

# 重新初始化模型端点 - 需修改
@app.route('/reinitialize', methods=['POST'])
@require_api_key
def reinitialize_model():
    """重新初始化模型"""
    try:
        global cohere_client
        cohere_client = init_model()
        
        if cohere_client:
            return jsonify({
                "success": True,
                "message": "Model reinitialized successfully",
                "model_used": "Cohere API"
            })
        else:
            return jsonify({
                "success": False,
                "message": "Model reinitialization failed"
            }), 500
    except Exception as e:
        logger.error(f"Reinitialization error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 主页面 - 更新API信息
@app.route('/', methods=['GET'])
def index():
    """API主页"""
    return jsonify({
        "api": "Cohere API Service for Feng Shui Analysis",
        "version": "1.0",
        "endpoints": {
            "/analyze-fengshui": "Analyze Feng Shui arrangement (POST)",
            "/generate": "Generate text with Cohere (POST)",
            "/api-info": "Get API and model information (GET)",
            "/health": "Health check (GET)",
            "/reinitialize": "Reinitialize model (POST)",
            "/fengshui-positions": "Get Feng Shui position information (GET)"
        }
    })

# 错误处理 - 无需修改
