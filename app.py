import requests
import os
import json
import logging
import uuid
import time
import re
import urllib.parse
from http import HTTPStatus
from flask import Flask, request, jsonify, make_response, Response
from flask_cors import CORS 
from dotenv import load_dotenv
import dashscope
from functools import wraps

# --- 自定义模块引入 ---
try:
    from knowledge_base_handler import KnowledgeBaseHandler
    HAS_KB_HANDLER = True
except ImportError:
    HAS_KB_HANDLER = False
    print("⚠️ Warning: knowledge_base_handler module not found. Running without KB.")

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('fengshui_app')

app = Flask(__name__)

# ============================================================
# ✅ CORS 配置
# ============================================================
CORS(app, 
     resources={r"/*": {"origins": "*"}},
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type", "X-API-Key", "Authorization"],
     supports_credentials=False,
     max_age=3600
)

reports_db = {}

WOO_CK = os.getenv("WOO_CK", "ck_1164e779c5af0df880fbf3fb3ddd38a808dc0e56")
WOO_CS = os.getenv("WOO_CS", "cs_cce2d28d979f992aa9a9a8183f79dd3c8ba76612")
WOO_URL = os.getenv("WOO_URL", "https://fengshuispaceplanner.com")

QWEN_API_KEY = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
if not QWEN_API_KEY:
    logger.error("⚠️ 未检测到 API Key")
else:
    dashscope.api_key = QWEN_API_KEY
    logger.info("✅ API Key 已加载")

# ✅ 产品信息配置
PRODUCT_URL = "https://fengshuispaceplanner.com/product/personalized-feng-shui-talisman/"
PRODUCT_NAME = "Personalized Feng Shui Talisman"

kb_handler = None
if HAS_KB_HANDLER:
    try:
        kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
        kb_handler.load_knowledge_base()
        logger.info("✅ 风水知识库准备就绪")
    except Exception as e:
        logger.warning(f"⚠️ 知识库初始化失败: {e}")


# ============================================================
# ✅ CORS 头装饰器
# ============================================================
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, Authorization'
    response.headers['Access-Control-Max-Age'] = '3600'
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

@app.after_request
def after_request(response):
    return add_cors_headers(response)

@app.before_request
def handle_options():
    if request.method == 'OPTIONS':
        response = make_response()
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, Authorization'
        response.headers['Access-Control-Max-Age'] = '3600'
        return response


# ============================================================
# ✅ 工具函数 (保持不变)
# ============================================================
def clean_markdown_wrapper(text):
    if not text: return text
    text = re.sub(r'^```(?:markdown)?\s*\n?', '', text.strip())
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()

def cleanup_old_reports():
    current_time = time.time()
    expired = [rid for rid, d in reports_db.items() if current_time - d.get('created_at', 0) > 86400]
    for rid in expired:
        del reports_db[rid]

def filter_report_for_free_tier(full_text):
    lines = full_text.split('\n')
    output_lines = []
    found_improvement = False
    bullet_count = 0
    
    for line in lines:
        stripped = line.strip()
        if "## Areas for Improvement" in line:
            found_improvement = True
            output_lines.append(line)
            continue
        if not found_improvement:
            output_lines.append(line)
            continue
        
        is_list_item = (stripped.startswith(('-', '*')) or (len(stripped) > 1 and stripped[0].isdigit() and '.' in stripped[:3]))
        
        if is_list_item:
            bullet_count += 1
            if bullet_count == 1:
                output_lines.append(line)
            else:
                break
        elif bullet_count < 1:
            output_lines.append(line)

    paywall = (
        "\n\n"
        "> 🔒 **PREMIUM CONTENT HIDDEN**\n"
        ">\n"
        "> Only the first issue is visible. \n"
        "> **Unlock the full report** to see the remaining issues, \n"
        "> detailed **Recommended Changes**, and the **Cure Selection**."
    )
    return "\n".join(output_lines) + paywall

def format_grid_data_for_ai(grid_data):
    position_map = {
        "1": "Northwest (NW) - Mentor Luck (Qian/乾)",
        "2": "North (N) - Career Luck (Kan/坎)",
        "3": "Northeast (NE) - Knowledge Luck (Gen/艮)",
        "4": "West (W) - Children/Creativity (Dui/兑)",
        "5": "Center - Health/Overall Luck",
        "6": "East (E) - Family/Health (Zhen/震)",
        "7": "Southwest (SW) - Love/Relationship (Kun/坤)",
        "8": "South (S) - Fame/Recognition (Li/离)",
        "9": "Southeast (SE) - Wealth Luck (Xun/巽)"
    }
    desc = []
    for pos, cell in grid_data.items():
        items = cell.get('items', []) if isinstance(cell, dict) else (cell if isinstance(cell, list) else [])
        areas = cell.get('areaTypes', []) if isinstance(cell, dict) else []
        if not items and not areas: continue
        
        pos_name = position_map.get(str(pos), f"Position {pos}")
        parts = []
        if items:
            readable = [("Sleeping Bed" if i == 'bed' else i.replace('_', ' ').title()) for i in items]
            parts.append(f"contains {', '.join(readable)}")
        if areas:
            parts.append(f"marked as {', '.join([a.replace('_', ' ').title() for a in areas])} area")
        if parts:
            desc.append(f"- {pos_name}: {' and '.join(parts)}.")
    return "\n".join(desc) if desc else "The room is currently empty."

