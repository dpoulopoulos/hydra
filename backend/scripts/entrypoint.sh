#! /usr/bin/env bash

set -e
set -x

echo "🔄 Running prestart.sh..."
/app/scripts/prestart.sh

echo "🚀 Starting FastAPI server..."
exec fastapi run --reload src/app/main.py
