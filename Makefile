setup_python:
	chmod +x update_environment.sh
	./update_environment.sh

install:
	pip install --upgrade pip
	pip install --no-cache-dir -e .

install_dev_tools:
	pip install -r requirements-dev.txt

lint_inplace:
	isort --project davai_s_nami_bot .
	black --line-length=89 .
	autoflake --in-place --recursive --remove-all-unused-imports --ignore-init-module-imports .

lint_check:
	isort --check --project davai_s_nami_bot --diff .
	black --check --line-length=89 .
	autoflake --check --recursive --remove-all-unused-imports --ignore-init-module-imports .

test:
	python dump_secrets.py
	pytest --verbose

deploy:
	chmod +x build.sh
	systemctl restart channelbot.service
