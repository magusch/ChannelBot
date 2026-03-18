import os, io
import uuid
import logging
import warnings

import requests
from PIL import Image
from pillow_heif import register_heif_opener
import boto3

log = logging.getLogger(__name__)

register_heif_opener()

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_S3_ENDPOINT_URL = os.getenv("AWS_S3_ENDPOINT_URL")

s3_client = boto3.client("s3", region_name=AWS_REGION,
                         aws_access_key_id=AWS_ACCESS_KEY_ID,
                         aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                         aws_session_token=AWS_SECRET_ACCESS_KEY,
                         endpoint_url=AWS_S3_ENDPOINT_URL
                         )


CONSTANTS_FILE_NAME = "prod_constants"
WEEKNAMES = {
    0: "Пн",
    1: "Вт",
    2: "Ср",
    3: "Чт",
    4: "Пт",
    5: "Сб",
    6: "Вск",
}
MONTHNAMES = {
    1: "января",
    2: "февраля",
    3: "марта",
    4: "апреля",
    5: "мая",
    6: "июня",
    7: "июля",
    8: "августа",
    9: "сентября",
    10: "октября",
    11: "ноября",
    12: "декабря",
}

THUMB_RESAMPLE = Image.LANCZOS
IMG_MAXSIZE = (1920, 1080)

REQUIRED_CONSTANT_NAMES = [
    "TIMEPAD_TOKEN",
    "BOT_TOKEN",
    "DATABASE_URL",
    "CHANNEL_ID",
    "DEV_CHANNEL_ID",
    "VK_TOKEN",
    "VK_USER_ID",
    "VK_GROUP_ID",
    "VK_DEV_GROUP_ID",
    "DSN_USERNAME",
    "DSN_PASSWORD",
    "DSN_DATABASE_URL",
    "VK_ID",
    "BASE_URL",
    "API_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
]


def read_constants():
    if os.path.exists(CONSTANTS_FILE_NAME):
        warnings.warn(
            message=(
                "Reading constants from file 'prod_constants' will be removed "
                "in future versions."
            ),
            category=DeprecationWarning,
        )

        missing_constants = set(REQUIRED_CONSTANT_NAMES)

        with open(CONSTANTS_FILE_NAME) as file:
            for line in file:
                tag, value = line.split()

                os.environ[tag] = value

                missing_constants -= {tag}

        for constant_name in missing_constants:
            if constant_name in os.environ:
                missing_constants -= {constant_name}

        if missing_constants:
            raise ValueError(
                "Some constants in 'prod_constants' are missing: {}".format(
                    ", ".join(missing_constants)
                )
            )

    else:
        for key in REQUIRED_CONSTANT_NAMES:
            if key not in os.environ:
                raise ValueError(f"Constant {key} not found in environ.")


def prepare_image(image_url):
    if image_url is None or isinstance(image_url, list) or image_url=='':
        image_path = None

    else:
        with Image.open(io.BytesIO(requests.get(image_url).content)) as img:
            image_name = "img"
            img.thumbnail(IMG_MAXSIZE, THUMB_RESAMPLE)

            if img.mode != "RGB":
                img = img.convert("RGB")

            # TODO: if line above work fine, this isn't necessary
            if img.mode == "CMYK":
                # can't save CMYK as PNG
                img.save(image_name + ".jpg", "jpeg")
                image_path = image_name + ".jpg"

            else:
                img.save(image_name + ".png", "png")
                img.save(image_name + ".jpg", "jpeg")

                image_size = os.path.getsize(image_name + ".png") / 1_000_000

                if image_size > 5:
                    image_path = image_name + ".jpg"
                else:
                    image_path = image_name + ".png"

    return image_path


def download_image(url: str) -> bytes:
    resp = requests.get(url, stream=True, timeout=10)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    if not content_type.startswith("image/"):
        raise ValueError(f"URL does not look like image, Content-Type={content_type}")

    return resp.content

def convert_to_jpg(image_bytes: bytes) -> tuple[bytes, str]:
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        raise ValueError(f"Cannot open image: {e}")


    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    elif img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90,  optimize=True)
    buf.seek(0)
    return buf.read(), "jpg"


