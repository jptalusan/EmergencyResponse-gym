FROM python:3.12

WORKDIR /app

COPY pyproject.toml .
RUN python -m pip install --upgrade pip setuptools wheel
RUN python -m pip install uv

COPY script ./script
COPY src ./src

RUN python -m uv pip install --system .

RUN mkdir -p /data/storage && chmod -R 777 /data/storage
ENV STORAGE_ROOT=/data/storage

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
