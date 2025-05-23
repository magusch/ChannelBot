#!/bin/bash
delimiter='**********'

function print {
    echo "$delimiter $1 $delimiter"
}

print 'Load pyenv into environ'
export PYENV_ROTT="$HOME/.pyenv"
export PATH="$PYENV_ROTT/bin:$PATH"

if command -v pyenv 1>/dev/null 2>&1; then
  eval "$(pyenv init -)"
fi

print 'Deactivate virtualenv'
pyenv deactivate

print 'Set python version is 3.7.9'
pyenv local 3.7.9
print "Current python version is $(python --version)"

print 'Delete old virtualenv'
pyenv virtualenv-delete --force channelbot-prod

print 'Create and activate new virtualenv'
pyenv virtualenv channelbot-prod
pyenv activate channelbot-prod
print "Current virtualenv is $(pyenv version)"

pip install --upgrade pip
pip install --no-cache-dir -e .

print 'Runnin service'
python run.py
