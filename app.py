import requests
import os
import json
import logging
import uuid
import time
from http import HTTPStatus
from flask import Flask, request, jsonify, make_response
from flask_cors import CORS 
from dotenv import load_dotenv
import dashscope

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
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

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


def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-API-Key, Authorization'
    response.headers['Access-Control-Max-Age'] = '3600'
    return response

@app.after_request
def after_request(response):
    return add_cors_headers(response)


def cleanup_old_reports():
    current_time = time.time()
    expired = [rid for rid, d in reports_db.items() if current_time - d.get('created_at', 0) > 86400]
    for rid in expired:
        del reports_db[rid]
    if expired:
        logger.info(f"🧹 已清理 {len(expired)} 份过期报告")


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
        
        is_list_item = (
            stripped.startswith(('-', '*')) or 
            (len(stripped) > 1 and stripped[0].isdigit() and '.' in stripped[:3])
        )
        
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
        
        if not items and not areas:
            continue
        
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
    if not gender or not birth_year:
        return None
    try:
        year = int(birth_year)
        
        def reduce(n):
            while n > 9:
                n = sum(int(d) for d in str(n))
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
    except:
        return None


def get_favorable_directions(kua):
    if not kua:
        return {}
    
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
    return jsonify({"status": "running", "version": "2.0.0", "cached": len(reports_db)})


@app.route('/health')
def health():
    return jsonify({"status": "ok", "kb": kb_handler is not None})


@app.route('/wake', methods=['GET', 'POST', 'OPTIONS'])
def wake():
    if request.method == 'OPTIONS':
        return make_response()
    return jsonify({"status": "awake", "time": time.time()})


@app.route('/analyze-fengshui', methods=['POST', 'OPTIONS'])
def analyze_fengshui():
    if request.method == 'OPTIONS':
        return make_response()
    
    cleanup_old_reports()
    
    try:
        data = request.json or {}
        grid_data = data.get('gridData', {})
        is_paid = data.get('isPaid', False)
        
        # 解析个人信息
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
        
        # 知识库上下文
        kb_context = ""
        if kb_handler:
            query = "bedroom feng shui bed position"
            if "mirror" in room_desc.lower(): query += " mirror"
            if "door" in room_desc.lower(): query += " door"
            kb_context = kb_handler.get_relevant_context(query)
        kb_context = kb_context or "Apply classical Feng Shui: Chi flow, Yin-Yang balance, Five Elements harmony."
        
        # 命卦信息
        kua_block = ""
        if kua and dirs:
            kua_block = f"""
=== PERSONAL KUA ===
Kua: {kua} ({dirs.get('group')} Group)
Best (Sheng Qi): {dirs.get('best')}
Favorable: {', '.join(dirs.get('favorable', []))}
Worst (Jue Ming): {dirs.get('worst')}
====================
"""
        
        prompt = f"""You are a Master Feng Shui Consultant (30+ years, Flying Star & Eight Mansions methods).

=== KNOWLEDGE BASE ===
{kb_context}
======================
{kua_block}
=== CURRENT LAYOUT ===
{room_desc if room_desc != "The room is currently empty." else "Empty room. Provide general guidance."}
======================

OUTPUT (Markdown):

## Overall Energy Assessment
(2-3 sentences)

## Positive Aspects
(2-3 good points)

## Areas for Improvement
(3-5 issues with WHY)

## Recommended Changes
(Specific fixes for each issue)

*** MUST RECOMMEND: [{PRODUCT_NAME}]({PRODUCT_URL}) ***
- Place in {dirs.get('best', 'favorable')} corner
- Explain how it fixes the energy imbalance
- Mention personalization

## Special Considerations
(Kua-based tips: sleep direction, colors, elements)
"""
        
        logger.info("📝 Calling Qwen API...")
        resp = dashscope.Generation.call(
            model='qwen-plus',
            messages=[
                {'role': 'system', 'content': 'You are a wise, traditional Feng Shui master. Professional yet warm.'},
                {'role': 'user', 'content': prompt}
            ],
            result_format='message'
        )
        
        if resp.status_code == HTTPStatus.OK:
            full = resp.output.choices[0].message.content
            report_id = str(uuid.uuid4())
            
            reports_db[report_id] = {
                "full_content": full,
                "created_at": time.time(),
                "kua": kua,
                "dirs": dirs,
                "grid": grid_data
            }
            
            content = full if is_paid else filter_report_for_free_tier(full)
            
            return jsonify({
                "success": True,
                "reportId": report_id,
                "analysis": content,
                "isLocked": not is_paid,
                "kua": kua,
                "favorableDirections": dirs
            })
        else:
            return jsonify({"success": False, "error": resp.message}), 500
            
    except Exception as e:
        logger.error(f"❌ Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/unlock-report', methods=['POST', 'OPTIONS'])
def unlock_report():
    if request.method == 'OPTIONS':
        return make_response()
    
    data = request.json or {}
    report_id = data.get('reportId')
    order_id = data.get('orderId')
    
    if not report_id or report_id not in reports_db:
        return jsonify({"success": False, "error": "Report expired. Please analyze again."}), 404
    
    if not order_id:
        return jsonify({"success": False, "error": "Please enter Order ID."}), 400
    
    try:
        url = f"{WOO_URL.rstrip('/')}/wp-json/wc/v3/orders/{order_id}"
        resp = requests.get(url, auth=(WOO_CK, WOO_CS), headers={"User-Agent": "FengShuiApp/2.0"}, timeout=15)
        
        if resp.status_code != 200:
            return jsonify({"success": False, "error": "Order not found."}), 404
        
        status = resp.json().get('status')
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
            return jsonify({"success": False, "error": f"Order status: {status}"}), 400
            
    except requests.Timeout:
        return jsonify({"success": False, "error": "Timeout. Retry."}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/get-report/<report_id>', methods=['GET', 'OPTIONS'])
def get_report(report_id):
    if request.method == 'OPTIONS':
        return make_response()
    
    if report_id not in reports_db:
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🚀 Starting on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
