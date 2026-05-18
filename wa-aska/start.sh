#!/bin/bash

# ASKA WhatsApp Bot - Startup Script
# Jalankan dengan: bash start.sh

echo "=========================================="
echo "ASKA WhatsApp Bot - Starting Server"
echo "=========================================="
echo ""

# Check if virtual environment exists
if [ ! -d "../venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "   Please create venv first: python3 -m venv ../venv"
    exit 1
fi

# Activate virtual environment
echo "📦 Activating virtual environment..."
source ../venv/bin/activate

# Check if .env exists
if [ ! -f "../.env" ]; then
    echo "❌ .env file not found!"
    echo "   Please copy .env.example to ../.env and configure it"
    echo "   Example: cp .env.example ../.env"
    exit 1
fi

# Check required environment variables
echo "🔍 Checking configuration..."
source ../.env

if [ -z "$WA_ASKA_ACCESS_TOKEN" ]; then
    echo "❌ WA_ASKA_ACCESS_TOKEN not set in .env"
    exit 1
fi

if [ -z "$WA_ASKA_PHONE_NUMBER_ID" ]; then
    echo "❌ WA_ASKA_PHONE_NUMBER_ID not set in .env"
    exit 1
fi

if [ -z "$WA_ASKA_GEMINI_API_KEY" ]; then
    echo "❌ WA_ASKA_GEMINI_API_KEY not set in .env"
    exit 1
fi

echo "✅ Configuration OK"
echo ""

# Check if port is already in use
PORT=${WA_ASKA_PORT:-8000}
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️  Port $PORT is already in use!"
    echo "   Kill existing process? (y/n)"
    read -r response
    if [[ "$response" == "y" ]]; then
        echo "🔫 Killing process on port $PORT..."
        kill -9 $(lsof -Pi :$PORT -sTCP:LISTEN -t)
        sleep 2
    else
        exit 1
    fi
fi

# Start server
echo "=========================================="
echo "🚀 Starting FastAPI server on port $PORT..."
echo "=========================================="
echo ""
echo "Press CTRL+C to stop server"
echo ""

uvicorn app.main:app --reload --port $PORT --host ${WA_ASKA_HOST:-0.0.0.0}
