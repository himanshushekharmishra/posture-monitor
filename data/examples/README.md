# Landmark examples

Each JSON file holds the 33 MediaPipe pose landmarks for one posture (coordinates
only, never an image), a label and the example it should be compared against.
`tests/test_examples.py` checks that every labelled example scores on the right
side of `slouch_threshold`.

| File | Expected | Pose |
|---|---|---|
| upright.json | good | baseline: sitting upright, facing the camera |
| upright_shifted.json | good | same posture, a little to the left and closer |
| shoulder_tilt.json | good | leaning on one elbow; tilt alone stays under the threshold |
| head_forward.json | slouch | head dropped forward toward the screen |
| leaning_in.json | slouch | upper body leaning in with the head dropping |
| slumped.json | slouch | head down, one shoulder lower, head rolled to the side |

These are synthetic (`"source": "synthetic"`), built by `scripts/make_examples.py`.

## Adding your own
1. Run `python -m src.main --debug` and press **s** to save the current landmarks
   as `recorded_<time>.json` (`"expected": null`, so tests skip it).
2. Save one while sitting upright and set its `"expected"` to `"good"`; that's your
   baseline. Point other recordings at it with `"baseline": "<that file>.json"`.
3. Set `"expected"` to `"good"` or `"slouch"` on the others and run `pytest -q`.
