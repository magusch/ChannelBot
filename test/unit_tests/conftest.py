import os
import sys
import pytest
from unittest.mock import patch
import fakeredis
import json

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, project_root)

from test.test_config import TEST_ENV, TEST_SITE_PARAMS

fake_redis = fakeredis.FakeRedis()

fake_redis.setex(
    'parameters:dsn_site',
    3600,  # TTL в секундах
    json.dumps(TEST_SITE_PARAMS)
)

for key, value in TEST_ENV.items():
    os.environ[key] = value

patches = [
    patch('davai_s_nami_bot.celery_app.redis_client', fake_redis),
    patch('davai_s_nami_bot.helper.dsn_parameters.redis_client', fake_redis),
]

for p in patches:
    p.start()

@pytest.fixture(scope="session")
def mock_redis():
    """Fixture for fake redis"""
    return fake_redis 