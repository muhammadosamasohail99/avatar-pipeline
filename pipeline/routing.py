ROUTES = {
    "Talking Head": {
        "avatar_scope": "full",
        "broll_segments": "all",
        "screen_position": None,
        "middle_source": "broll",
        "nine_sixteen": "face_track",
    },
    "Selfie": {
        "avatar_scope": "full",
        "broll_segments": "all",
        "screen_position": None,
        "middle_source": "broll",
        "nine_sixteen": "face_track",
    },
    "Screen Recording": {
        "avatar_scope": "intro_outro",
        "broll_segments": "intro_outro",
        "screen_position": None,
        "middle_source": "screen",
        "nine_sixteen": "face_track",
    },
    "Split Screen": {
        "avatar_scope": "full_left",
        "broll_segments": "none",
        "screen_position": "right",
        "middle_source": "screen",
        "nine_sixteen": "pip",
    },
}

def plan_for_format(visual_format: str) -> dict:
    return ROUTES.get(visual_format, ROUTES["Selfie"])
