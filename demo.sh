#!/usr/bin/env bash

echo "=== resetting ai-chatbot2 history ==="

echo "You are a billing specialist assistant for a SaaS company. Focus on payment, refund, and subscription questions. Always mention the relevant timeframe or policy when you know it."  > servers/prompts/ai-chatbot2.txt
python gitgrounded.py --del-v "ai-chatbot2"

echo
echo "=== checking all endpoints — storing baseline ==="
python gitgrounded.py --check --quick

echo
echo "=== editing ai-chatbot2's prompt live ==="
echo "You are a billing specialist bot. Keep every answer under 5 words." > servers/prompts/ai-chatbot2.txt
cat servers/prompts/ai-chatbot2.txt

echo
echo "=== checking again — comparing against baseline ==="
python gitgrounded.py --check --quick

echo
echo "=== ranking ai-chatbot2's version history ==="
python gitgrounded.py --rank "ai-chatbot2"