FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
WORKDIR /app
COPY requirements-dev.txt requirements-dev.txt
RUN pip install -r requirements-dev.txt
COPY packages packages
COPY services/identity/app services/identity/app
COPY services/academic/app services/academic/app
COPY services/finance/app services/finance/app
COPY services/hr/app services/hr/app
ENTRYPOINT ["python"]
