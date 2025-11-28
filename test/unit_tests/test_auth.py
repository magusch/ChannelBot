import json
from fastapi import status


def test_register_user_success(client):
    user_data = {
        "email": "test@example.com",
        "password": "securepassword123",
        "first_name": "Test",
        "last_name": "User",
        "telegram_nickname": "testuser"
    }

    response = client.post(
        "/api/auth/register",
        data=json.dumps(user_data)
    )

    assert response.status_code == status.HTTP_201_CREATED

    response_data = response.json()
    assert "id" in response_data
    assert response_data["email"] == user_data["email"]
    assert response_data["is_active"] is True

    assert "hashed_password" not in response_data
    assert "password" not in response_data


def test_register_user_success_without_full_info(client):

    user_data = {
        "email": "test@example.com",
        "password": "securepassword123",
    }

    response = client.post(
        "/api/auth/register",
        data=json.dumps(user_data)
    )

    assert response.status_code == status.HTTP_201_CREATED

    response_data = response.json()
    assert "id" in response_data
    assert response_data["email"] == user_data["email"]


def test_register_duplicate_email(client):

    user_data = {
        "email": "duplicate@example.com",
        "password": "securepassword123"
    }

    response_ok = client.post(
        "/api/auth/register",
        data=json.dumps(user_data)
    )
    assert response_ok.status_code == status.HTTP_201_CREATED

    response_fail = client.post(
        "/api/auth/register",
        data=json.dumps(user_data)
    )

    assert response_fail.status_code == status.HTTP_400_BAD_REQUEST
    assert "User exists. Email is not unique" in response_fail.json()["detail"]


def test_register_missing_field(client):

    user_data = {
        "email": "incomplete@example.com"
    }

    response = client.post(
        "/api/auth/register",
        data=json.dumps(user_data)
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    assert "password" in response.json()["detail"][0]["loc"]