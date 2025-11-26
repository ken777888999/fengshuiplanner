from functools import wraps
from flask import request, jsonify
import os
import logging

logger = logging.getLogger(__name__)

def require_api_key(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        expected_key = os.getenv("APP_API_KEY")
        
        if not api_key or api_key != expected_key:
            logger.warning("Invalid API key attempt")
            return jsonify({"error": "Invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated_function