def calculate_kua_number(gender, birth_year):
    if not gender or not birth_year: return None
    try:
        year = int(birth_year)
        def reduce(n):
            while n > 9: n = sum(int(d) for d in str(n))
            return n if n != 0 else 9
        reduced = reduce(year % 100)
        if gender.lower() == 'male':
            kua = (9 - reduced) if year >= 2000 else (10 - reduced)
            if kua <= 0: kua += 9
            if kua == 10: kua = 1
        else:
            kua = reduce((reduced + 6) if year >= 2000 else (reduced + 5))
        if kua == 0: kua = 9
        if kua == 5: kua = 2 if gender.lower() == 'male' else 8
        return kua
    except: return None

def get_favorable_directions(kua):
    if not kua: return {}
    data = {
        1: {"favorable": ["Southeast", "East", "South", "North"], "unfavorable": ["Northwest", "West", "Southwest", "Northeast"], "best": "Southeast", "worst": "Southwest"},
        2: {"favorable": ["Northeast", "West", "Northwest", "Southwest"], "unfavorable": ["Southeast", "East", "South", "North"], "best": "Northeast", "worst": "Southeast"},
        3: {"favorable": ["South", "North", "East", "Southeast"], "unfavorable": ["Southwest", "Northeast", "Northwest", "West"], "best": "South", "worst": "West"},
        4: {"favorable": ["North", "South", "Southeast", "East"], "unfavorable": ["Southwest", "Northeast", "West", "Northwest"], "best": "North", "worst": "Northeast"},
        6: {"favorable": ["West", "Northeast", "Southwest", "Northwest"], "unfavorable": ["East", "Southeast", "North", "South"], "best": "West", "worst": "South"},
        7: {"favorable": ["Northwest", "Southwest", "West", "Northeast"], "unfavorable": ["Southeast", "East", "South", "North"], "best": "Northwest", "worst": "North"},
        8: {"favorable": ["Southwest", "Northwest", "Northeast", "West"], "unfavorable": ["Southeast", "East", "South", "North"], "best": "Southwest", "worst": "East"},
        9: {"favorable": ["East", "South", "North", "Southeast"], "unfavorable": ["West", "Southwest", "Northwest", "Northeast"], "best": "East", "worst": "Northwest"},
    }
    result = data.get(kua, {})
    result["kua"] = kua
    result["group"] = "East" if kua in [1,3,4,9] else "West"
    return result


@app.route('/')
def home():
    return jsonify({"status": "running", "version": "2.1.1-FULL", "cached": len(reports_db)})

@app.route('/health')
def health():
    return jsonify({"status": "ok", "kb": kb_handler is not None})

@app.route('/wake', methods=['GET', 'POST', 'OPTIONS'])
def wake():
    return jsonify({"status": "awake", "time": time.time()})

# ✅ 保留原有的调试路由
@app.route('/debug-routes')
def debug_routes():
    output = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(rule.methods)
        line = urllib.parse.unquote(f"{rule.rule:50s} {methods}")
        output.append(line)
    return "<br>".join(output)

