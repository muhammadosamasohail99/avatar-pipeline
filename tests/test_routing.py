from pipeline.routing import plan_for_format

def test_selfie():
    p = plan_for_format("Selfie")
    assert p["avatar_scope"] == "full"
    assert p["broll_segments"] == "all"
    assert p["nine_sixteen"] == "face_track"

def test_screen_recording():
    p = plan_for_format("Screen Recording")
    assert p["avatar_scope"] == "intro_outro"
    assert p["middle_source"] == "screen"
    assert p["nine_sixteen"] == "face_track"

def test_split_screen():
    p = plan_for_format("Split Screen")
    assert p["avatar_scope"] == "full_left"
    assert p["screen_position"] == "right"
    assert p["nine_sixteen"] == "pip"
