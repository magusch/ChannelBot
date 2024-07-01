FROM python:3.9

WORKDIR /app

COPY requirements.txt .

RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libatlas-base-dev \
    gfortran \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip cache purge
RUN pip install --upgrade pip setuptools wheel
RUN pip install -r requirements.txt

COPY . .

ENV CELERY_BROKER_URL=redis://redis:6379/0
ENV CELERY_RESULT_BACKEND=redis://redis:6379/0

ARG SERVICE

ENTRYPOINT ["sh", "-c"]
CMD ["if [ \"$SERVICE\" = \"web\" ]; then uvicorn main:app --host 0.0.0.0 --port 8000; \
      elif [ \"$SERVICE\" = \"celery_worker\" ]; then celery -A davai_s_nami_bot.celery_app worker --loglevel=info; \
      elif [ \"$SERVICE\" = \"celery_beat\" ]; then celery -A davai_s_nami_bot.celery_app beat --loglevel=info; \
      fi"]