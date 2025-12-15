import hmac
import hashlib
import json, os
import urllib.parse
from typing import Dict, Any
import datetime

TEST_BOT_TOKEN = os.environ['BOT_TOKEN']


def generate_telegram_init_data(
        user_data: Dict[str, Any],
        bot_token: str = os.environ['BOT_TOKEN'],
        #auth_date: int = datetime.time()
) -> str:
    """
   Generates a Telegram WebApp initData string with a valid hash for testing purposes.

    Args:
        user_data: dict with user data (id, first_name, etc.).
        bot_token: Telegram bot token used to generate the hash.
    """

    user_str = json.dumps(user_data, separators=(',', ':'))


    params_for_hash = {
        #'auth_date': str(auth_date),
        'user': user_str,
        'signature': 'test_signature',
        'query_id': 'test_query_id'

    }

    # Sort and format string 'key=value\nkey2=value2...'
    data_check_string_parts = []
    for key in sorted(params_for_hash.keys()):
        data_check_string_parts.append(f"{key}={params_for_hash[key]}")

    data_check_string = '\n'.join(data_check_string_parts)

    # Calculate Secret Key (SHA256(BOT_TOKEN))
    secret_key = hmac.new(
        "WebAppData".encode('utf-8'),
        bot_token.encode('utf-8'),
        hashlib.sha256
    ).digest()

    # Calculate HMAC-SHA256 hash
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    final_params = {**params_for_hash, 'hash': calculated_hash}


    final_init_data = []
    for key, value in final_params.items():
        if key == 'user':
            final_init_data.append(f"user={urllib.parse.quote(value)}")
        else:
            final_init_data.append(f"{key}={value}")

    return '&'.join(final_init_data)