FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /usr/local/bin/uv
WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt
COPY backend ./backend
RUN useradd --system --no-create-home app
USER app
ENV PYTHONUNBUFFERED=1
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8102"]
