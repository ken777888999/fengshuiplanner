import os
import time
import logging
import google.generativeai as genai
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from functools import wraps

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('app')

# 获取环境变量
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
APP_API_KEY = os.getenv('APP_API_KEY')  # 用于API认证

# 初始化Flask应用
app = Flask(__name__)
CORS(app)  # 启用CORS

# API密钥验证装饰器
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key or api_key != APP_API_KEY:
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# 初始化Gemini模型
def init_model():
    """Initialize Gemini model with comprehensive error handling"""
    try:
        # 检查API密钥
        if not GEMINI_API_KEY or GEMINI_API_KEY == "your_api_key_here":
            logger.error("GEMINI_API_KEY not properly set")
            return None
            
        # 配置生成式AI
        logger.info("Configuring Google Generative AI")
        genai.configure(
            api_key=GEMINI_API_KEY,
            client_options={
                'api_endpoint': 'generativelanguage.googleapis.com'
            }
        )
        
        # 首先列出可用的模型进行调试
        try:
            logger.info("Attempting to list available models...")
            models = genai.list_models()
            available_models = [model.name for model in models]
            logger.info(f"Available models: {available_models}")
        except Exception as e:
            logger.warning(f"Could not list models: {str(e)}")
            available_models = []
        
        # 尝试不同的模型名称
        model_names = [
            'gemini-1.5-pro',
            'gemini-1.0-pro', 
            'gemini-pro',
            'models/gemini-pro'
        ]
        
        # 如果列出可用模型成功，优先尝试可用的模型
        if available_models:
            for available_model in available_models:
                if "gemini" in available_model.lower() and "pro" in available_model.lower():
                    try:
                        logger.info(f"Trying available model: {available_model}")
                        model_name = available_model.split("/")[-1] if "/" in available_model else available_model
                        model = genai.GenerativeModel(model_name)
                        # 测试连接
                        response = model.generate_content("Test connection")
                        if response and hasattr(response, 'text'):
                            logger.info(f"Successfully initialized available model: {model_name}")
                            return model
                    except Exception as e:
                        logger.warning(f"Available model {model_name} failed: {str(e)}")
                        continue
        
        # 如果可用模型没有成功，尝试常见模型名称
        for model_name in model_names:
            try:
                logger.info(f"Trying standard model name: {model_name}")
                model = genai.GenerativeModel(model_name)
                # 使用明确的配置测试连接
                response = model.generate_content(
                    "Test connection",
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.1,
                        max_output_tokens=10
                    )
                )
                if response and hasattr(response, 'text'):
                    logger.info(f"Successfully initialized model: {model_name}")
                    return model
            except Exception as e:
                logger.warning(f"Model {model_name} failed: {str(e)}")
                continue
                
        # 如果所有尝试都失败
        logger.error(f"All model attempts failed: {', '.join(model_names)}")
        return None
        
    except Exception as e:
        logger.error(f"Failed to initialize Gemini model: {str(e)}")
        return None

# 初始化模型
gemini_model = init_model()

