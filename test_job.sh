#!/bin/bash

SMILES=$1

if [ -z "$SMILES" ]; then
  echo "Usage: ./test_job.sh <SMILES>"
  echo "Example: ./test_job.sh c1ccccc1"
  exit 1
fi

if [ -z "$TOKEN" ]; then
  echo "Error: Please export your JWT TOKEN first."
  echo "export TOKEN=\"eyJhbGciOi...\""
  exit 1
fi

echo "🧪 1. Submitting SMILES to API: $SMILES"
RESPONSE=$(curl -s -X POST http://localhost:8080/v1/api/jobs \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d "{\"smiles\": \"$SMILES\"}")

# Extract the job_id using grep and cut (works on any Linux/Mac without needing jq installed)
JOB_ID=$(echo $RESPONSE | grep -o '"job_id":"[^"]*' | cut -d'"' -f4)
STATUS=$(echo $RESPONSE | grep -o '"status":"[^"]*' | cut -d'"' -f4)

if [ -z "$JOB_ID" ]; then
  echo "❌ Error: Failed to get job_id from API."
  echo "Response: $RESPONSE"
  exit 1
fi

echo "✅ 2. Got Job ID: $JOB_ID (Status: $STATUS)"

if [ "$STATUS" == "completed" ]; then
  echo "⚡ 3. Cache Hit! No WebSocket needed. Result was inline:"
  echo $RESPONSE
else
  echo "🔌 3. Cache Miss (queued). Connecting to WebSocket to wait for worker..."
  wscat -c "ws://localhost:8080/v1/api/jobs/ws/$JOB_ID" -H "Authorization: Bearer $TOKEN"
fi
