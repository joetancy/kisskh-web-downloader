from app.services.organizer import jellyfin_names, organize, sanitize_name


def test_jellyfin_filename_and_subtitle():
    assert jellyfin_names("My Show", 1, 2, ".mkv", "en") == (
        "My Show - S01E02.mkv",
        "My Show - S01E02.en.srt",
    )


def test_path_sanitization():
    assert sanitize_name("../Show: Name") == "_Show_ Name"


def test_organize_moves_files(tmp_path):
    source = tmp_path / "work"
    source.mkdir()
    video = source / "video.mkv"
    subtitle = source / "sub.srt"
    video.write_bytes(b"video")
    subtitle.write_text("sub")
    video_out, sub_out = organize(video, subtitle, tmp_path / "media", "Example", 1, 12, "en")
    assert video_out.name == "Example - S01E12.mkv"
    assert sub_out.name == "Example - S01E12.en.srt"
    assert video_out.read_bytes() == b"video"
