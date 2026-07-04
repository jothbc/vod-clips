from reels.publish_youtube import apply_youtube_format


def test_apply_youtube_format_video_unchanged():
    title, desc, tags = apply_youtube_format("Title", "Desc", ["game"], "video")
    assert title == "Title"
    assert desc == "Desc"
    assert tags == ["game"]


def test_apply_youtube_format_shorts_adds_hashtag_and_tag():
    title, desc, tags = apply_youtube_format("Clip", "My clip", ["game"], "shorts")
    assert title == "Clip"
    assert "#Shorts" in desc
    assert tags[0] == "Shorts"
    assert "game" in tags


def test_apply_youtube_format_shorts_skips_duplicate():
    title, desc, tags = apply_youtube_format("T", "Already #Shorts", ["Shorts"], "shorts")
    assert desc == "Already #Shorts"
    assert tags == ["Shorts"]
