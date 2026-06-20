from config import Settings, PIPELINE

def test_settings_loads():
    s = Settings()
    assert s.airtable_base_id == "appiE5ew3MElVDS9g"
    assert s.airtable_table_id == "tblgfx7nmAMKIL0Km"

def test_pipeline_constants():
    assert PIPELINE["cost_cap_usd"] == 15.0
    assert PIPELINE["concurrency"] >= 2
    assert PIPELINE["regen_cap"]["avatar"] == 5
    assert PIPELINE["wpm_target"] == 160
    assert PIPELINE["lufs_target"] == -14
    assert PIPELINE["expansions"]["$1.2M"] == "1.2 million dollars"
    assert PIPELINE["caption"]["fontname"] == "Inter"
    assert PIPELINE["caption"]["fontsize"] == 62
