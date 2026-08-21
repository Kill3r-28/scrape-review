FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

COPY pyproject.toml README.md ./
COPY scrape.py review.py main.py prompts.md rxconfig.py ./
COPY tickets ./tickets
COPY dashboard ./dashboard

RUN pip install --upgrade pip \
    && pip install \
      "fastapi>=0.115.0" \
      "uvicorn[standard]>=0.30.0" \
      "sqlalchemy>=2.0.0" \
      "jinja2>=3.1.0" \
      "python-multipart>=0.0.9" \
      "psycopg[binary]>=3.2.0" \
      "requests>=2.32.0" \
      "beautifulsoup4>=4.12.0"

EXPOSE 8000
CMD ["sh", "-c", "uvicorn tickets.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
