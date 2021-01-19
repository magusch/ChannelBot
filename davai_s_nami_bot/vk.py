import os, requests, re

from io import BytesIO
from PIL import Image

vk_token = os.environ.get("VK_TOKEN")
group_id = os.environ.get("VK_GROUP_ID")
album_id = os.environ.get("VK_ALBUM_ID")
user_id = os.environ.get("VK_USER_ID")
get_end_dict = {'access_token': vk_token, 'expires_in': 86400, 'user_id': user_id, 'v': 5.103}
telegram_url = 'https://t.me/DavaiSNami/'

def vk_post(msg, attachments):
    site = f'https://api.vk.com/method/wall.post'
    data = {
        'owner_id': -1*int(group_id), 'from_group': 1,
        'message': msg, 'attachments': attachments,
    }
    data.update(get_end_dict)
    req = requests.post(site, data=data)
    return req.json()


def create_vk_post(post):
    post = post.replace('Где:', '🏙 Где:').replace('Когда:', '⏰ Когда:').replace('Вход:', '💸 Вход:').replace('Билеты:', '💸 Билеты:').replace('[','').replace(']','').replace('_','').replace('*','')
    url_list = re.findall(r'(\((?:\[??[^\[]*?\)))', post[post.rfind('(http'):]) #TODO: rebuild this stupid
    if len(url_list) > 0:
        url = url_list[0][1:-1]
    else:
        url = ''
    return post, url


def posting_in_vk(event, tm_post_id=None):
    post, url = create_vk_post(event.Post)

    if event.URL!=None:
        url = event.URL
    elif tm_post_id!=None:
        url = telegram_url + str(tm_post_id)

    if event.Image is None:
        attachments = ''
    else:
        upload_photo = VKUpload()
        with Image.open(BytesIO(requests.get(event.Image).content)) as img:
            photo_name = 'img.jpg'
            img.save(photo_name, "jpeg")
            attachments = upload_photo.upload_and_save_photo(filename=photo_name)

    attachments = attachments + url

    vk_post(post, attachments)


class VKUpload:
    def __init__(self, group_id=group_id, album_id=album_id, user_id=user_id, token=vk_token):
        self.get_end_str = f'&access_token={token}&expires_in=86400&user_id={user_id}&v=5.103'
        self.group_id = group_id
        self.album_id = album_id
        self.vk_upload_url = self.vk_url_for_upload()

    def vk_url_for_upload(self):
        site = f'https://api.vk.com/method/photos.getUploadServer?group_id={self.group_id}&album_id={self.album_id}{self.get_end_str}'
        req = requests.get(site).json()
        if 'response' in req:
            vk_upload_url = req['response']['upload_url']
            return vk_upload_url
        else:
            raise ValueError(f"Wrong answer: {req}")

    def upload_and_save_photo(self, filename):
        file = open(filename, 'rb')
        response = self.vk_upload_image(file)
        attachments = self.vk_safe_upload_photo(response)
        return attachments

    def vk_upload_image(self, file):
        files = {'file': file}
        req = requests.post(self.vk_upload_url, files=files).json()
        if 'error' not in req:
            return req
        else:
            raise ValueError(f"Wrong answer: {req}")

    def vk_safe_upload_photo(self, response):
        server = response['server']
        photos_list = response['photos_list']
        photo_hash = response['hash']
        album_id = response['aid']
        site = f'https://api.vk.com/method/photos.save?group_id={self.group_id}&album_id={album_id}&server={server}&photos_list={photos_list}&hash={photo_hash}{self.get_end_str}'
        req = requests.get(site).json()
        if 'response' in req:
            for photo in req['response']:
                owner_id = photo['owner_id']
                photo_id = photo['id']
                attachments = f'photo{owner_id}_{photo_id}'
            return attachments
        else:
            raise ValueError(f"Wrong answer: {req}")