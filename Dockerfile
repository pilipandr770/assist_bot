# === Вихідний образ ===
FROM python:3.12-slim

# === Робоча директорія в контейнері ===
WORKDIR /app

# === Копіюємо requirements.txt і встановлюємо залежності ===
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# === Копіюємо весь код бота ===
COPY . .

# === Задаємо змінні середовища для безпечного запуску (можна перезаписати через docker-compose або команду) ===
ENV PYTHONUNBUFFERED=1

# === Стартова команда ===
CMD ["python", "bot.py"]