# 风水分析函数
def analyze_fengshui(grid_data, user_info, is_paid=False):
    """风水分析逻辑"""
    try:
        if not gemini_model:
            return {
                "error": "Gemini model not available",
                "fallback_response": "Service temporarily unavailable"
            }, 503

        # 构建提示词
        room_description = ""
        for position, items in grid_data.items():
            if items:
                room_description += f"Position {position}: {', '.join(items)}. "

        concerns = user_info.get('concerns', 'general feng shui')
        
        # 根据是否付费用户提供不同深度的分析
        depth = "detailed" if is_paid else "basic"
        
        prompt = f"""
        As a Feng Shui expert, analyze this room arrangement:
        {room_description}
        
        User's specific concerns: {concerns}
        
        Provide a {depth} Feng Shui analysis focusing on:
        1. Overall energy flow
        2. Specific recommendations for improvement
        3. Potential issues to address
        
        {' Include advanced remedies and specific timing recommendations.' if is_paid else ''}
        """

        # 生成配置
        generation_config = genai.types.GenerationConfig(
            temperature=0.7,
            max_output_tokens=1000 if is_paid else 500,
            top_p=0.95,
            top_k=40
        )

        # 生成分析
        response = gemini_model.generate_content(
            prompt,
            generation_config=generation_config
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

# API信息端点
@app.route('/api-info', methods=['GET'])
@require_api_key
def api_info():
    """提供API版本和可用模型的信息"""
    try:
        info = {
            "library_version": genai.__version__,
            "available_models": []
        }
        
        try:
            models = genai.list_models()
            info["available_models"] = [
                {"name": m.name, "display_name": getattr(m, "display_name", "Unknown")}
                for m in models
            ]
        except Exception as e:
            info["models_error"] = str(e)
            
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 生成文本端点
@app.route('/generate', methods=['POST'])
@require_api_key
def generate_text():
    """使用Gemini模型生成文本"""
    try:
        data = request.json
        
        # 验证输入
        if not data or not data.get('prompt'):
            return jsonify({"error": "Missing prompt in request"}), 400
            
        prompt = data.get('prompt')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 800))
        
        # 检查模型是否可用
        if not gemini_model:
            return jsonify({
                "error": "Gemini model not available",
                "fallback_response": "Gemini API is currently unavailable. Please try again later."
            }), 503
            
        # 生成文本
        try:
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens,
                top_p=0.95,
                top_k=40
            )
            
            response = gemini_model.generate_content(
                prompt,
                generation_config=generation_config
            )
            
            # 返回结果
            return jsonify({
                "success": True,
                "generated_text": response.text,
                "model_used": gemini_model._model_name
            })
        except Exception as e:
            logger.error(f"Text generation error: {str(e)}")
            return jsonify({
                "error": f"Text generation failed: {str(e)}",
                "fallback_response": "Failed to generate text with Gemini. Please try a different prompt."
            }), 500
            
    except Exception as e:
        logger.error(f"Request processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 风水分析端点
@app.route('/analyze-fengshui', methods=['POST'])
@require_api_key
def fengshui_endpoint():
    """风水分析端点"""
    try:
        data = request.json
        
        # 验证输入
        if not data or 'gridData' not in data:
            return jsonify({"error": "Missing required data"}), 400

        grid_data = data.get('gridData', {})
        user_info = data.get('userInfo', {})
        is_paid = data.get('isPaid', False)

        # 验证网格数据格式
        if not isinstance(grid_data, dict):
            return jsonify({"error": "Invalid grid data format"}), 400

        # 执行分析
        result = analyze_fengshui(grid_data, user_info, is_paid)
        
        # 如果返回值是元组（包含错误状态码）
        if isinstance(result, tuple):
            return jsonify(result[0]), result[1]
            
        return jsonify(result)

    except Exception as e:
        logger.error(f"Feng Shui endpoint error: {str(e)}")
        return jsonify({
            "error": "Failed to process request",
            "message": str(e)
        }), 500

# 获取风水位置信息
@app.route('/fengshui-positions', methods=['GET'])
def get_fengshui_positions():
    """返回风水分析中可用的位置信息"""
    return jsonify({
        "positions": {
            "1": "North",
            "2": "Northeast",
            "3": "East",
            "4": "Southeast",
            "5": "South",
            "6": "Southwest",
            "7": "West",
            "8": "Northwest",
            "9": "Center"
        },
        "common_items": [
            "bed",
            "desk",
            "door",
            "window",
            "mirror",
            "plant",
            "cabinet",
            "chair",
            "electronics",
            "water_feature"
        ]
    })

# 健康检查端点
@app.route('/health', methods=['GET'])
def health_check():
    """健康检查端点"""
    status = {
        "status": "ok",
        "gemini_model_available": gemini_model is not None,
        "timestamp": time.time()
    }
    return jsonify(status)

# 重新初始化模型端点
@app.route('/reinitialize', methods=['POST'])
@require_api_key
def reinitialize_model():
    """重新初始化模型"""
    try:
        global gemini_model
        gemini_model = init_model()
        
        if gemini_model:
            return jsonify({
                "success": True,
                "message": "Model reinitialized successfully",
                "model_used": gemini_model._model_name
            })
        else:
            return jsonify({
                "success": False,
                "message": "Model reinitialization failed"
            }), 500
    except Exception as e:
        logger.error(f"Reinitialization error: {str(e)}")
        return jsonify({"error": str(e)}), 500

# 主页面
@app.route('/', methods=['GET'])
def index():
    """API主页"""
    return jsonify({
        "api": "Gemini API Service",
        "version": "1.0",
        "endpoints": {
            "/analyze-fengshui": "Analyze Feng Shui arrangement (POST)",
            "/generate": "Generate text with Gemini (POST)",
            "/api-info": "Get API and model information (GET)",
            "/health": "Health check (GET)",
            "/reinitialize": "Reinitialize model (POST)",
            "/fengshui-positions": "Get Feng Shui position information (GET)"
        }
    })

# 错误处理
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method not allowed"}), 405

@app.errorhandler(500)
def internal_error(e):
    return jsonify({"error": "Internal server error"}), 500

# 运行应用（仅在直接运行此文件时）
if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=(os.getenv('FLASK_ENV') == 'development'))
