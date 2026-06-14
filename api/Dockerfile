FROM python:3.12-slim

WORKDIR /app

RUN pip install uv

COPY api/requirements.txt .
RUN uv pip install --system --no-cache-dir -r requirements.txt

COPY api/ .

EXPOSE 8000

CMD ["python", "main.py"]
