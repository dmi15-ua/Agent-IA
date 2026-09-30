FROM python:3.11-slim

WORKDIR /app

# Copiar requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código
COPY . .

# Puerto que usa FastAPI
EXPOSE 8000

# Comando para correr
CMD ["python", "main.py"]