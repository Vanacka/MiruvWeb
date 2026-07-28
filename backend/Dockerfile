FROM python:3.11-slim

WORKDIR /app

# Systémové závislosti - build-essential kvůli balíčkům jako psycopg2, Pillow apod.
# (klidně smaž, pokud je nepotřebuješ, ušetříš si tím čas při buildu)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Nejdřív jen requirements.txt, ať se cachuje instalace závislostí
# a nerebuilduje se to znovu jen kvůli změně v main.py
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Zbytek kódu se stejně přemountuje přes volume v docker-compose,
# ale hodí se to i tady kvůli buildu produkčního image
COPY . .

EXPOSE 8000

# --reload sleduje změny v souborech a restartuje server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
