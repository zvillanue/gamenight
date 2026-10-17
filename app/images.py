import io
import os
import secrets

from PIL import Image, ImageOps

MAX_PIXELS = 24_000_000
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def save_game_image(file_storage, folder):
    """Validate an uploaded photo and store a re-encoded copy.

    Re-encoding to a fresh JPEG strips EXIF/GPS data and anything that isn't
    pixels, and the stored name is random, never the uploaded one. Returns
    the stored filename; raises ValueError with a user-facing message.
    """
    data = file_storage.read()
    if not data:
        raise ValueError("That image file was empty.")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise ValueError("Images must be JPEG, PNG or WebP.")
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("That image is too large.")
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except ValueError:
        raise
    except Exception:
        raise ValueError("That file doesn't look like a valid image.")
    img.thumbnail((900, 900))
    os.makedirs(folder, exist_ok=True)
    name = secrets.token_hex(16) + ".jpg"
    img.save(os.path.join(folder, name), "JPEG", quality=85, optimize=True)
    return name


def delete_game_image(name, folder):
    if name and name.endswith(".jpg") and "/" not in name and "\\" not in name:
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
