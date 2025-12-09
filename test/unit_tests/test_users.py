import json
import pytest
from fastapi import status
from .test_auth import register_user, auth_headers, user_payload


# @pytest.fixture
# def event_payload():
#     return {
#         "id": 111,
#         "event_id": 'test-event-001',
#         "title": "Test Event",
#         "full_text": "This is a test event.",
#         "from_date": "2024-12-31T23:59:59",
#     }

@pytest.fixture
def create_user_event(client, auth_headers, existing_event):
    response = client.post(
        f"/api/users/me/events/{existing_event}",
        headers={
            "Authorization": f"Bearer {auth_headers['access_token']}",
            "Content-Type": "application/json"
        }
    )

    assert response.status_code == status.HTTP_201_CREATED

    return {
        "response": response.json(),
        "auth_headers": auth_headers
    }


def test_create_event_success(create_user_event, existing_event):
    response_data = create_user_event["response"]
    assert response_data["id"] == existing_event
    assert response_data["detail"] == "Event added to favourites"
    assert response_data["type"] == "event"


def test_get_user_events_success(client, create_user_event):
    created_event = create_user_event
    response = client.get(
        "/api/users/me/events",
        headers={
            "Authorization": f"Bearer {created_event['auth_headers']['access_token']}",
            "Content-Type": "application/json"
        }
    )

    assert response.status_code == status.HTTP_200_OK
    response_data = response.json()

    assert len(response_data) == 1
    assert response_data[0]["id"] == created_event["response"]["id"]


def test_delete_event_success(client, create_user_event):
    response_data = create_user_event["response"]
    auth_headers = create_user_event["auth_headers"]
    response = client.delete(
        f"/api/users/me/events/{response_data['id']}",
        headers={
            "Authorization": f"Bearer {auth_headers['access_token']}",
            "Content-Type": "application/json"
        }
    )
    assert response.status_code == status.HTTP_200_OK

    response = client.get(
        "/api/users/me/events",
        headers={
            "Authorization": f"Bearer {auth_headers['access_token']}",
            "Content-Type": "application/json"
        }
    )

    assert response.status_code == status.HTTP_200_OK
    response_data = response.json()

    assert len(response_data) == 0
