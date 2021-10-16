import os, datetime
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any, Dict, Union

import requests
from markdown import markdown
from telebot import TeleBot

from . import database
from . import events


def format_text(text: str, style: str = None):
    """
    Редактирование форматирования (только для ВКонтакте)
    """
    if style == "vk":
        formatted = (
            text.replace("Где:", "🏙 Где:")
            .replace("Когда:", "⏰ Когда:")
            .replace("Вход:", "💸 Вход:")
            .replace("Билеты:", "💸 Билеты:")
            .replace("[", "")
            .replace("]", "")
            .replace("_", "")
            .replace("*", "")
        )

    else:
        formatted = text

    return formatted


class BaseClient(ABC):
    constants: Dict[str, Dict[str, Union[str, int]]]
    name: ""
    formatter_style = ""

    def send_post(self, event: events.Event, image_path: str, environ: str = "prod"):
        text = format_text(event.post, style=self.formatter_style)

        if image_path is None or '':
            return self.send_text(
                text=text,
                **self.constants.get(environ, {}),
            )

        return self.send_image(
            text=text,
            image_path=image_path,
            **self.constants.get(environ, {}),
        )

    @abstractmethod
    def send_text(self, *args, **kwargs):
        """
        Text message
        """

    @abstractmethod
    def send_image(self, *args, **kwargs):
        """
        Image with text
        """


class Telegram(BaseClient):
    constants = dict(
        prod={"destination_id": os.environ.get("CHANNEL_ID")},
        dev={"destination_id": os.environ.get("DEV_CHANNEL_ID")},
    )
    name = "telegram_channel"
    formatter_style = None

    def __init__(self):
        self._client = TeleBot(
            token=os.environ.get("BOT_TOKEN"),
            parse_mode="markdown",
        )

    def send_post(self, event: events.Event, image_path: str, environ: str = "prod"):
        message = super().send_post(event, image_path, environ=environ)
        #explored_date = datetime.datetime.now()
        database.add_event_for_telegram(event, message.message_id)
        #database.add(event, 'dev_events', message.message_id, explored_date) #TODO: post in special table (idk)

    def send_text(self, text: str, *, destination_id: Union[int, str]):
        return self._client.send_message(
            chat_id=destination_id,
            text=text,
            disable_web_page_preview=True,
        )

    def send_image(
        self, text: str, image_path: str, *, destination_id: Union[int, str]
    ):
        with open(image_path, "rb") as image_obj:
            message = self._client.send_photo(
                chat_id=destination_id,
                photo=image_obj,
                caption=text,
            )

        return message

    def send_file(
        self, destination_id: Union[int, str], file_path: str, mode: str = "r"
    ):
        with open(file_path, mode) as file_obj:
            message = self._client.send_document(destination_id, file_obj)

        return message


class VKRequests(BaseClient):
    """VK-client by send requests to vk-api"""

    api_base_url: str = "https://api.vk.com/"
    api_urls = dict(
        wall_post=api_base_url + "method/wall.post",
        upload_photo=api_base_url + "method/photos.getUploadServer",
        save_photo=api_base_url + "method/photos.save",
        upload_photo_wall=api_base_url + "method/photos.getWallUploadServer",
        save_photo_wall=api_base_url + "method/photos.saveWallPhoto",
    )
    constants = dict(
        prod={
            "destination_id": os.environ.get("VK_GROUP_ID"),
        },
        dev={
            "destination_id": os.environ.get("VK_DEV_GROUP_ID"),
        },
    )
    name = "vk_group"
    formatter_style = "vk"

    def __init__(self):
        self._access_params = dict(
            access_token=os.environ.get("VK_TOKEN"),
            expires_in=86_400,
            user_id=os.environ.get("VK_USER_ID"),
            v=5.103,
        )

    def send_text(self, text: str, *, destination_id: Union[int, str], **kwargs):
        content = dict(
            owner_id=destination_id,
            from_group=1,
            message=text,
        )

        return _requests_post(
            url=self.api_urls["wall_post"],
            data={**self._access_params, **content},
            return_key=None,
        )

    def send_image(
        self,
        text: str,
        image_path: str,
        *,
        destination_id: Union[int, str],
    ):
        with open(image_path, "rb") as image_obj:
            attachments = self._upload_image_to_wall(destination_id, image_obj)

        return _requests_post(
            url=self.api_urls["wall_post"],
            data={
                **self._access_params,
                "owner_id": f"-{destination_id}",
                "from_group": 1,
                "message": text,
                "attachments": attachments,
            },
            return_key=None,
        )

    def _upload_image_to_wall(self, group_id: Union[int, str], image_obj: Any):
        upload_url = self._get_wall_upload_url(group_id)

        upload_images = _requests_post(
            url=upload_url,
            files={"file": image_obj},
            return_key=None,
        )

        return self._get_photo_attachments_str_wall(upload_images, group_id)

    @lru_cache()
    def _get_wall_upload_url(self, group_id: Union[int, str]):
        return _requests_post(
            url=self.api_urls["upload_photo_wall"],
            data=dict(
                group_id=group_id,
                **self._access_params,
            ),
        )["upload_url"]

    def _get_photo_attachments_str_wall(self, params: Dict[str, str], group_id):
        params["group_id"] = group_id

        upload_photos = _requests_get(
            url=self.api_urls["save_photo_wall"],
            params={**params, **self._access_params},
        )

        attachments = list()
        for photo in upload_photos:
            attachments.append(f"""photo{photo["owner_id"]}_{photo["id"]}""")

        return ",".join(attachments)


class VK:
    """
    TODO: create VK-client by open-source packages, like
    [vk_api](https://github.com/python273/vk_api) or
    [vkwave](https://github.com/fscdev/vkwave) or
    [vkbottle](https://github.com/timoniq/vkbottle)
    or others
    """

    name = ""
    constants = dict(prod={}, dev={})

    def send_text(self, *args, **kwargs):
        pass

    def send_image(self, *args, **kwargs):
        pass


class DevClient(Telegram):
    """
    Клиент для отправки сообщений в dev канал.
    """

    def send_text(self, text: str):
        super().send_text(text, **super().constants["dev"])

    def send_file(self, path: str, mode: str = "r", with_remove: bool = False):
        super().send_file(file_path=path, mode=mode, **super().constants["dev"])

        if with_remove:
            with open(path, "r+b") as file:
                file.truncate(0)
                file.write(b"")


class Clients:
    def __init__(self):
        self._clients = [cls() for cls in BaseClient.__subclasses__()]

    def send_post(self, *args, **kwargs):
        for client in self._clients:
            client.send_post(*args, **kwargs)


def _requests_get(url, params: Dict[str, Any], return_key: str = "response"):
    return _check_response(requests.get(url=url, params=params), return_key=return_key)


def _requests_post(
    url,
    data: Dict[str, Any] = None,
    json: Dict[str, Any] = None,
    files: Dict[str, Any] = None,
    return_key: str = "response",
):
    return _check_response(
        requests.post(url=url, data=data, json=json, files=files), return_key=return_key
    )


def _check_response(response: requests.Response, return_key: str):
    err_msg = ""

    if response.ok:
        data = response.json()
    else:
        raise requests.exceptions.RequestException(
            f"Response status code is {response.status_code}"
        )

    if return_key is None:
        return data

    if return_key in data:
        return data[return_key]

    raise requests.exceptions.RequestException(
        f"Key {return_key!r} not found in response:\n" f"{response.text}"
    )
