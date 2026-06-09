FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY . .
RUN pip install --no-cache-dir -e .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
