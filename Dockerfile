FROM python:3.9-slim AS base

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libssl-dev \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    gfortran \
    libblas-dev \
    liblapack-dev \
    libatlas-base-dev \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip cache purge
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

FROM base AS dependencies

COPY . .

ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0


ENTRYPOINT ["sh", "-c"]
CMD ["echo SERVICE=$SERVICE; \
      if [ \"$SERVICE\" = \"fastapi_app\" ]; then uvicorn main:app --host 0.0.0.0 --port 8005 --reload; \
      elif [ \"$SERVICE\" = \"celery_worker\" ]; then celery -A davai_s_nami_bot.celery_app worker --loglevel=info; \
      elif [ \"$SERVICE\" = \"celery_beat\" ]; then celery -A davai_s_nami_bot.celery_app beat --loglevel=info; \
      else echo \"Unknown service: $SERVICE\"; exit 1; fi"]