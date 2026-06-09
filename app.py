import requests
import os
import json
import logging
import uuid
import time
import re
import urllib.parse
import sqlite3
import threading
from http import HTTPStatus
from flask import Flask, request, jsonify, make_response, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import dashscope
from requests.auth import HTTPBasicAuth

# --- Custom Module Import ---
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
# ✅ Rate Limiting
# ============================================================
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["60 per minute"],
    storage_uri="memory://"
)

# ============================================================
# ✅ CORS Configuration
# ============================================================
ALLOWED_ORIGINS = [
    "https://fengshuispaceplanner.com",
    "https://www.fengshuispaceplanner.com",
    "http://localhost",  # 本地开发
]

CORS(app,
     resources={r"/*": {"origins": ALLOWED_ORIGINS}},
     methods=["GET", "POST", "OPTIONS"],
     allow_headers=["Content-Type"],
     supports_credentials=False,
     max_age=3600
)

# ============================================================
# ✅ SQLite Persistence (替代内存字典)
# ============================================================
DB_PATH = os.getenv("REPORTS_DB_PATH", "reports.db")

db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
db_lock = threading.Lock()

db_conn.execute('''CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    full_content TEXT NOT NULL,
    created_at REAL NOT NULL,
    kua INTEGER,
    dirs TEXT,
    grid TEXT
)''')
db_conn.commit()

def save_report(report_id, full_content, kua, dirs, grid):
    with db_lock:
        db_conn.execute(
            "INSERT INTO reports (id, full_content, created_at, kua, dirs, grid) VALUES (?, ?, ?, ?, ?, ?)",
            (report_id, full_content, time.time(), kua, json.dumps(dirs) if dirs else None, json.dumps(grid) if grid else None)
        )
        db_conn.commit()

