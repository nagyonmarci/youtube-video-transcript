#!/bin/sh
set -e

MODEL_PATH="${WHISPER_MODEL_PATH:-/app/models/ggml-large-v3.bin}"
MODEL_FILE=$(basename "$MODEL_PATH")

if [ ! -f "$MODEL_PATH" ]; then
  echo "Downloading Whisper model: $MODEL_FILE"
  curl -L -o "$MODEL_PATH" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${MODEL_FILE}"
  echo "Model downloaded."
else
  echo "Whisper model already present: $MODEL_PATH"
fi

exec uvicorn main:app --host 0.0.0.0 --port 8001
