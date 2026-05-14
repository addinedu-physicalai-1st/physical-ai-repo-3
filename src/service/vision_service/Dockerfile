FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 9003
EXPOSE 9103/udp

CMD ["python", "-m", "app.main"]