# ============================================================
# ✅ 核心修改 1：重命名为 /process-layout (原 analyze-fengshui)
# ============================================================
@app.route('/process-layout', methods=['POST', 'OPTIONS'])
def process_layout():
    cleanup_old_reports()
    
    try:
        data = request.json or {}
        grid_data = data.get('gridData', {})
        is_paid = data.get('isPaid', False)
        
        info = data.get('personalInfo', {})
        gender = info.get('gender', '')
        birth_date = info.get('birthDate', '')
        
        birth_year = ''
        if birth_date:
            for sep in ['-', '/']:
                if sep in birth_date:
                    birth_year = birth_date.split(sep)[0]
                    break
        
        kua = calculate_kua_number(gender, birth_year) if gender and birth_year else None
        dirs = get_favorable_directions(kua)
        room_desc = format_grid_data_for_ai(grid_data)
        
        kua_info = ""
        if kua and dirs:
            kua_info = f"Kua {kua}, Best: {dirs.get('best')}, Avoid: {dirs.get('worst')}"
        
        prompt = f"""Feng Shui Master analysis for bedroom layout.

Layout: {room_desc}
{f'Personal: {kua_info}' if kua_info else ''}

Provide in Markdown:
## Overall Energy Assessment
(2 sentences)

## Positive Aspects  
(2-3 points)

## Areas for Improvement
(3-4 issues with impact)

## Recommended Changes
IMPORTANT: Provide exactly THREE (3) distinct, actionable recommendations. Number them 1, 2, and 3.
1. [First specific recommendation based on furniture placement or layout]
2. [Second specific recommendation based on decor, colors, or elements]
3. [Third recommendation]: Identify a specific energy blockage in the {dirs.get('best', 'favorable')} sector that cannot be fixed by furniture alone. Prescribe the [{PRODUCT_NAME}]({PRODUCT_URL}) as the essential cure to activate this sector.

## Special Tips
(1-2 personalized tips)"""        

        logger.info("📝 Calling Qwen API...")
        
        resp = dashscope.Generation.call(
            model='qwen-plus',
            messages=[
                {'role': 'system', 'content': 'Expert Feng Shui consultant. Concise, professional responses. Output plain Markdown directly without wrapping in code blocks.'},
                {'role': 'user', 'content': prompt}
            ],
            result_format='message',
            timeout=25
        )
        
        if resp.status_code == HTTPStatus.OK:
            full = resp.output.choices[0].message.content
            full = clean_markdown_wrapper(full)
            report_id = str(uuid.uuid4())
            
            reports_db[report_id] = {
                "full_content": full,
                "created_at": time.time(),
                "kua": kua,
                "dirs": dirs,
                "grid": grid_data
            }
            
            content = full if is_paid else filter_report_for_free_tier(full)
            
            logger.info(f"✅ Report generated: {report_id[:8]}...")
            
            return jsonify({
                "success": True,
                "reportId": report_id,
                "analysis": content,
                "isLocked": not is_paid,
                "kua": kua,
                "favorableDirections": dirs
            })
        else:
            logger.error(f"❌ Qwen API error: {resp.message}")
            return jsonify({"success": False, "error": resp.message}), 500
            
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# ✅ 核心修改 2：重命名为 /verify-purchase (原 unlock-report)
# ============================================================
@app.route('/verify-purchase', methods=['POST', 'OPTIONS'])
def verify_purchase():
    # 显式处理 OPTIONS 请求
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200

    data = request.json or {}
    report_id = data.get('reportId')
    order_id = data.get('orderId')
    
    logger.info(f"🔓 收到验证请求. Report: {report_id}, Order: {order_id}")

    if not report_id or report_id not in reports_db:
        logger.warning(f"❌ 报告未找到: {report_id}")
        return jsonify({"success": False, "error": "Report expired. Please analyze again."}), 404
    
    if not order_id:
        return jsonify({"success": False, "error": "Please enter Order ID."}), 400
    
    try:
        base_url = WOO_URL.rstrip('/')
        url = f"{base_url}/wp-json/wc/v3/orders/{order_id}"
        
        logger.info(f"🔍 正在向 WooCommerce 验证: {url}")
        
        # ✅ 关键修复：伪装成真实浏览器，防止 SiteGround 拦截
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Connection": "keep-alive"
        }

        resp = requests.get(
            url, 
            auth=(WOO_CK, WOO_CS), 
            headers=headers, 
            timeout=15
        )
        
        if "sgcaptcha" in resp.text:
            logger.error("❌ 严重错误: 请求被 SiteGround 安全插件拦截。")
            return jsonify({"success": False, "error": "Server connection blocked by website security."}), 500

        if resp.status_code != 200:
            logger.error(f"❌ WooCommerce 错误 {resp.status_code}")
            return jsonify({"success": False, "error": "Order not found."}), 404
        
        order_data = resp.json()
        status = order_data.get('status')
        logger.info(f"✅ 订单状态: {status}")

        if status in ['completed', 'processing']:
            r = reports_db[report_id]
            return jsonify({
                "success": True,
                "reportId": report_id,
                "analysis": r['full_content'],
                "isLocked": False,
                "kua": r.get('kua'),
                "favorableDirections": r.get('dirs')
            })
        else:
            return jsonify({"success": False, "error": f"Order status is '{status}', waiting for completion."}), 400
            
    except Exception as e:
        logger.error(f"❌ 验证异常: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# ✅ 保留原有的 get-report 路由
# ============================================================
@app.route('/get-report/<report_id>', methods=['GET', 'OPTIONS'])
@app.route('/get-report', methods=['GET', 'OPTIONS'])
def get_report(report_id=None):
    if report_id is None:
        report_id = request.args.get('reportId') or request.args.get('id')

    if not report_id or report_id not in reports_db:
        return jsonify({"success": False, "error": "Not found."}), 404
    
    r = reports_db[report_id]
    paid = request.args.get('paid', 'false').lower() == 'true'
    
    return jsonify({
        "success": True,
        "reportId": report_id,
        "analysis": r['full_content'] if paid else filter_report_for_free_tier(r['full_content']),
        "isLocked": not paid,
        "kua": r.get('kua'),
        "favorableDirections": r.get('dirs')
    })

# ============================================================
# ✅ 错误处理 (保持不变)
# ============================================================
@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception: {e}", exc_info=True)
    response = jsonify({"success": False, "error": "Internal server error"})
    response.status_code = 500
    return add_cors_headers(response)

@app.errorhandler(404)
def handle_404(e):
    response = jsonify({"success": False, "error": "Not found"})
    response.status_code = 404
    return add_cors_headers(response)

@app.errorhandler(500)
def handle_500(e):
    response = jsonify({"success": False, "error": "Server error"})
    response.status_code = 500
    return add_cors_headers(response)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🚀 Starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
