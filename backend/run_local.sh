#!/bin/bash
# run_local.sh — Build, run, and test your robot-driver-api locally
# ---------------------------------------------------------------

IMAGE_NAME="robot-driver-api"
PORT=5001
API_KEY="secret123"

echo "🔧 Step 1: Building Docker image..."
docker build -t $IMAGE_NAME . || { echo "❌ Build failed"; exit 1; }

echo "🚀 Step 2: Running container (detached mode)..."
CONTAINER_ID=$(docker run -d -p $PORT:5001 \
  -e RELAXED_CSP=1 \
  -e API_KEY=$API_KEY \
  -e ADMIN_DEFAULT=1 \
  $IMAGE_NAME)

echo "⏳ Waiting for server to start (30 seconds)..."
sleep 30

echo "🕵️ Step 3: Checking health endpoint..."
HEALTH=$(curl -s http://localhost:$PORT/api/health || echo "down")

if [[ $HEALTH == *"ok"* ]]; then
  echo "✅ Server is healthy and running at: http://localhost:$PORT"
else
  echo "⚠️ Health check failed. Logs below:"
  docker logs $CONTAINER_ID
  exit 1
fi

echo ""
echo "📊 Step 4: Testing categories endpoint..."
curl -s http://localhost:$PORT/categories.json | jq '.count, .status'

echo ""
echo "📊 Step 5: Testing search endpoint..."
curl -s -X POST http://localhost:$PORT/search-json \
  -H "Content-Type: application/json" \
  -d '{"product":"Travel"}' | jq '.status, .category, .meta.count'

echo ""
echo "🧠 Step 6: Testing MCP API run endpoint..."
curl -s -X POST "http://localhost:$PORT/api/run" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"goal":"list categories"}' | jq '.status, .result.status'

echo ""
echo "🎉 Done! App is live on: http://localhost:$PORT"
echo "🧱 Container ID: $CONTAINER_ID"
echo "📜 View logs: docker logs -f $CONTAINER_ID"
echo "🛑 Stop container: docker stop $CONTAINER_ID && docker rm $CONTAINER_ID"
echo ""
echo "🔗 Test URLs:"
echo "   Health: http://localhost:$PORT/api/health"
echo "   Login:  http://localhost:$PORT/login (admin/admin123)"
echo "   Demo:   http://localhost:$PORT/demo"