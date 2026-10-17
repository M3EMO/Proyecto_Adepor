#!/usr/bin/env bash
# Dashboard Adepor en local. Solo escucha en 127.0.0.1. Sin ngrok ni red externa.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -m streamlit run dashboard.py \
    --server.address 127.0.0.1 \
    --server.headless true \
    --browser.gatherUsageStats false
