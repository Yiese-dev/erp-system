FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
WORKDIR /app
COPY packages/campus_common/requirements.txt packages/campus_common/requirements.txt
COPY services/identity/requirements.txt services/identity/requirements.txt
COPY services/academic/requirements.txt services/academic/requirements.txt
COPY services/finance/requirements.txt services/finance/requirements.txt
COPY services/hr/requirements.txt services/hr/requirements.txt
RUN pip install -r services/identity/requirements.txt -r services/academic/requirements.txt \
	-r services/finance/requirements.txt -r services/hr/requirements.txt
COPY packages packages
COPY services/identity/app services/identity/app
COPY services/academic/app services/academic/app
COPY services/finance/app services/finance/app
COPY services/hr/app services/hr/app
ENTRYPOINT ["python"]
