setup_python:
	chmod +x update_environment.sh
	./update_environment.sh

install:
	pyenv activate channelbot-ci
	pip install --upgrade pip
	pip install --no-cache-dir -e .

install_dev_tools:
	pyenv activate channelbot-ci
	pip install -r requirements-dev.txt

lint_inplace:
	pyenv activate channelbot-ci
	isort --project davai_s_nami_bot .
	black --line-length=89 .
	autoflake --in-place --recursive --remove-all-unused-imports --ignore-init-module-imports .

lint_check:
	pyenv activate channelbot-ci
	isort --check --project davai_s_nami_bot --diff .
	black --check --line-length=89 .
	autoflake --check --recursive --remove-all-unused-imports --ignore-init-module-imports .

test:
	pyenv activate channelbot-ci
	python dump_secrets.py
	pytest --verbose

deploy:
	pyenv activate channelbot-ci
	chmod +x build.sh
	systemctl restart channelbot.service
