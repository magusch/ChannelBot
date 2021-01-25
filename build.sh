pyenv deactivate
pyenv local 3.7.9
pyenv virtualenv-delete --force channelbot-prod
pyenv virtualenv channelbot-prod
source ~/.bashrc
pyenv activate channelbot-prod

pip install --upgrade pip
pip install --no-cache-dir -e .

python run.py
