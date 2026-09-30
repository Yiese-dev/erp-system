FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
WORKDIR /app
COPY packages/campus_common/requirements.txt packages/campus_common/requirements.txt
COPY services/identity/requirements.txt services/identity/requirements.txt
RUN pip install -r services/identity/requirements.txt
COPY packages/campus_common packages/campus_common
COPY services/identity/app services/identity/app
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin campus
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=2)"
CMD ["uvicorn", "services.identity.app.main:application", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--forwarded-allow-ips", "*"]
