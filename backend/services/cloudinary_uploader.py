from typing import Optional
import os
from fastapi import UploadFile

try:
    import cloudinary
    from cloudinary.uploader import upload as cloudinary_upload
except Exception:
    cloudinary = None

from backend.core.settings import settings


def is_configured() -> bool:
    return bool(settings.cloudinary_cloud_name and settings.cloudinary_api_key and settings.cloudinary_api_secret)


async def upload_file(file: UploadFile, folder: Optional[str] = "comprobantes") -> str:
    """Upload an UploadFile to Cloudinary and return secure_url.
    Raises RuntimeError on failure.
    """
    if cloudinary is None:
        raise RuntimeError("cloudinary package not installed")

    if not is_configured():
        raise RuntimeError("Cloudinary not configured (env vars missing)")

    # Configure cloudinary
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )

    # read bytes
    content = await file.read()
    if not content:
        raise RuntimeError("Empty file")

    try:
        # use upload with bytes
        res = cloudinary_upload(content, folder=folder, resource_type='image')
        url = res.get('secure_url') or res.get('url')
        if not url:
            raise RuntimeError('No url returned from Cloudinary')
        return url
    except Exception as e:
        raise RuntimeError(f'Cloudinary upload failed: {e}')
