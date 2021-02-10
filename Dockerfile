FROM ubuntu:20.04
MAINTAINER Your Name "artem.ermulin@ya.ru"

RUN apt update
RUN apt install wget -y
RUN apt install make -y
RUN apt install build-essential -y
RUN apt install libssl-dev -y
RUN apt install gcc -y
RUN apt install curl -y
RUN apt install git-core -y
RUN apt install gcc -y
RUN apt install zlib1g-dev -y
RUN apt install libbz2-dev -y
RUN apt install libreadline-dev -y
RUN apt install libsqlite3-dev -y
RUN apt install libssl-dev -y
RUN apt install libffi-dev -y
RUN apt install liblzma-dev -y
RUN apt install llvm -y
RUN apt install libncurses5-dev -y
RUN apt install libncursesw5-dev -y
RUN apt install xz-utils -y
RUN apt install python-openssl -y
RUN git clone https://github.com/pyenv/pyenv.git $HOME/.pyenv
RUN git clone https://github.com/yyuu/pyenv-virtualenv.git   $HOME/.pyenv/plugins/pyenv-virtualenv
RUN echo $'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
RUN echo $'export PATH="$PYENV_ROOT/bin:$PATH"\n' >> ~/.bashrc
RUN echo $'if command -v pyenv 1>/dev/null 2>&1; then' >> ~/.bashrc
RUN echo $'  eval "$(pyenv init -)"' >> ~/.bashrc
RUN echo $'fi' >> ~/.bashrc
RUN . ~/.bashrc
RUN pyenv install 3.7.7
RUN pyenv global 3.7.7
RUN pip install --upgrade pip

COPY . /app
WORKDIR /app
RUN pip install -e .
ENTRYPOINT ["python"]
CMD ["update_tables.py"]
