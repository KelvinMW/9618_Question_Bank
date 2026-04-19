# 9618 QBank

Local Flask app for browsing Cambridge 9618 questions, viewing mark schemes, and assembling custom papers from cropped question images.

## Quick start

The easiest way to run the app on macOS is:

1. Clone the repo
2. Double-click [run_qbank.command](/Users/rjm/Dev/9618%20QBank/run_qbank.command:1)

On first run it will:

- create its own local virtual environment
- install the required Python packages
- create each user's local settings files
- open the app in the browser

The app runs locally on `http://127.0.0.1:5001`.

## Manual start

```bash
python3 -m venv .qbank-venv
source .qbank-venv/bin/activate
pip install -r requirements.txt
python3 launch_qbank.py
```

## For colleagues

Normal users do not need to run any of the data-generation scripts such as:

- `clipper.py`
- `build_marks.py`
- `build_index.py`
- `build_source_file_map.py`

Those are maintenance tools for rebuilding the bank data, not part of the normal app startup flow.

## Data layout

Tracked repo data:

- `manual_titles.json`: shipped question titles
- `question_marks.json`: shipped total marks per question
- `question_source_files.json`: shipped Paper 4 source-file mappings
- `question_overrides.json`: shipped topic/tag overrides if needed
- `topic_index.json`: generated topic/question index

Local user data:

- `local/app_settings.json`: favourite paper, edit mode, browser filters
- `local/saved_papers.json`: assigned papers
- `local/user_titles.json`: per-user title edits
- `local/question_overrides.json`: per-user topic/tag/mark edits

The `local/` JSON files are ignored by git, so each user keeps their own local state.

## Notes

- The app is intended to run locally, not as a hosted web service.
- The shipped repo already contains the cropped images, marks, titles, and source-file mappings needed to use the app.
- If you regenerate marks with `build_marks.py`, any shipped corrections should be reviewed before committing.
- If you want to refresh the Paper 4 source-file map, run `python3 build_source_file_map.py` and then review `question_source_files.json`.
- Cropped question and mark-scheme images live in `static/crops/`.
