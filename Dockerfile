# Imagem de produção do Atlas AI.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependências primeiro: esta camada só é refeita quando requirements.txt muda.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Roda como usuário sem privilégios; só data/ e reports/ são graváveis.
RUN useradd --create-home --uid 10001 atlas \
    && mkdir -p data reports \
    && chown atlas:atlas data reports
USER atlas

# Plataformas como Render/Railway definem PORT; localmente o padrão é 8000.
ENV PORT=8000
EXPOSE 8000

# Sem --proxy-headers de propósito: veja app/security.py (client_key).
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\""]