def upload_bytes_to_s3(bytes, ext: str) -> dict:
    """
    Uploads bytes to s3 bucket and return url.
    """
    aws_s3_bucket = os.environ.get("AWS_STORAGE_BUCKET_NAME")
    s3_public_url = os.environ.get("AWS_S3_PUBLIC_URL")

    key = f"uploads/{uuid.uuid4().hex}.{ext}"

    s3_client.put_object(
        Bucket=aws_s3_bucket,
        Key=key,
        Body=bytes,
        ContentType="image/jpeg",
        ContentEncoding="identity",
        ContentDisposition="inline",
        CacheControl="public, max-age=31536000",
        ACL="public-read",
    )
    if s3_public_url:
        url = f"https://{s3_public_url.rstrip('/')}/{key}"
    else:
        url = f"https://{aws_s3_bucket}.s3.{AWS_REGION}.amazonaws.com/{key}"
    return {
        "bucket": aws_s3_bucket,
        "key": key,
        "url": url,
    }


def process_image_from_url(image_url: str) -> dict:
    """
    1) Download image by url
    2) Convert image to jpg
    3) Upload image to S3
    4) Return dict with image url
    """
    if not image_url.startswith("http://") and not image_url.startswith("https://"):
        raise ValueError("image_url must be http(s) link")

    original_bytes = download_image(image_url)
    jpg_bytes, ext = convert_to_jpg(original_bytes)
    result = upload_bytes_to_s3(jpg_bytes, ext)
    result["source_url"] = image_url
    return result


def _crop_center(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize and crop image to fill target dimensions (center crop)."""
    src_ratio = img.width / img.height
    target_ratio = target_w / target_h

    if src_ratio > target_ratio:
        # Image is wider — fit by height, crop sides
        new_h = target_h
        new_w = int(target_h * src_ratio)
    else:
        # Image is taller — fit by width, crop top/bottom
        new_w = target_w
        new_h = int(target_w / src_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def create_collage(image_urls: list, gap: int = 3, output_width: int = 1200) -> bytes:
    """Create a collage from image URLs.

    Layout:
    - 1 image: single image resized
    - 2 images: 2 in a row
    - 3 images: 3 in a row
    - 4+ images: 2x2 grid (first 4)

    Returns JPEG bytes.
    """
    images = []
    for url in image_urls:
        if not url or not url.startswith("http"):
            continue
        try:
            img_bytes = download_image(url)
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            elif img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[-1])
                img = bg
            images.append(img)
        except Exception as e:
            log.warning(f"Failed to download image {url}: {e}")
            continue

        if len(images) >= 4:
            break

    if not images:
        raise ValueError("No valid images to create collage")

    count = len(images)
    bg_color = (255, 255, 255)

    if count == 1:
        # Single image: fit into max size without cropping
        img = images[0]
        max_w, max_h = output_width, int(output_width * 0.75)
        img.thumbnail((max_w, max_h), Image.LANCZOS)
        collage = img

    elif count == 2:
        cell_w = (output_width - gap) // 2
        cell_h = int(cell_w * 1.0)  # square cells
        collage = Image.new("RGB", (output_width, cell_h), bg_color)
        for i, img in enumerate(images):
            cropped = _crop_center(img, cell_w, cell_h)
            x = i * (cell_w + gap)
            collage.paste(cropped, (x, 0))

    elif count == 3:
        cell_w = (output_width - gap * 2) // 3
        cell_h = int(cell_w * 1.2)  # slightly tall
        collage = Image.new("RGB", (output_width, cell_h), bg_color)
        for i, img in enumerate(images):
            cropped = _crop_center(img, cell_w, cell_h)
            x = i * (cell_w + gap)
            collage.paste(cropped, (x, 0))

    else:  # 4+
        cell_w = (output_width - gap) // 2
        cell_h = int(cell_w * 0.75)  # 4:3 cells
        total_h = cell_h * 2 + gap
        collage = Image.new("RGB", (output_width, total_h), bg_color)
        positions = [(0, 0), (cell_w + gap, 0), (0, cell_h + gap), (cell_w + gap, cell_h + gap)]
        for i, img in enumerate(images[:4]):
            cropped = _crop_center(img, cell_w, cell_h)
            collage.paste(cropped, positions[i])

    buf = io.BytesIO()
    collage.save(buf, format="JPEG", quality=88, optimize=True)
    buf.seek(0)
    return buf.read()


def create_collage_and_upload(image_urls: list) -> dict:
    """Create collage from image URLs and upload to S3.

    Returns dict with S3 url, or None if no valid images.
    """
    if not image_urls:
        return None

    # Filter valid URLs
    valid_urls = [u for u in image_urls if u and isinstance(u, str) and u.startswith("http")]
    if not valid_urls:
        return None

    try:
        collage_bytes = create_collage(valid_urls)
        result = upload_bytes_to_s3(collage_bytes, "jpg")
        result["source_count"] = min(len(valid_urls), 4)
        return result
    except Exception as e:
        log.error(f"Failed to create collage: {e}")
        return None
