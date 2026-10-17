# Image for both the Blog API and the Blog MCP server (same code, different command).
FROM python:3.13-slim
# AWS Lambda Web Adapter: on Lambda it forwards invocations to the web server below as
# plain HTTP (with response streaming). Outside Lambda it is inert.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter
COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /usr/local/bin/uv
WORKDIR /app
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt
COPY backend ./backend
COPY mcp_server ./mcp_server
RUN useradd --system --no-create-home app
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]
