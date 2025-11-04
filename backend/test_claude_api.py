# backend/test_claude_api.py
import os
from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

# Test if API key is loaded
api_key = os.environ.get("ANTHROPIC_API_KEY")
print(f"✅ API Key loaded: {api_key[:20]}..." if api_key else "❌ API Key not found!")

# Test API connection
try:
    client = Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=100,
        messages=[{"role": "user", "content": "Say hello!"}]
    )
    print(f"✅ Claude API working! Response: {message.content[0].text}")
except Exception as e:
    print(f"❌ Error: {e}")