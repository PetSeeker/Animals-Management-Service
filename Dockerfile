FROM python:3.10-slim

WORKDIR /app

COPY . /app

COPY ./requirements.txt .

RUN pip install --upgrade pip

RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python3", "main.py"]
