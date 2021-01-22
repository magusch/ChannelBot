install:
	pip install --upgrade pip
	pip install pytest autoflake black isort -e .

lint_inplace:
	isort --project davai_s_nami_bot --diff .
	black --line-length=89 .
	autoflake --recursive --remove-all-unused-imports --ignore-init-module-imports .

lint_check:
	isort --check --project davai_s_nami_bot --diff .
	black --check --line-length=89 .
	autoflake --check --recursive --remove-all-unused-imports --ignore-init-module-imports .

test:
	pytest --verbose
