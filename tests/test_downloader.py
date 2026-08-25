import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from techradar import downloader

def test_video_id_forms():
    cases = [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/abc123defGH", "abc123defGH"),
        ("https://www.youtube.com/watch?app=desktop&v=xyz11122233&feature=share", "xyz11122233"),
        ("https://m.notyoutube.com/x", None),
    ]
    for url, exp in cases:
        assert downloader.video_id(url) == exp, (url, downloader.video_id(url))

def test_download_bad_format_field():
    # download() always returns a state dict with queued/active status
    st = downloader.download("https://www.youtube.com/watch?v=dQw4w9WgXcQ", fmt="mp4")
    assert st["status"] in ("queued", "downloading", "done", "error")
    assert st["fmt"] == "mp4"

def test_download_dir_created():
    assert os.path.isdir(downloader.DOWNLOAD_DIR)

def test_file_path_rejects_traversal():
    assert downloader.file_path("../../etc/passwd") is None
