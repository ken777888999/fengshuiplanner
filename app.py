import os
import time
import logging
import requests
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

# 获取环境变量 - 移除默认值，完全依赖环境变量
QWEN_API_KEY = os.getenv('QWEN_API_KEY')
WP_API_KEY = os.getenv('WP_API_KEY')

# 初始化Flask应用
app = Flask(__name__)
# 更新CORS配置，明确指定允许的源
CORS(app, origins=["https://fengshuispaceplanner.com"], supports_credentials=True)

# 额外的CORS处理
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', 'https://fengshuispaceplanner.com')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,X-API-Key')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

# API密钥验证装饰器
def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key or api_key != WP_API_KEY:  # 使用WP_API_KEY验证
            return jsonify({"error": "Invalid or missing API key"}), 401
        return f(*args, **kwargs)
    return decorated_function

# 通义千问API配置 - 北京地域
QWEN_API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# 定义通义千问API调用函数
def generate_with_qwen(prompt, max_tokens=1000, temperature=0.7, is_paid=False):
    """使用通义千问API生成内容"""
    try:
        if not QWEN_API_KEY:
            logger.error("QWEN_API_KEY not set")
            return None, "API key not configured"
        
        # 根据是否付费用户调整最大token数
        actual_max_tokens = max_tokens if is_paid else min(max_tokens, 800)
        
        # 构建请求数据 - 使用兼容模式格式
        payload = {
            "model": "qwen-plus-latest",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": actual_max_tokens,
            "temperature": temperature,
            "top_p": 0.8
        }
        
        # 设置请求头
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {QWEN_API_KEY}"
        }
        
        # 发送请求
        logger.info("Sending request to Qwen API")
        response = requests.post(QWEN_API_URL, json=payload, headers=headers)
        
        # 检查响应状态
        if response.status_code == 200:
            result = response.json()
            
            # 解析结果 - 兼容模式格式
            if "choices" in result and len(result["choices"]) > 0:
                message = result["choices"][0].get("message", {})
                generated_text = message.get("content", "")
                return generated_text, None
            else:
                logger.error(f"Unexpected response structure: {result}")
                return None, "Unexpected API response format"
                
        else:
            error_detail = response.json() if response.content else "No details"
            logger.error(f"API error: {response.status_code}, {error_detail}")
            return None, f"API error {response.status_code}: {error_detail}"
            
    except Exception as e:
        logger.exception(f"Exception in generate_with_qwen: {str(e)}")
        return None, str(e)

# 风水分析函数 - 修改为使用通义千问API
def analyze_fengshui(grid_data, user_info, is_paid=False):
    """风水分析逻辑"""
    try:
        # 构建房间描述
        room_description = ""
        for position, items in grid_data.items():
            if items and isinstance(items, list):
                room_description += f"Position {position}: {', '.join(items)}. "

        concerns = user_info.get('concerns', 'general feng shui')
        
        # 从知识库获取专业知识
        feng_shui_knowledge = extract_knowledge_for_prompt()
        
        # 根据是否付费用户提供不同深度的分析
        depth = "detailed" if is_paid else "basic"
        
        # 构建提示词
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
        
        ## Special Considerations
        Offer more personalized advice based on the user's specific situation.
        
        {' Include advanced remedies and specific timing recommendations in your analysis.' if is_paid else 'For the non-paid version, keep the analysis brief but insightful.'}
        """

        # 调用通义千问API生成分析
        max_tokens = 1500 if is_paid else 800
        generated_text, error = generate_with_qwen(
            prompt=prompt, 
            max_tokens=max_tokens,
            temperature=0.7,
            is_paid=is_paid
        )
        
        if error:
            return {
                "error": f"Analysis failed: {error}",
                "fallback_response": "Unable to complete analysis. Please try again."
            }, 500
        
        return {
            "success": True,
            "analysis": generated_text,
            "type": "detailed" if is_paid else "basic"
        }

    except Exception as e:
        logger.error(f"Feng Shui analysis error: {str(e)}")
        return {
            "error": f"Analysis failed: {str(e)}",
            "fallback_response": "Unable to complete analysis. Please try again."
        }, 500

# API信息端点 - 更新为提供通义千问信息
@app.route('/api-info', methods=['GET'])
@require_api_key
def api_info():
    """提供API版本和模型信息"""
    try:
        info = {
            "api": "Qwen API Service",
            "model": "qwen-plus-latest",
            "version": "1.0",
            "region": "Beijing",
            "service_provider": "Aliyun Dashscope"
        }
        return jsonify(info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 生成文本端点 - 更新为使用通义千问API
@app.route('/generate', methods=['POST'])
@require_api_key
def generate_text():
    """使用通义千问模型生成文本"""
    try:
        data = request.json
        
        # 验证输入
        if not data or not data.get('prompt'):
            return jsonify({"error": "Missing prompt in request"}), 400
            
        prompt = data.get('prompt')
        temperature = float(data.get('temperature', 0.7))
        max_tokens = int(data.get('max_tokens', 800))
        is_paid = bool(data.get('isPaid', False))
        
        # 使用通义千问API生成文本
        generated_text, error = generate_with_qwen(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            is_paid=is_paid
        )
        
        if error:
            return jsonify({
                "error": f"Text generation failed: {error}",
                "fallback_response": "Failed to generate text. Please try a different prompt."
            }), 500
            
        # 返回结果
        return jsonify({
            "success": True,
            "generated_text": generated_text,
            "model_used": "qwen-plus-latest"
        })
            
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
        "model": "qwen-plus-latest",
        "api_provider": "Aliyun Dashscope",
        "region": "Beijing",
        "timestamp": time.time()
    }
    return jsonify(status)

# 保留接口以保持兼容性
@app.route('/reinitialize', methods=['POST'])
@require_api_key
def reinitialize_model():
    """通义千问不需要重新初始化，但为了兼容性保留此端点"""
    return jsonify({
        "success": True,
        "message": "API doesn't require reinitialization",
        "model_used": "qwen-plus-latest"
    })

# 主页面
@app.route('/', methods=['GET'])
def index():
    """API主页"""
    return jsonify({
        "api": "Feng Shui Analysis API",
        "version": "1.0",
        "model": "通义千问-Plus-Latest",
        "region": "Beijing",
        "provider": "Aliyun Dashscope",
        "endpoints": {
            "/analyze-fengshui": "Analyze Feng Shui arrangement (POST)",
            "/generate": "Generate text with Qwen model (POST)",
            "/api-info": "Get API and model information (GET)",
            "/health": "Health check (GET)",
            "/reinitialize": "Service maintenance endpoint (POST)",
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
