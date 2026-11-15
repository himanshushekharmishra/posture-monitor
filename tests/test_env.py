import pytest

from src.utils.env import apply_overrides, parse_env

SETTINGS = {"camera_index": 0, "process_fps": 5, "ema_alpha": 0.3, "model_path": "a.task",
            "debug_flag": False, "weights": {"neck": 0.5}}


def test_parse_env_handles_comments_quotes_and_export():
    text = """
    # comment
    CAMERA_INDEX=1
    export MODEL_PATH="models/my model.task"
    PROCESS_FPS=10  # inline comment
    not a line
    """
    assert parse_env(text) == {
        "CAMERA_INDEX": "1", "MODEL_PATH": "models/my model.task", "PROCESS_FPS": "10",
    }


def test_overrides_convert_to_existing_types():
    s, applied = apply_overrides(SETTINGS, {"CAMERA_INDEX": "2", "EMA_ALPHA": "0.5",
                                            "DEBUG_FLAG": "yes", "MODEL_PATH": "b.task"})
    assert s["camera_index"] == 2 and s["ema_alpha"] == 0.5
    assert s["debug_flag"] is True and s["model_path"] == "b.task"
    assert sorted(applied) == ["CAMERA_INDEX", "DEBUG_FLAG", "EMA_ALPHA", "MODEL_PATH"]
    assert SETTINGS["camera_index"] == 0  # input not modified


def test_later_sources_win_and_unknown_or_nested_are_ignored():
    s, applied = apply_overrides(
        SETTINGS, {"CAMERA_INDEX": "1"}, {"camera_index": "3", "WEIGHTS": "x", "PATH": "C:/"}
    )
    assert s["camera_index"] == 3 and s["weights"] == {"neck": 0.5}
    assert applied == ["CAMERA_INDEX"]


def test_bad_value_names_the_variable():
    with pytest.raises(ValueError, match="PROCESS_FPS"):
        apply_overrides(SETTINGS, {"PROCESS_FPS": "fast"})
