from src.media.production import _image_suffix


def test_image_suffix_detects_real_download_format():
    assert _image_suffix(b"\x89PNG\r\n\x1a\n" + b"x" * 20) == ".png"
    assert _image_suffix(b"\xff\xd8\xff" + b"x" * 20) == ".jpg"
    assert _image_suffix(b"RIFF" + b"1234" + b"WEBP" + b"x" * 20) == ".webp"
    assert _image_suffix(b"unknown") == ".img"
