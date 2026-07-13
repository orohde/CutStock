FROM python:3.12-slim

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY core/ core/
COPY web/ web/
COPY ui/__init__.py ui/
COPY ui/i18n.py ui/

ENV CUTSTOCK_DB=/data/cutstock.db

EXPOSE 8000

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
