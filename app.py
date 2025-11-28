import os
import time
import logging
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

# 获取环境变量
COHERE_API_KEY = os.getenv('COHERE_API_KEY', 'xeJWwYbXgmFnKDmaAHvtkcmHo2jknduhR8FPG1Dm')
WP_API_KEY = os.getenv('WP_API_KEY')  # 修改为WP_API_KEY

# 初始化Flask应用
app = Flask(__name__)
# 更具体的CORS配置
CORS(app, resources={r"/*": {"origins": "*"}})

# API密钥验证装饰器
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key or api_key != WP_API_KEY:  # 修改为WP_API_KEY
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# 初始化Cohere模型
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

# 初始化模型
cohere_client = init_model()

# 风水分析函数
def analyze_fengshui(grid_data, user_info, is_paid=False):
    """风水分析逻辑"""
    try:
        if not cohere_client:
            return {
                "error": "Cohere model not available",
                "fallback_response": "Service temporarily unavailable"
            }, 503

        # 记录输入数据
        logger.info(f"Grid data: {grid_data}, User info: {user_info}, Is paid: {is_paid}")

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

        logger.info(f"Sending prompt to Cohere: {prompt[:100]}...")

        # 生成分析
        response = cohere_client.chat(
            message=prompt,
            model="command" if is_paid else "command-light",
            temperature=0.7,
            max_tokens=1000 if is_paid else 500
        )

        # 记录模型响应
        logger.info(f"Received response from Cohere: {response.text[:100]}...")

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

# 添加缺失的风水分析端点
@app.route('/analyze-fengshui', methods=['POST'])
@require_api_key
def analyze_feng_shui_endpoint():
    """风水分析端点"""
    try:
        data = request.json
        logger.info(f"Received analysis request: {data}")
        
        # 验证输入
        if not data:
            return jsonify({"error": "Missing request data"}), 400
            
        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)
        
        # 记录请求信息用于调试
        logger.info(f"Analyzing Feng Shui with: gridData={len(grid_data)} items, isPaid={is_paid}")
        
        # 调用分析函数
        result = analyze_fengshui(grid_data, user_info, is_paid)
        
        # 如果结果是元组，表示有错误发生
        if isinstance(result, tuple):
            return jsonify(result[0]), result[1]
            
        # 返回分析结果
        return jsonify(result)
            
    except Exception as e:
        logger.error(f"Feng Shui analysis endpoint error: {str(e)}")
        return jsonify({
            "error": f"Analysis request failed: {str(e)}",
            "fallback_response": "Unable to process your request. Please try again."
        }), 500

# API信息端点
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

# 文本生成端点
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

# 健康检查端点
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

# 重新初始化模型端点
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

# 获取风水位置信息端点
@app.route('/fengshui-positions', methods=['GET'])
@require_api_key
def feng_shui_positions():
    """返回九宫格位置的传统风水含义"""
    positions = {
        "1": {"name": "Northwest", "element": "Metal", "associations": "Helpful People, Travel"},
        "2": {"name": "North", "element": "Water", "associations": "Career, Life Path"},
        "3": {"name": "Northeast", "element": "Earth", "associations": "Knowledge, Wisdom"},
        "4": {"name": "West", "element": "Metal", "associations": "Children, Creativity"},
        "5": {"name": "Center", "element": "Earth", "associations": "Health, Balance"},
        "6": {"name": "East", "element": "Wood", "associations": "Family, Community"},
        "7": {"name": "Southwest", "element": "Earth", "associations": "Love, Marriage"},
        "8": {"name": "South", "element": "Fire", "associations": "Fame, Reputation"},
        "9": {"name": "Southeast", "element": "Wood", "associations": "Wealth, Prosperity"}
    }
    return jsonify(positions)

# 主页面
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

# 错误处理程序
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "Method not allowed"}), 405

@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal server error"}), 500

# 应用启动配置
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
