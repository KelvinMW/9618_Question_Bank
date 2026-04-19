# 9618 QBank

Local Flask app for browsing Cambridge 9618 questions, viewing mark schemes, and assembling custom papers from cropped question images.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

The app runs locally on `http://127.0.0.1:5001`.

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
- If you regenerate marks with `build_marks.py`, any shipped corrections should be reviewed before committing.
- If you want to refresh the Paper 4 source-file map, run `python3 build_source_file_map.py` and then review `question_source_files.json`.
- Cropped question and mark-scheme images live in `static/crops/`.
