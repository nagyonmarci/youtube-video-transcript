FROM cgr.dev/chainguard/wolfi-base AS build

RUN apk add --no-cache python-3.12-base py3.12-pip

WORKDIR /app

RUN python3.12 -m venv /app/venv
ENV PATH="/app/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM cgr.dev/chainguard/wolfi-base

RUN apk add --no-cache python-3.12-base ffmpeg curl tzdata

WORKDIR /app

COPY --from=build --chown=nonroot:nonroot /app/venv /app/venv
COPY --chown=nonroot:nonroot . .

ENV PATH="/app/venv/bin:$PATH"

USER nonroot

EXPOSE 8000

CMD ["python3.12", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