def load_report(report_id):
    with db_lock:
        row = db_conn.execute("SELECT full_content, created_at, kua, dirs, grid FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row:
        return None
    return {
        "full_content": row[0],
        "created_at": row[1],
        "kua": row[2],
        "dirs": json.loads(row[3]) if row[3] else None,
        "grid": json.loads(row[4]) if row[4] else None
    }

def cleanup_old_reports():
    cutoff = time.time() - 86400
    with db_lock:
        db_conn.execute("DELETE FROM reports WHERE created_at < ?", (cutoff,))
        db_conn.commit()

# ============================================================
# ✅ 密钥配置（无 fallback，缺失报错）
# ============================================================
WOO_CK = os.getenv("WOO_CK")
WOO_CS = os.getenv("WOO_CS")
WOO_URL = os.getenv("WOO_URL", "https://fengshuispaceplanner.com")

FSP_API_URL = "https://fengshuispaceplanner.com/wp-json/fsp-api/v1/verify-order"
FSP_API_SECRET = os.getenv("FSP_API_SECRET")
if not FSP_API_SECRET:
    logger.warning("⚠️ FSP_API_SECRET not set - order verification will fail")

QWEN_API_KEY = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
if not QWEN_API_KEY:
    logger.error("⚠️ QWEN_API_KEY not configured - analysis will fail")
else:
    dashscope.api_key = QWEN_API_KEY
    logger.info("✅ API Key loaded")

# ✅ Product Info Configuration
PRODUCT_URL = "https://fengshuispaceplanner.com/product/personalized-feng-shui-talisman/"
PRODUCT_NAME = "Personalized Feng Shui Talisman"

kb_handler = None
if HAS_KB_HANDLER:
    try:
        kb_handler = KnowledgeBaseHandler(base_path="knowledge_base")
        kb_handler.load_knowledge_base()
        logger.info("✅ Feng Shui KB ready")
    except Exception as e:
        logger.warning(f"⚠️ KB init failed: {e}")


# ============================================================
# ✅ CORS Headers Decorator
# ============================================================
def add_cors_headers(response):
    origin = request.headers.get('Origin', '')
    if origin in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
    else:
        response.headers['Access-Control-Allow-Origin'] = ALLOWED_ORIGINS[0]
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
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
        origin = request.headers.get('Origin', '')
        if origin in ALLOWED_ORIGINS:
            response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Max-Age'] = '3600'
        return response


# ============================================================
# ✅ Utility Functions
# ============================================================
def clean_markdown_wrapper(text):
    if not text: return text
    text = re.sub(r'^```(?:markdown)?\s*\n?', '', text.strip())
    text = re.sub(r'\n?```\s*$', '', text)
    return text.strip()

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

# ✅ 输入清洗：只允许合法的家具类型和区域类型
ALLOWED_ITEMS = {'bed', 'door', 'window', 'mirror', 'device', 'sofa', 'table', 'plant'}
ALLOWED_AREAS = {'private', 'public', 'work', 'entertain'}
ALLOWED_POSITIONS = set(str(i) for i in range(1, 10))

def sanitize_grid_data(grid_data):
    """清洗前端传入的 gridData，防止 prompt 注入"""
    if not isinstance(grid_data, dict):
        return {}
    clean = {}
    for pos, cell in grid_data.items():
        if str(pos) not in ALLOWED_POSITIONS:
            continue
        if not isinstance(cell, dict):
            continue
        items = [i for i in cell.get('items', []) if i in ALLOWED_ITEMS]
        areas = [a for a in cell.get('areaTypes', []) if a in ALLOWED_AREAS]
        if items or areas:
            clean[str(pos)] = {'items': items, 'areaTypes': areas}
    return clean

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
    except (ValueError, TypeError) as e:
        logger.warning(f"Kua calculation failed: {e}")
        return None

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
    return jsonify({"status": "running", "version": "3.0.0-hardened", "db": "sqlite"})

@app.route('/health')
def health():
    return jsonify({"status": "ok", "kb": kb_handler is not None})

@app.route('/wake', methods=['GET', 'POST', 'OPTIONS'])
def wake():
    return jsonify({"status": "awake", "time": time.time()})

@app.route('/debug-routes')
def debug_routes():
    output = []
    for rule in app.url_map.iter_rules():
        methods = ','.join(rule.methods)
        line = urllib.parse.unquote(f"{rule.rule:50s} {methods}")
        output.append(line)
    return "<br>".join(output)


# ============================================================
# ✅ /process-layout (已修复缩进 + 输入清洗)
# ============================================================
@app.route('/process-layout', methods=['POST', 'OPTIONS'])
@limiter.limit("5 per minute")
def process_layout():
    cleanup_old_reports()

    try:
        data = request.json or {}
        grid_data = sanitize_grid_data(data.get('gridData', {}))  # ✅ 清洗输入
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

        product_md_link = f"[{PRODUCT_NAME}]({PRODUCT_URL})"
        best_direction = dirs.get('best', 'Southwest')

        # ✅ 产品上下文
        product_context = (
            f"RECOMMENDED CURE: {PRODUCT_NAME}\n"
            "SOURCE: Longhushan (Dragon Tiger Mountain), birthplace of Zhengyi Taoism.\n"
            "DESCRIPTION: Crafted with 1500-year Taoist wisdom, designed to balance bedroom energy.\n"
            "FUNCTION: Address specific imbalances identified in the bedroom analysis.\n"
            "USAGE: Simple placement, no complex rituals required.\n"
            "\n"
            "IMPORTANT RESTRICTIONS - DO NOT USE THESE PHRASES:\n"
            "- 'exact dimensions calibration' or 'precise measurement'\n"
            "- 'electronic residue' or 'structural imbalances'\n"
            "- 'actively stabilizes Qi' or 'hidden energy leaks'\n"
            "- 'custom-calibrated to your room's exact dimensions and orientation'\n"
        )

        prompt = f"""You are a Feng Shui Master. Analyze this bedroom layout.

User Data:
- Layout: {room_desc}
- Personal: {kua_info if kua_info else 'Not provided'}

Product Context:
{product_context}

Task: Provide a Feng Shui report in Markdown. Always address the user directly using "you" and "your".

Structure:
## Overall Energy Assessment
(2 sentences summarizing the flow of Qi)

## Positive Aspects
(2-3 points, use numbered list 1., 2., etc.)

## Areas for Improvement
(3-4 issues with impact, use numbered list 1., 2., etc.)

## Recommended Changes
(Provide exactly THREE distinct recommendations. Number them 1., 2., and 3.)

1. [Write a specific recommendation based on furniture placement or layout]
2. [Write a specific recommendation based on decor, colors, or elements]
3. For the {best_direction} sector, consider placing a {product_md_link} to help balance the energy in this area. This talisman, rooted in Longhushan Taoist tradition, is designed to address the specific imbalances identified in your bedroom and works in harmony with your personal energy pattern.

## Special Tips
(2 personalized tips, use numbered list 1., 2.)

CRITICAL RULES:
1. Always use "you" and "your" when addressing the user
2. The product link must be EMBEDDED within a sentence, not on its own line
3. Product recommendation must be SIMPLE and MODEST
4. ALLOWED phrases (from product page):
   - "balance your bedroom's energy"
   - "address specific imbalances identified in your bedroom"
   - "works in harmony with your personal energy pattern"
   - "rooted in Longhushan Taoist tradition"
   - "no complex rituals required"
5. FORBIDDEN phrases (do not use):
   - "exact dimensions and orientation"
   - "custom-calibrated to your room's precise measurements"
   - "electronic residue"
   - "structural imbalances"
   - "actively stabilizes Qi"
   - "hidden energy leaks"
"""

        logger.info("📝 Calling Qwen API...")

        resp = dashscope.MultiModalConversation.call(
            model='qwen3.6-plus',
            api_key=QWEN_API_KEY,
            messages=[
                {
                    'role': 'system',
                    'content': [{
                        'text': 'Expert Feng Shui consultant. Concise, professional responses. Output plain Markdown directly without wrapping in code blocks. Always address the user as "you/your", never "they/their". Keep product recommendations simple and aligned with the product page - do not exaggerate claims.'
                    }]
                },
                {'role': 'user', 'content': [{'text': prompt}]}
            ],
            result_format='message',
            timeout=25
        )

        # ✅ 修复：正确的缩进
        if resp.status_code == HTTPStatus.OK:
            resp_content = resp.output.choices[0].message.content
            if isinstance(resp_content, list) and len(resp_content) > 0:
                if 'text' in resp_content[0]:
                    full = resp_content[0]['text']
                else:
                    full = str(resp_content)
            elif isinstance(resp_content, str):
                full = resp_content
            else:
                full = str(resp_content)

            full = clean_markdown_wrapper(full)

            report_id = str(uuid.uuid4())

            # ✅ SQLite 持久化
            save_report(report_id, full, kua, dirs, grid_data)

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
# ✅ /verify-purchase
# ============================================================
@app.route('/verify-purchase', methods=['POST', 'OPTIONS'])
@limiter.limit("10 per minute")
def verify_purchase():
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200

    data = request.json or {}
    report_id = data.get('reportId')
    order_id = data.get('orderId')

    logger.info(f"🔓 Verify Request. Report: {report_id}, Order: {order_id}")

    # ✅ SQLite 查询
    report = load_report(report_id) if report_id else None
    if not report:
        logger.warning(f"❌ Report not found: {report_id}")
        return jsonify({"success": False, "error": "Report expired. Please analyze again."}), 404

    if not order_id:
        return jsonify({"success": False, "error": "Please enter Order ID."}), 400

    if not FSP_API_SECRET:
        logger.error("❌ FSP_API_SECRET not configured")
        return jsonify({"success": False, "error": "Verification service not configured."}), 500

    try:
        logger.info(f"🔍 Calling FSP API for order: {order_id}")

        resp = requests.post(
            FSP_API_URL,
            json={"order_id": order_id},
            headers={
                "Content-Type": "application/json",
                "x-fsp-secret": FSP_API_SECRET,
                "User-Agent": "FSP-Payment-Verification/1.0 (Render.com; +https://fengshuispaceplanner.com)"
            },
            timeout=15
        )

        logger.info(f"📥 API response status: {resp.status_code}")
        logger.info(f"📥 API response body: {resp.text[:500]}")

        if "<!DOCTYPE" in resp.text or "<html" in resp.text.lower():
            logger.error("❌ API blocked - received HTML instead of JSON")
            return jsonify({
                "success": False,
                "error": "Verification service temporarily unavailable. Please try again."
            }), 503

        if resp.status_code == 404:
            return jsonify({"success": False, "error": "Order ID not found."}), 404

        if resp.status_code == 403:
            logger.error("❌ API secret mismatch")
            return jsonify({"success": False, "error": "Verification failed."}), 500

        if resp.status_code != 200:
            return jsonify({
                "success": False,
                "error": f"Verification error: {resp.status_code}"
            }), resp.status_code

        try:
            result = resp.json()
        except json.JSONDecodeError:
            logger.error(f"❌ Invalid JSON: {resp.text[:200]}")
            return jsonify({
                "success": False,
                "error": "Invalid response from verification server"
            }), 500

        if not result.get('success'):
            error_msg = result.get('message', 'Unknown error')
            return jsonify({"success": False, "error": error_msg}), 400

        status = result.get('status')
        is_paid = result.get('is_paid', False)

        logger.info(f"✅ Order #{order_id} - Status: {status}, Paid: {is_paid}")

        if status in ['completed', 'processing'] or is_paid:
            return jsonify({
                "success": True,
                "reportId": report_id,
                "analysis": report['full_content'],
                "isLocked": False,
                "kua": report.get('kua'),
                "favorableDirections": report.get('dirs')
            })
        else:
            return jsonify({
                "success": False,
                "error": f"Order status is '{status}'. Please complete payment first."
            }), 400

    except requests.exceptions.Timeout:
        logger.error("❌ API timeout")
        return jsonify({"success": False, "error": "Verification timeout. Please try again."}), 504
    except Exception as e:
        logger.error(f"❌ Verify Exception: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================
# ✅ /get-report
# ============================================================
@app.route('/get-report/<report_id>', methods=['GET', 'OPTIONS'])
@app.route('/get-report', methods=['GET', 'OPTIONS'])
def get_report(report_id=None):
    if report_id is None:
        report_id = request.args.get('reportId') or request.args.get('id')

    # ✅ SQLite 查询
    report = load_report(report_id) if report_id else None
    if not report:
        return jsonify({"success": False, "error": "Not found."}), 404

    paid = request.args.get('paid', 'false').lower() == 'true'

    return jsonify({
        "success": True,
        "reportId": report_id,
        "analysis": report['full_content'] if paid else filter_report_for_free_tier(report['full_content']),
        "isLocked": not paid,
        "kua": report.get('kua'),
        "favorableDirections": report.get('dirs')
    })


# ============================================================
# ✅ Error Handlers
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
