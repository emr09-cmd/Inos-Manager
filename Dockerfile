FROM python:3.12-slim

WORKDIR /app

# system dependencies (important for discord.py voice / PyNaCl)
RUN apt-get update && apt-get install -y \
    build-essential \
    libffi-dev \
    libnacl-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]