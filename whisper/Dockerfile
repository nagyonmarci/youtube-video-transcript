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
        | head -1 | xargs -I{} cp {} /usr/local/bin/whisper-cli && \
    find build -type f \( -name "libwhisper.so*" -o -name "libggml*.so*" \) \
        -exec cp {} /usr/local/lib/ \;

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy whisper.cpp binary and runtime shared libraries
COPY --from=builder /usr/local/bin/whisper-cli /usr/local/bin/whisper-cli
COPY --from=builder /usr/local/lib/ /usr/local/lib/
RUN ldconfig

RUN mkdir -p /app/models

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/entrypoint.sh
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8001

CMD ["/app/entrypoint.sh"]
