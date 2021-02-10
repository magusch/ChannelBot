FROM ubuntu:20.04
MAINTAINER Your Name "artem.ermulin@ya.ru"

RUN apt update
RUN apt install -y python
RUN apt install -y python-pip python-dev build-essential

COPY . /app
WORKDIR /app
RUN pip install -e .
ENTRYPOINT ["python"]
CMD ["update_tables.py"]
