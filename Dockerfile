# Stage 1: Install dependencies
FROM python:3.9-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmariadb-dev \
    libmariadb-dev-compat \
    tzdata \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN pip install --no-cache-dir --target=/app/packages -r requirements.txt

# Stage 2: Build the final runtime container
FROM python:3.9-slim

WORKDIR /app

ENV TZ=UTC

COPY --from=builder /app/packages /usr/local/lib/python3.9/site-packages
COPY . /app

EXPOSE 4000

CMD ["python", "api.py"]
