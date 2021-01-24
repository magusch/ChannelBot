install:
	pip install --upgrade pip
	pip install pytest autoflake black isort -e .

lint_inplace:
	isort --project davai_s_nami_bot .
	black --line-length=89 .
	autoflake --in-place --recursive --remove-all-unused-imports --ignore-init-module-imports .

lint_check:
	isort --check --project davai_s_nami_bot --diff .
	black --check --line-length=89 .
	autoflake --check --recursive --remove-all-unused-imports --ignore-init-module-imports .

test:
	pytest --verbose

stop:
	pkill -9 python

run:
	python run.py &

deploy:
	VK_ALBUM_ID=$VK_DEV_ALBUM_ID
	VK_GROUP_ID=$VK_DEV_GROUP_ID
	CHANNEL_ID=$DEV_CHANNEL_ID
	make stop
	make run
