import pytest
import json
from fastapi import status


@pytest.fixture
def user_payload():
    return {
        "nickname": "testuser",
        "email": "tokenuser@example.com",
        "password": "testpassword123",
        "full_name": "Test User",
    }


@pytest.fixture
def register_user(client, user_payload):
    response = client.post(
        "/api/auth/register",
        data=json.dumps(user_payload),
    )
    assert response.status_code == status.HTTP_201_CREATED
    return response.json()


@pytest.fixture
def auth_headers(client, register_user, user_payload):
    """
    Делает логин под зарегистрированным пользователем
    и возвращает готовые заголовки с токеном.
    """
    response = client.post(
        "/api/auth/login",
        data=json.dumps(user_payload),
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == status.HTTP_200_OK
    return response.json()


def test_register_user_success(register_user, user_payload):
    assert "id" in register_user
    assert register_user["email"] == user_payload["email"]
    assert register_user["is_active"] is True

    assert "hashed_password" not in register_user
    assert "password" not in register_user


def test_register_user_success_without_full_info(client):

    user_data = {
        "nickname": "testuser",
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


def test_register_duplicate_email(client, register_user, user_payload):
    response_fail = client.post(
        "/api/auth/register",
        data=json.dumps(user_payload)
    )

    assert response_fail.status_code == status.HTTP_400_BAD_REQUEST
    assert "User exists. Email is not unique" in response_fail.json()["detail"]


def test_register_missing_field(client):

    user_data = {
        "nickname": "testuser",
        "email": "incomplete@example.com"
    }

    response = client.post(
        "/api/auth/register",
        data=json.dumps(user_data)
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    assert "password" in response.json()["detail"][0]["loc"]


def test_login_success(auth_headers):
    response_data = auth_headers
    assert "access_token" in response_data
    assert response_data["token_type"] == "bearer"


def test_login_fail_wrong_password(client, register_user):
    user_data = register_user
    wrong_password_payload = {
        "nickname": user_data["nickname"],
        "password": "wrongpassword"
    }

    response = client.post(
        "/api/auth/login",
        data=json.dumps(wrong_password_payload),
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert "Incorrect nickname or password" in response.json()["detail"]


def test_login_and_me_success(client, auth_headers, user_payload):
    response_data = auth_headers
    assert "access_token" in response_data

    response_me = client.get(
        "/api/auth/me",
        headers={
            "Authorization": f"Bearer {response_data['access_token']}",
            "Content-Type": "application/json"
        }
    )
    assert response_me.status_code == status.HTTP_200_OK
    me_data = response_me.json()
    assert me_data["full_name"] == user_payload["full_name"]


def test_update_user(client, auth_headers):
    response_data = auth_headers
    assert "access_token" in response_data

    new_full_name = "editeduser"

    response_edit = client.put(
        "/api/auth/me",
        data=json.dumps({"full_name": new_full_name}),
        headers={
            "Authorization": f"Bearer {response_data['access_token']}",
            "Content-Type": "application/json"
        }
    )

    assert response_edit.status_code == status.HTTP_200_OK
    edited_data = response_edit.json()
    assert edited_data["full_name"] == new_full_name
