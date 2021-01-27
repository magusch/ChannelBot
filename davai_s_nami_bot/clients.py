import os
import json
from abc import ABC, abstractmethod
from functools import lru_cache

import requests
from telebot import TeleBot


class BaseClient(ABC):
    @abstractmethod
    def send_text(self, id, text):
        """
        Text message to id
        """

    @abstractmethod
    def send_image(self, id, text, image_path, **kwargs):
        """
        Image with text to id
        """


class Telegram(BaseClient):
    def __init__(self):
        self._client = TeleBot(
            token=os.environ.get("BOT_TOKEN"),
            parse_mode="Markdown",
        )

    def send_text(self, id, text):
        return self._client.send_message(
            chat_id=id,
            text=text,
            disable_web_page_preview=True,
        )

    def send_image(self, id, text, image_path):
        with open(image_path, "rb") as image_obj:
            message = self._client.send_photo(
                chat_id=id,
                photo=image_obj,
                caption=text,
            )

        return message

    def send_file(self, id, file_path, mode="r"):
        with open(file_path, mode) as file_obj:
            message = self._client.send_document(id, file_obj)

        return message


class VKRequests(BaseClient):
    """VK-client by send requests to vk-api"""
    api_base_url = "https://api.vk.com/"
    api_urls = dict(
        wall_post=api_base_url + "method/wall.post",
        upload_photo=api_base_url + "method/photos.getUploadServer",
        save_photo=api_base_url + "method/photos.save",
    )

    def __init__(self):
        self._access_params = dict(
            access_token=os.environ.get("VK_TOKEN"),
            expires_in=86_400,
            user_id=os.environ.get("VK_USER_ID"),
            v=5.103,
        )

    def send_text(self, id, text):
        content = dict(
            owner_id=id,
            from_group=1,
            message=text,
        )

        response = requests.post(
            self.api_urls["wall_post"],
            data={
                **self._access_params,
                **content,
            }
        )
        # TODO check response to valid code
        return response.json()

    def send_image(self, id, text, image_path, *, album_id):
        with open(image_path, "rb") as image_obj:
            attachments = self._upload_image_to_album(id, album_id, image_obj)

        response = requests.post(
            url=self.api_urls["wall_post"],
            data=dict(
                **self._access_params,
                owner_id=f"-{id}",
                from_group=1,
                message=text,
                attachments=attachments,
            )
        )

        return response.json()

    def _upload_image_to_album(self, group_id, album_id, image_obj):
        upload_url = self._get_upload_url(group_id, album_id)
        response = requests.post(upload_url, files={"file": image_obj})

        return self._get_photo_attachments_str(response.json())

    @lru_cache()
    def _get_upload_url(self, group_id, album_id):
        response = requests.post(
            url=self.api_urls["upload_photo"],
            data=dict(
                group_id=group_id,
                album_id=album_id,
                **self._access_params,
            )
        )
        return response.json()["response"]["upload_url"]

    def _get_photo_attachments_str(self, params):
        params["album_id"] = params.pop("aid")
        params["group_id"] = params.pop("gid")

        response = requests.get(
            url=self.api_urls["save_photo"],
            params={**params, **self._access_params},
        ).json()

        attachments = list()
        for photo in response["response"]:
            attachments.append(
                f"""photo{photo["owner_id"]}_{photo["id"]}"""
            )

        return ",".join(attachments)


class VK(BaseClient):
    """
    TODO: create VK-client by open-source packages, like
    [vk_api](https://github.com/python273/vk_api) or
    [vkwave](https://github.com/fscdev/vkwave) or
    [vkbottle](https://github.com/timoniq/vkbottle)
    or others
    """
    def send_text(self, id, text):
        pass

    def send_image(self, id, text, image_path):
        pass
