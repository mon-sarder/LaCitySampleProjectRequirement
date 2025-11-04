# 🤖 Robot Driver API - Books to Scrape Web Automation

A Flask-based web automation API with Playwright scraping capabilities and MCP (Model Context Protocol) integration for Claude Desktop. This project demonstrates automated web scraping, RESTful API design, and AI agent integration.

## 📋 Table of Contents

- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [Testing](#testing)
- [Claude Desktop MCP Integration](#claude-desktop-mcp-integration)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)

---

## ✨ Features

- 🔍 **Web Scraping**: Automated scraping of Books to Scrape website using Playwright
- 🌐 **RESTful API**: Flask-based API with JSON endpoints
- 🔐 **Authentication**: Session-based auth with SQLite database
- 🤖 **MCP Integration**: Model Context Protocol server for Claude Desktop
- 🐳 **Docker Support**: Containerized deployment option
- 📊 **Category Search**: Search books by 50+ categories
- 🎨 **Modern UI**: Clean, responsive web interface
- 🔒 **Security**: CSP headers, rate limiting, input validation

---

## 📦 Prerequisites

### Required Software

1. **Python 3.8+**
```bash
   python3 --version
```

2. **Git**
```bash
   git --version
```

3. **pip (Python package manager)**
```bash
   pip3 --version
```

4. **Docker** (Optional - for containerized deployment)
```bash
   docker --version
```

5. **Claude Desktop** (Optional - for MCP integration)
   - Download from: https://claude.ai/download

### System Requirements

- macOS, Linux, or Windows (WSL recommended for Windows)
- 4GB RAM minimum
- 500MB free disk space

---

## 🚀 Installation

### Step 1: Clone the Repository
```bash
git clone https://github.com/mon-sarder/LaCitySampleProjectRequirement.git
cd LaCitySampleProjectRequirement/backend
```

### Step 2: Create Virtual Environment
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### Step 3: Install Python Dependencies
```bash
# Upgrade pip first
pip install --upgrade pip

# Install all required packages
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

**What gets installed:**
- Flask 3.0.0 - Web framework
- Playwright 1.48.0 - Browser automation
- Anthropic SDK - Claude API integration
- python-dotenv - Environment variable management
- mcp - Model Context Protocol server
- And other dependencies (see `requirements.txt`)

---

## ⚙️ Configuration

### Step 1: Create Environment File

Copy the example environment file:
```bash
cp .env.example .env
```

### Step 2: Configure Environment Variables

Edit `.env` file with your settings:
```bash
nano .env
```

**Required variables:**
```env
# Claude API Key (get from https://console.anthropic.com/)
ANTHROPIC_API_KEY=sk-ant-api03-your-actual-key-here

# Flask Configuration
FLASK_SECRET=your-secret-key-change-this
API_KEY=secret123
RELAXED_CSP=1
ADMIN_DEFAULT=1

# Robot Driver Configuration
ROBOT_BASE_URL=http://localhost:5001
ROBOT_API_KEY=secret123
```

**How to get your Claude API key:**
1. Go to https://console.anthropic.com/
2. Sign in with your account
3. Navigate to Settings → API Keys
4. Click "Create Key"
5. Copy the key (starts with `sk-ant-api03-`)

### Step 3: Verify Configuration
```bash
# Test that environment variables load correctly
python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print('✅ Config loaded!' if os.getenv('ANTHROPIC_API_KEY') else '❌ Config missing')"
```

---

## 🎬 Running the Application

### Option 1: Run Locally (Recommended for Development)

**Single Terminal:**
```bash
# Navigate to backend directory
cd backend

# Activate virtual environment
source venv/bin/activate

# Set environment variables
export RELAXED_CSP=1
export API_KEY=secret123
export ADMIN_DEFAULT=1

# Run the server
python3 app.py
```

**Expected output:**
```
🚀 Starting Robot Driver API...
✅ Database initialized
✅ Seeded default admin user: admin / admin123
✅ Server ready!
📍 Access at: http://localhost:5001
```

**Access the application:**
- Login: http://localhost:5001/login
- Demo Console: http://localhost:5001/demo
- Health Check: http://localhost:5001/api/health

**Default credentials:**
- Username: `admin`
- Password: `admin123`

---

### Option 2: Run with Docker

**Terminal 1 - Build and run:**
```bash
cd backend

# Build Docker image
docker build -t robot-driver-api .

# Run container
docker run -d -p 5001:5001 \
  -e RELAXED_CSP=1 \
  -e API_KEY=secret123 \
  -e ADMIN_DEFAULT=1 \
  --name robot-driver \
  robot-driver-api

# View logs
docker logs -f robot-driver
```

**Or use the automated script:**
```bash
chmod +x run_local.sh
./run_local.sh
```

**Docker commands:**
```bash
# Stop container
docker stop robot-driver

# Start container
docker start robot-driver

# Remove container
docker rm robot-driver

# View logs
docker logs robot-driver
```

---

### Option 3: Multiple Terminals (Development Setup)

**Terminal 1 - Run Flask Server:**
```bash
cd backend
source venv/bin/activate
python3 app.py
```

**Terminal 2 - Run Tests:**
```bash
cd backend
source venv/bin/activate
python3 test_mcp.py
```

**Terminal 3 - Run MCP Server (for Claude Desktop):**
```bash
cd backend
source venv/bin/activate
python3 mcp_bridge.py
```

---

## 🧪 Testing

### Run All Tests
```bash
cd backend

# Test MCP endpoints
python3 test_mcp.py

# Test Claude API connection
python3 test_claude_api.py

# Test environment variables
python3 test_env.py
```

### Expected Test Output
```
🤖 Robot Driver MCP Server Test Suite
============================================================
✅ PASS - Health Check
✅ PASS - Categories
✅ PASS - Search
✅ PASS - Run Goal

Total: 4/4 tests passed
🎉 All tests passed!
```

### Manual API Testing
```bash
# Health check
curl http://localhost:5001/api/health

# List categories
curl -H "X-API-Key: secret123" http://localhost:5001/categories.json

# Search for books
curl -X POST http://localhost:5001/search-json \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret123" \
  -d '{"product":"Travel","limit":5}'
```

---

## 🤖 Claude Desktop MCP Integration

### Step 1: Configure Claude Desktop

Add this configuration to your Claude Desktop MCP settings:

**Location:** `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS)
```json
{
  "mcpServers": {
    "robot-driver": {
      "command": "python3",
      "args": [
        "/Users/monsarder/LaCitySampleProjectRequirement/backend/mcp_bridge.py"
      ],
      "env": {
        "ROBOT_BASE_URL": "http://localhost:5001",
        "ROBOT_API_KEY": "secret123"
      }
    }
  }
}
```

**Replace** `/Users/monsarder/LaCitySampleProjectRequirement/backend/mcp_bridge.py` with your actual path.

### Step 2: Restart Claude Desktop

1. **Quit** Claude Desktop completely (Cmd+Q on Mac)
2. **Restart** Claude Desktop
3. The MCP server will connect automatically

### Step 3: Verify MCP Connection

In Claude Desktop, you should now be able to use these tools:
- `check_health()` - Check server health
- `list_categories()` - Get all book categories
- `search_product(product, limit)` - Search for books
- `run_goal(goal)` - Execute automation goals

**Example prompts to try:**
- "List all book categories"
- "Search for Travel books and show me 5 results"
- "Find the cheapest books in the Mystery category"

---

## 📚 API Endpoints

### Public Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check (no auth required) |
| `/login` | GET/POST | User login page |
| `/register` | GET/POST | User registration |

### Authenticated Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/search` | GET/POST | Session | Search page (HTML) |
| `/demo` | GET | Session | Demo console (HTML) |
| `/categories.json` | GET | Session/API Key | Get all categories |
| `/search-json` | POST | Session/API Key | Search books (JSON) |
| `/api/run` | POST | Session/API Key | Execute automation goal |
| `/login-test` | POST | Session/API Key | Test login automation |

### API Request Examples

**Search for books:**
```bash
curl -X POST http://localhost:5001/search-json \
  -H "Content-Type: application/json" \
  -H "X-API-Key: secret123" \
  -d '{
    "product": "Travel",
    "limit": 10
  }'
```

**Get categories:**
```bash
curl -H "X-API-Key: secret123" \
  http://localhost:5001/categories.json
```

---

## 📁 Project Structure
```
backend/
├── .env                    # Environment variables (create from .env.example)
├── .env.example            # Environment template
├── .gitignore              # Git ignore rules
├── Dockerfile              # Docker configuration
├── requirements.txt        # Python dependencies
├── run_local.sh           # Docker startup script
│
├── app.py                  # Main Flask application
├── robot_driver.py         # Playwright scraper
├── login_driver.py         # Login automation
├── mcp_agent.py           # AI goal executor
├── mcp_bridge.py          # MCP server for Claude
│
├── test_mcp.py            # MCP endpoint tests
├── test_claude_api.py     # Claude API tests
├── test_env.py            # Environment tests
│
├── static/
│   └── style.css          # CSS styles
│
└── templates/
    ├── index.html         # Demo console
    ├── login.html         # Login page
    ├── register.html      # Registration page
    ├── search.html        # Search page
    └── categories.html    # Categories page
```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. "Module not found" errors
```bash
# Make sure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

#### 2. "Port 5001 already in use"
```bash
# Find process using port 5001
lsof -i :5001

# Kill the process
kill -9 <PID>

# Or use a different port
export FLASK_PORT=5002
python3 app.py
```

#### 3. Playwright browser issues
```bash
# Reinstall Playwright browsers
playwright install chromium

# Or install all browsers
playwright install
```

#### 4. Docker health check failing
```bash
# Check Docker logs
docker logs robot-driver

# Increase startup time in Dockerfile (already set to 60s)
# Or wait longer before checking health
```

#### 5. MCP server not connecting to Claude Desktop
```bash
# Verify MCP bridge path is correct
ls -la ~/Library/Application\ Support/Claude/claude_desktop_config.json

# Test MCP bridge manually
cd backend
python3 mcp_bridge.py

# Restart Claude Desktop completely
```

#### 6. ".env file not loading"
```bash
# Check file exists
ls -la .env

# Check file is in .gitignore
cat .gitignore | grep .env

# Test loading
python3 -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('API_KEY'))"
```

---

## 📖 Additional Resources

- **Flask Documentation**: https://flask.palletsprojects.com/
- **Playwright Python**: https://playwright.dev/python/
- **Anthropic API**: https://docs.anthropic.com/
- **MCP Specification**: https://modelcontextprotocol.io/
- **Books to Scrape**: https://books.toscrape.com/

---

## 🤝 Contributing

This is a sample project for educational purposes. Feel free to fork and modify.

---

## 📄 License

MIT License - See LICENSE file for details

---

## 👤 Author

**Mon Sarder**
- GitHub: [@mon-sarder](https://github.com/mon-sarder)

---

## 🎓 Project Context

This project was created as a sample implementation demonstrating:
- Web scraping with Playwright
- RESTful API design with Flask
- MCP (Model Context Protocol) integration
- Docker containerization
- Modern web development practices

---

## ⚡ Quick Start Commands
```bash
# Clone and setup
git clone https://github.com/mon-sarder/LaCitySampleProjectRequirement.git
cd LaCitySampleProjectRequirement/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# Configure
cp .env.example .env
nano .env  # Add your API keys

# Run
python3 app.py

# Test
python3 test_mcp.py

# Access
open http://localhost:5001/login
```

---

**🎉 You're all set! Happy coding!**
