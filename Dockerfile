FROM python:3.11-slim

WORKDIR /app

# Los logs deben salir en el momento. Sin esto Python acumula la salida en
# búferes y en Railway parece que la app no registra nada.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dependencias primero: si solo cambia el código, Docker reutiliza esta capa.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El código. El .dockerignore evita que se cuele el .env con las credenciales.
COPY . .

EXPOSE 8000

# Railway inyecta la variable PORT con un valor propio: hay que respetarla o el
# proxy no encuentra el servicio. Por eso el comando va en forma de shell
# (forma exec, ${PORT} no se expande) y por eso se llama a uvicorn directamente
# en vez de "python main.py", que además arrancaba con reload=True.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
