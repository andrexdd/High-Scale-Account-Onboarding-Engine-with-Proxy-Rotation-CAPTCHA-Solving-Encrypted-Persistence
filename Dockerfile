FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libxss1 \
    libappindicator1 \
    libindicator7 \
    fonts-liberation \
    libnss3 \
    lsb-release \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN useradd -m -u 1000 onboarding && chown -R onboarding:onboarding /app
USER onboarding

ENTRYPOINT ["python", "run_simulation.py"]
