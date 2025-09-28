# Feng Shui Bedroom Analyzer API

Backend service for the Feng Shui Bedroom Analysis application. This service:

1. Receives bedroom layout data from WordPress frontend
2. Analyzes the layout using Feng Shui principles and the Gemini Pro AI model
3. Returns comprehensive analysis reports with paid/free content differentiation
4. Integrates with WooCommerce for payment verification

## Setup

1. Clone this repository
2. Install dependencies: `pip install -r requirements.txt`
3. Add your API keys to `.env` file:
GEMINI_API_KEY=your_gemini_api_key
WP_API_KEY=your_wordpress_api_key
4. Create a `knowledge_base` folder and add your Feng Shui reference materials
5. Run locally: `python app.py`
6. Deploy to Render

## API Endpoints

- `POST /analyze`: Analyze bedroom layout
- `POST /verify-payment`: Verify WooCommerce payment status
- `GET /health`: Health check endpoint

## Environment Variables

- `GEMINI_API_KEY`: Google Gemini API key
- `WP_API_KEY`: API key for WordPress integration
