# Stage 1: Build whisper.cpp
FROM ubuntu:22.04 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch v1.7.3 https://github.com/ggerganov/whisper.cpp.git /whisper.cpp

WORKDIR /whisper.cpp
RUN cmake -B build -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build --config Release -j$(nproc) && \
    # Binary is named 'whisper-cli' in newer versions, 'main' in older ones
    find build/bin -maxdepth 1 -type f \( -name "whisper-cli" -o -name "main" \) \
        | head -1 | xargs -I{} cp {} /usr/local/bin/whisper-cli

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy whisper.cpp binary
COPY --from=builder /usr/local/bin/whisper-cli /usr/local/bin/whisper-cli

# Download model at build time
ARG WHISPER_MODEL=ggml-large-v3.bin
RUN mkdir -p /app/models && \
    curl -L -o /app/models/${WHISPER_MODEL} \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${WHISPER_MODEL}

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
