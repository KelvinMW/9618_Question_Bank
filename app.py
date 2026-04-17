from flask import Flask, render_template, send_from_directory, abort, request, send_file, jsonify
import csv
import json
import os
import re
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from uuid import uuid4

import fitz
from PIL import Image, ImageChops
import clipper

app = Flask(__name__)

# --- CONFIGURATION ---
INDEX_FILE = 'topic_index.json'
MANUAL_TITLES_FILE = 'manual_titles.json'
SYLLABUS_FILE = 'map.json'
CROP_FOLDER = 'static/crops'
MAP_FILE = 'map.csv'
SAVED_PAPERS_FILE = 'saved_papers.json'
QUESTION_OVERRIDES_FILE = 'question_overrides.json'
APP_SETTINGS_FILE = 'app_settings.json'
DEFAULT_APP_SETTINGS = {
    "favorite_level": "P1",
    "edit_mode": False,
}
PDF_PAGE_WIDTH = 595
PDF_PAGE_HEIGHT = 842
PDF_MARGIN_X = 50
PDF_MARGIN_TOP = 50
PDF_MARGIN_BOTTOM = 44
PDF_QUESTION_GAP = 10
PDF_TITLE_GAP = 30
PDF_NUMBER_BOX_WIDTH = 28
PDF_NUMBER_BOX_HEIGHT = 24
PDF_NUMBER_PADDING_RIGHT = 10
PDF_NUMBER_BASELINE_OFFSET = -2
PDF_SPLIT_SEARCH_WINDOW = 120
PDF_WHITE_ROW_THRESHOLD = 250
PDF_WHITE_ROW_RATIO = 0.995
PDF_MAJOR_GAP_MIN_ROWS = 48
PDF_BLOCK_PADDING = 8
PDF_MIN_SPLIT_GAP_ROWS = 10
PDF_MIN_SEGMENT_HEIGHT_PX = 140
PDF_GAP_SIDE_IGNORE = 24
PDF_GAP_WHITE_RATIO = 0.999
PDF_GAP_MIN_PIXEL = 245
PDF_DOTTED_PIXEL_THRESHOLD = 190
PDF_DOTTED_SPREAD_MIN = 0.65
PDF_DOTTED_DENSITY_MIN = 0.003
PDF_DOTTED_DENSITY_MAX = 0.12
PDF_DOTTED_BAND_MAX_ROWS = 8
PDF_DOTTED_GROUP_GAP = 36
PDF_DOTTED_MIN_BANDS = 3
PDF_DOTTED_PROTECT_LEAD = 16
PDF_DOTTED_PROTECT_TRAIL = 120
PDF_FORM_BLOCK_MIN_HEIGHT = 80
PDF_FORM_BLOCK_MAX_HEIGHT = 150
PDF_FORM_RUN_MIN_BLOCKS = 3
PDF_FORM_BLOCK_VARIANCE = 28
PDF_FORM_ATTACH_MAX_HEIGHT = 700
PDF_RENDER_SCALE = 4
PDF_HEADER_CUTOFF = 52
PDF_FOOTER_CUTOFF = 48
PDF_LEFT_ANCHOR_LIMIT = 90
PDF_ANCHOR_PADDING = 6
PDF_PART_ANCHOR_LIMIT = 120
PDF_CONTENT_THRESHOLD = 230
PDF_MARGIN_STRIP_SCAN_WIDTH = 60
PDF_MARGIN_STRIP_MEAN_MAX = 245
PDF_MARGIN_STRIP_DARK_ROW_RATIO_MIN = 0.25
PDF_MARGIN_CLEAR_MEAN_MIN = 248
PDF_MARGIN_CLEAR_DARK_ROW_RATIO_MAX = 0.10


# --- HELPERS ---

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_json(filepath, payload):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def question_key(paper, q_num):
    return f"{paper}::{q_num}"


def normalize_level_choice(level):
    level = str(level or '').strip().upper()
    if level not in {'P1', 'P2', 'P3', 'P4'}:
        return DEFAULT_APP_SETTINGS["favorite_level"]
    return level


def infer_level_from_topic(topic_key):
    if topic_key == 'P4':
        return 'P4'

    match = re.search(r'(\d+)', str(topic_key))
    if not match:
        return DEFAULT_APP_SETTINGS["favorite_level"]

    major_num = int(match.group(1))
    if 1 <= major_num <= 8:
        return 'P1'
    if 9 <= major_num <= 12:
        return 'P2'
    if 13 <= major_num <= 20:
        return 'P3'
    return DEFAULT_APP_SETTINGS["favorite_level"]


@lru_cache(maxsize=1)
def load_app_settings():
    payload = load_json(APP_SETTINGS_FILE)
    settings = DEFAULT_APP_SETTINGS.copy()

    if isinstance(payload, dict):
        settings["favorite_level"] = normalize_level_choice(payload.get("favorite_level"))
        settings["edit_mode"] = bool(payload.get("edit_mode", False))

    return settings


def save_app_settings(settings):
    save_json(APP_SETTINGS_FILE, settings)
    load_app_settings.cache_clear()


@lru_cache(maxsize=1)
def load_question_overrides():
    payload = load_json(QUESTION_OVERRIDES_FILE)
    if isinstance(payload, dict):
        return payload
    return {}


def save_question_overrides(overrides):
    save_json(QUESTION_OVERRIDES_FILE, overrides)
    load_question_overrides.cache_clear()
    load_base_question_lookup.cache_clear()
    load_question_lookup.cache_clear()


def normalize_tag_list(raw_tags):
    if isinstance(raw_tags, list):
        parts = raw_tags
    else:
        parts = re.split(r'[;,]', str(raw_tags or ''))

    tags = []
    seen = set()

    for part in parts:
        tag = str(part).strip()
        if not tag or tag in seen:
            continue
        tags.append(tag)
        seen.add(tag)

    return tags or ['Whole Topic']


def load_topic_choices():
    syllabus = load_json(SYLLABUS_FILE)
    keys = set(syllabus.keys())
    keys.add('P4')
    return [
        {"key": key, "name": get_topic_name(key)}
        for key in sorted(keys, key=sort_key_logic)
    ]


@lru_cache(maxsize=1)
def load_base_question_lookup():
    full_index = load_json(INDEX_FILE)
    lookup = {}

    for topic_key, topic_data in full_index.items():
        topic_name = get_topic_name(topic_key)
        flattened_questions = flatten_topic_questions(topic_data, topic_key)

        for question in flattened_questions:
            normalized_q_num = str(question.get('question'))
            paper = question.get('paper')
            key = (paper, normalized_q_num)

            lookup[key] = {
                "title": question.get('title') or get_display_title(paper, normalized_q_num, topic_key),
                "tags": list(question.get('tags', [])),
                "paper": paper,
                "question": normalized_q_num,
                "img": question.get("img") or f"{paper}_q{normalized_q_num}.png",
                "ms_img": question.get("ms_img") or f"{paper.replace('_qp_', '_ms_')}_q{normalized_q_num}.png",
                "topic_key": topic_key,
                "topic_name": topic_name,
            }

    return lookup


@lru_cache(maxsize=1)
def load_question_lookup():
    lookup = {
        key: value.copy()
        for key, value in load_base_question_lookup().items()
    }

    for key, override in load_question_overrides().items():
        try:
            paper, normalized_q_num = key.split('::', 1)
        except ValueError:
            continue

        lookup_key = (paper, normalized_q_num)
        if lookup_key not in lookup:
            continue

        if override.get("topic_key"):
            lookup[lookup_key]["topic_key"] = override["topic_key"]
            lookup[lookup_key]["topic_name"] = get_topic_name(override["topic_key"])

        if override.get("tags"):
            lookup[lookup_key]["tags"] = list(override["tags"])

    return lookup


def get_display_title(paper, q_num, topic_key):
    manual_titles = load_json(MANUAL_TITLES_FILE)
    key = f"{paper}_q{q_num}"

    if key in manual_titles:
        return manual_titles[key]

    topic_name = get_topic_name(topic_key)
    return f"{topic_name} (Q{q_num})"


def get_topic_name(topic_key):
    if topic_key == 'P4':
        return get_level_name('P4')

    syllabus = load_json(SYLLABUS_FILE)
    value = syllabus.get(topic_key)

    if value is None:
        return topic_key

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        if "topic" in value:
            return value["topic"]
        if "title" in value:
            return value["title"]
        if "name" in value:
            return value["name"]

    return topic_key


def get_level_name(level_key):
    names = {
        "P1": "Theory Fundamentals",
        "P2": "Fundamental Problem Solving & Programming Skills",
        "P3": "Advanced Theory",
        "P4": "Practical",
    }
    return names.get(level_key, level_key)


def is_in_level(topic_key, level):
    topic_key = str(topic_key)

    if level is None:
        level = "P1"

    if topic_key == "P4":
        return level == "P4"

    try:
        match = re.search(r'(\d+)', topic_key)
        if match:
            major_num = int(match.group(1))
            if level == 'P1':
                return 1 <= major_num <= 8
            if level == 'P2':
                return 9 <= major_num <= 12
            if level == 'P3':
                return 13 <= major_num <= 20
        return False
    except:
        return False


def sort_key_logic(topic_key):
    if topic_key == 'P4':
        return [99]

    nums = re.findall(r'\d+', str(topic_key))
    return [int(d) for d in nums] if nums else [0]


def build_topic_list(target_level):
    filtered_keys = {
        question.get("topic_key")
        for question in load_question_lookup().values()
        if is_in_level(question.get("topic_key"), target_level)
    }

    sorted_topics = sorted(filtered_keys, key=sort_key_logic)

    topic_list = [
        {
            "key": k,
            "name": get_topic_name(k)
        }
        for k in sorted_topics
    ]

    return topic_list


def build_paper_list(target_level=None):
    papers = set()

    for question in load_question_lookup().values():
        if not is_in_level(question.get("topic_key"), target_level):
            continue
        paper = question.get("paper")
        if paper:
            papers.add(paper)

    return sorted(papers)


def build_global_question_list(target_level=None):
    questions = [
        question.copy()
        for question in load_question_lookup().values()
        if is_in_level(question.get("topic_key"), target_level)
    ]

    return sorted(
        questions,
        key=lambda item: (
            item.get("title", "").lower(),
            item.get("topic_key", "").lower(),
            item.get("paper", "").lower(),
            int(item.get("question", 0)),
        )
    )


def build_topic_question_list(topic_key):
    questions = [
        question.copy()
        for question in load_question_lookup().values()
        if question.get("topic_key") == topic_key
    ]

    return sorted(
        questions,
        key=lambda item: (
            item.get('title', '').lower(),
            item.get('paper', '').lower(),
            int(item.get('question', 0))
        )
    )


def flatten_topic_questions(topic_data, topic_name):
    deduped_questions = OrderedDict()

    for sub_tag, questions in topic_data.items():
        for q in questions:
            key = (q['paper'], str(q['question']))

            if key not in deduped_questions:
                q_item = q.copy()
                q_item['title'] = get_display_title(q['paper'], q['question'], topic_name)
                q_item['tags'] = []
                deduped_questions[key] = q_item

            if sub_tag not in deduped_questions[key]['tags']:
                deduped_questions[key]['tags'].append(sub_tag)

    return sorted(
        deduped_questions.values(),
        key=lambda item: (
            item.get('title', '').lower(),
            item.get('paper', '').lower(),
            int(item.get('question', 0))
        )
    )


def find_question_metadata(paper, q_num):
    normalized_q_num = str(q_num)
    metadata = load_question_lookup().get((paper, normalized_q_num))
    if metadata:
        return metadata.copy()

    return {
        "title": None,
        "tags": [],
        "paper": paper,
        "question": normalized_q_num,
        "img": f"{paper}_q{normalized_q_num}.png",
        "ms_img": f"{paper.replace('_qp_', '_ms_')}_q{normalized_q_num}.png",
    }


def normalize_saved_question_refs(questions):
    normalized = []
    seen = set()

    for item in questions or []:
        paper = str(item.get('paper', '')).strip()
        question = str(item.get('question', '')).strip()
        if not paper or not question:
            continue

        key = (paper, question)
        if key in seen:
            continue

        normalized.append({"paper": paper, "question": question})
        seen.add(key)

    return normalized


def load_saved_papers():
    payload = load_json(SAVED_PAPERS_FILE)

    if isinstance(payload, dict):
        papers = payload.get('papers', [])
    elif isinstance(payload, list):
        papers = payload
    else:
        papers = []

    normalized = []
    for item in papers:
        title = str(item.get('title', '')).strip()
        questions = normalize_saved_question_refs(item.get('questions', []))
        if not title or not questions:
            continue

        normalized.append({
            "id": str(item.get('id') or f"paper_{uuid4().hex[:12]}"),
            "title": title,
            "questions": questions,
            "created_at": item.get('created_at') or now_iso(),
            "updated_at": item.get('updated_at') or item.get('created_at') or now_iso(),
        })

    return normalized


def save_saved_papers(papers):
    save_json(SAVED_PAPERS_FILE, {"papers": papers})


def build_saved_paper_assignment_map(saved_papers):
    assignments = {}

    for paper in saved_papers:
        paper_ref = {
            "id": paper["id"],
            "title": paper["title"],
        }
        for question in paper.get("questions", []):
            key = question_key(question["paper"], question["question"])
            assignments.setdefault(key, []).append(paper_ref)

    return assignments


def attach_assignments_to_questions(questions, assignment_map):
    enriched = []

    for question in questions:
        item = question.copy()
        assignments = assignment_map.get(question_key(item.get("paper"), item.get("question")), [])
        item["assigned_papers"] = assignments
        item["assigned_count"] = len(assignments)
        enriched.append(item)

    return enriched


def serialize_saved_paper(saved_paper):
    enriched_questions = []
    for question in saved_paper.get("questions", []):
        metadata = find_question_metadata(question["paper"], question["question"])
        enriched_questions.append({
            "paper": metadata["paper"],
            "question": metadata["question"],
            "title": metadata.get("title"),
            "tags": metadata.get("tags", []),
            "img": metadata.get("img"),
            "ms_img": metadata.get("ms_img"),
        })

    return {
        "id": saved_paper["id"],
        "title": saved_paper["title"],
        "question_count": len(enriched_questions),
        "questions": enriched_questions,
        "created_at": saved_paper.get("created_at"),
        "updated_at": saved_paper.get("updated_at"),
    }


@lru_cache(maxsize=1)
def load_map_rows():
    if not os.path.exists(MAP_FILE):
        return []

    with open(MAP_FILE, mode='r', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f, skipinitialspace=True))


def find_map_row(paper, q_num, folder='qp'):
    normalized_q_num = str(q_num)
    for row in load_map_rows():
        if (
            row.get('folder', '').strip() == folder
            and row.get('filename', '').strip() == paper
            and str(row.get('q_num', '')).strip() == normalized_q_num
        ):
            return row
    return None


def load_question_source_image(question, source_folder, image_name, source_image_cache):
    cache_key = (source_folder, question.get('paper'), str(question.get('question')), image_name)
    cached = source_image_cache.get(cache_key)
    if cached is not None:
        image, top_trim = cached
        return image.copy(), top_trim

    if source_folder == 'qp':
        row = find_map_row(question['paper'], question['question'], folder='qp')
        if row:
            try:
                start_page = int(row['start_page']) - 1
                end_page = int(row['end_page']) - 1
            except (ValueError, TypeError):
                start_page = end_page = None

            pdf_path = os.path.join('qp', f"{question['paper']}.pdf")
            if start_page is not None and os.path.exists(pdf_path):
                doc = fitz.open(pdf_path)
                try:
                    page_images = clipper.extract_question_images(doc, start_page, end_page, question['question'])
                finally:
                    doc.close()

                if page_images:
                    stitched_image = clipper.stitch_images(page_images)
                    prepared_image, trim_bbox = trim_outer_whitespace(stitched_image, return_bbox=True)
                    top_trim = trim_bbox[1]
                    source_image_cache[cache_key] = (prepared_image.copy(), top_trim)
                    return prepared_image, top_trim

    image_path = os.path.join(CROP_FOLDER, source_folder, image_name)
    if not os.path.exists(image_path):
        return None, 0

    with Image.open(image_path) as image:
        prepared_image = trim_edge_gutters(image.convert("RGB"))
        prepared_image, trim_bbox = trim_outer_whitespace(prepared_image, return_bbox=True)

    top_trim = trim_bbox[1]
    source_image_cache[cache_key] = (prepared_image.copy(), top_trim)
    return prepared_image, top_trim


def get_pdf_words(page):
    return page.get_text('words', sort=True)


def find_pdf_question_anchor(words, q_num, page_height):
    q_num = str(q_num).strip()
    candidates = [
        word for word in words
        if word[4] == q_num
        and word[0] <= PDF_LEFT_ANCHOR_LIMIT
        and PDF_HEADER_CUTOFF <= word[1] <= page_height - PDF_FOOTER_CUTOFF
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda word: (word[1], word[0]))


def build_question_clip_rect(page, words, q_num, is_first_page, is_last_page):
    page_rect = page.rect
    top = PDF_HEADER_CUTOFF
    bottom = page_rect.height - PDF_FOOTER_CUTOFF

    if is_first_page:
        start_anchor = find_pdf_question_anchor(words, q_num, page_rect.height)
        if start_anchor:
            top = max(PDF_HEADER_CUTOFF, start_anchor[1] - PDF_ANCHOR_PADDING)

    if is_last_page:
        next_anchor = find_pdf_question_anchor(words, int(q_num) + 1, page_rect.height)
        if next_anchor:
            bottom = min(bottom, next_anchor[1] - PDF_ANCHOR_PADDING)

    if bottom <= top:
        top = PDF_HEADER_CUTOFF
        bottom = page_rect.height - PDF_FOOTER_CUTOFF

    return fitz.Rect(0, top, page_rect.width, bottom)


def insert_page_number(page, page_number):
    footer_rect = fitz.Rect(
        PDF_MARGIN_X,
        PDF_PAGE_HEIGHT - 28,
        PDF_PAGE_WIDTH - PDF_MARGIN_X,
        PDF_PAGE_HEIGHT - 10,
    )
    page.insert_textbox(
        footer_rect,
        str(page_number),
        fontsize=10,
        fontname="helv",
        color=(0.42, 0.46, 0.52),
        align=1,
    )


def trim_outer_whitespace(image, padding=10, return_bbox=False):
    grayscale = image.convert("L")
    mask = grayscale.point(
        lambda pixel: 255 if pixel < PDF_CONTENT_THRESHOLD else 0,
        mode="L",
    )
    bbox = mask.getbbox()

    if not bbox:
        return (image, (0, 0, image.width, image.height)) if return_bbox else image

    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    cropped = image.crop((left, top, right, bottom))
    if return_bbox:
        return cropped, (left, top, right, bottom)
    return cropped


def trim_vertical_whitespace(image, padding=8):
    grayscale = image.convert("L")
    mask = grayscale.point(
        lambda pixel: 255 if pixel < PDF_CONTENT_THRESHOLD else 0,
        mode="L",
    )
    bbox = mask.getbbox()

    if not bbox:
        return image

    top = max(0, bbox[1] - padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((0, top, image.width, bottom))


def get_band_stats(grayscale, x0, x1):
    band = grayscale.crop((x0, 0, x1, grayscale.height))
    pixels = list(band.getdata())
    mean = sum(pixels) / max(1, len(pixels))

    dark_rows = 0
    for y in range(grayscale.height):
        row = band.crop((0, y, band.width, y + 1))
        if min(row.getdata()) < 120:
            dark_rows += 1

    return mean, dark_rows / max(1, grayscale.height)


def trim_edge_gutters(image):
    grayscale = image.convert("L")
    width, height = grayscale.size
    scan = min(PDF_MARGIN_STRIP_SCAN_WIDTH, width // 4)
    if scan <= 0:
        return image

    left_strip = get_band_stats(grayscale, 0, scan)
    left_inner = get_band_stats(grayscale, scan, min(width, scan * 2))
    right_strip = get_band_stats(grayscale, max(0, width - scan), width)
    right_inner = get_band_stats(grayscale, max(0, width - (scan * 2)), max(0, width - scan))

    left_crop = scan if (
        left_strip[0] <= PDF_MARGIN_STRIP_MEAN_MAX
        and left_strip[1] >= PDF_MARGIN_STRIP_DARK_ROW_RATIO_MIN
        and left_inner[0] >= PDF_MARGIN_CLEAR_MEAN_MIN
        and left_inner[1] <= PDF_MARGIN_CLEAR_DARK_ROW_RATIO_MAX
    ) else 0

    right_crop = scan if (
        right_strip[0] <= PDF_MARGIN_STRIP_MEAN_MAX
        and right_strip[1] >= PDF_MARGIN_STRIP_DARK_ROW_RATIO_MIN
        and right_inner[0] >= PDF_MARGIN_CLEAR_MEAN_MIN
        and right_inner[1] <= PDF_MARGIN_CLEAR_DARK_ROW_RATIO_MAX
    ) else 0

    return image.crop((left_crop, 0, max(left_crop + 1, width - right_crop), height))


def insert_question_number(page, question_number, y_cursor):
    number_rect = fitz.Rect(
        PDF_MARGIN_X,
        y_cursor + PDF_NUMBER_BASELINE_OFFSET,
        PDF_MARGIN_X + PDF_NUMBER_BOX_WIDTH,
        y_cursor + PDF_NUMBER_BASELINE_OFFSET + PDF_NUMBER_BOX_HEIGHT,
    )
    page.insert_textbox(
        number_rect,
        str(question_number),
        fontsize=12,
        fontname="hebo",
        color=(0, 0, 0),
        align=0,
    )


def row_white_ratio(image, y):
    left = min(PDF_GAP_SIDE_IGNORE, max(0, image.width // 8))
    right = max(left + 1, image.width - left)
    row = image.crop((left, y, right, y + 1))
    grayscale = row.convert("L")
    pixels = list(grayscale.getdata())
    white_pixels = sum(1 for pixel in pixels if pixel >= PDF_WHITE_ROW_THRESHOLD)
    return white_pixels / max(1, len(pixels))


def is_safe_gap_row(image, y):
    left = min(PDF_GAP_SIDE_IGNORE, max(0, image.width // 8))
    right = max(left + 1, image.width - left)
    row = image.crop((left, y, right, y + 1))
    grayscale = row.convert("L")
    pixels = list(grayscale.getdata())
    return (
        min(pixels) >= PDF_GAP_MIN_PIXEL
        and (sum(1 for pixel in pixels if pixel >= PDF_GAP_MIN_PIXEL) / max(1, len(pixels))) >= PDF_GAP_WHITE_RATIO
    )


def find_dotted_answer_regions(image):
    left = min(PDF_GAP_SIDE_IGNORE, max(0, image.width // 8))
    right = max(left + 1, image.width - left)

    dotted_bands = []
    band_start = None

    for y in range(image.height):
        row = image.crop((left, y, right, y + 1))
        grayscale = row.convert("L")
        pixels = list(grayscale.getdata())
        dark_positions = [index for index, pixel in enumerate(pixels) if pixel < PDF_DOTTED_PIXEL_THRESHOLD]

        is_dotted = False
        if dark_positions:
            spread = (max(dark_positions) - min(dark_positions)) / max(1, len(pixels))
            density = len(dark_positions) / max(1, len(pixels))
            is_dotted = (
                spread >= PDF_DOTTED_SPREAD_MIN
                and PDF_DOTTED_DENSITY_MIN <= density <= PDF_DOTTED_DENSITY_MAX
            )

        if is_dotted and band_start is None:
            band_start = y
        elif not is_dotted and band_start is not None:
            if (y - band_start) <= PDF_DOTTED_BAND_MAX_ROWS:
                dotted_bands.append((band_start, y - 1))
            band_start = None

    if band_start is not None and (image.height - band_start) <= PDF_DOTTED_BAND_MAX_ROWS:
        dotted_bands.append((band_start, image.height - 1))

    if len(dotted_bands) < PDF_DOTTED_MIN_BANDS:
        return []

    grouped_regions = []
    current_start, current_end = dotted_bands[0]
    current_count = 1

    for band_start, band_end in dotted_bands[1:]:
        if band_start - current_end <= PDF_DOTTED_GROUP_GAP:
            current_end = band_end
            current_count += 1
        else:
            if current_count >= PDF_DOTTED_MIN_BANDS:
                grouped_regions.append((
                    max(0, current_start - PDF_DOTTED_PROTECT_LEAD),
                    min(image.height, current_end + PDF_DOTTED_PROTECT_TRAIL),
                ))
            current_start, current_end = band_start, band_end
            current_count = 1

    if current_count >= PDF_DOTTED_MIN_BANDS:
        grouped_regions.append((
            max(0, current_start - PDF_DOTTED_PROTECT_LEAD),
            min(image.height, current_end + PDF_DOTTED_PROTECT_TRAIL),
        ))

    return grouped_regions


def is_protected_row(y, protected_ranges):
    return any(start <= y <= end for start, end in protected_ranges)


def find_split_row(image, start_px, ideal_end_px, max_end_px, protected_ranges=None):
    protected_ranges = protected_ranges or []
    if ideal_end_px >= max_end_px:
        return max_end_px

    search_start = max(start_px + PDF_MIN_SEGMENT_HEIGHT_PX, ideal_end_px - PDF_SPLIT_SEARCH_WINDOW)
    search_end = min(max_end_px, ideal_end_px + PDF_SPLIT_SEARCH_WINDOW)

    best_before = None
    best_after = None
    gap_start = None

    for y in range(search_start, search_end):
        is_white = is_safe_gap_row(image, y) and not is_protected_row(y, protected_ranges)

        if is_white and gap_start is None:
            gap_start = y
        elif not is_white and gap_start is not None:
            gap_height = y - gap_start
            if gap_height >= PDF_MIN_SPLIT_GAP_ROWS:
                gap_mid = gap_start + (gap_height // 2)
                if not is_protected_row(gap_mid, protected_ranges):
                    if gap_mid <= ideal_end_px:
                        if best_before is None or gap_mid > best_before:
                            best_before = gap_mid
                    else:
                        if best_after is None or gap_mid < best_after:
                            best_after = gap_mid
            gap_start = None

    if gap_start is not None:
        gap_height = search_end - gap_start
        if gap_height >= PDF_MIN_SPLIT_GAP_ROWS:
            gap_mid = gap_start + (gap_height // 2)
            if not is_protected_row(gap_mid, protected_ranges):
                if gap_mid <= ideal_end_px:
                    best_before = gap_mid
                elif best_after is None:
                    best_after = gap_mid

    return best_before or best_after


def is_part_marker(text):
    if not (text.startswith('(') and text.endswith(')')):
        return False
    inner = text[1:-1]
    return inner.islower() and inner.isalpha() and 1 <= len(inner) <= 4


def find_part_starts_for_question(question):
    row = find_map_row(question['paper'], question['question'], folder='qp')
    if not row:
        return []

    try:
        start_page = int(row['start_page']) - 1
        end_page = int(row['end_page']) - 1
    except (ValueError, TypeError):
        return []

    pdf_path = os.path.join('qp', f"{question['paper']}.pdf")
    if not os.path.exists(pdf_path):
        return []

    part_starts = []
    cumulative_height = 0
    doc = fitz.open(pdf_path)
    try:
        for page_index in range(start_page, end_page + 1):
            if page_index < 0 or page_index >= len(doc):
                continue

            page = doc[page_index]
            words = clipper.get_page_words(page)
            clip_rect, _ = clipper.build_clip_rect(
                page,
                words,
                question['question'],
                is_first_page=(page_index == start_page),
                is_last_page=(page_index == end_page),
            )

            for word in words:
                text = str(word[4])
                if not is_part_marker(text):
                    continue
                if (word[0] - clip_rect.x0) > PDF_PART_ANCHOR_LIMIT:
                    continue
                if not (clip_rect.y0 <= word[1] <= clip_rect.y1):
                    continue

                part_y = cumulative_height + int((word[1] - clip_rect.y0) * clipper.RENDER_SCALE)
                part_starts.append(part_y)

            cumulative_height += int(clip_rect.height * clipper.RENDER_SCALE)
    finally:
        doc.close()

    cleaned = sorted({y for y in part_starts if y > 20})
    return cleaned


def split_image_into_blocks(image, protected_ranges=None):
    protected_ranges = protected_ranges or []
    blocks = []
    in_gap = False
    gap_start = None
    last_cut = 0

    for y in range(image.height):
        is_white_row = is_safe_gap_row(image, y)

        if is_white_row and not in_gap:
            in_gap = True
            gap_start = y
        elif not is_white_row and in_gap:
            gap_height = y - gap_start
            if gap_height >= PDF_MAJOR_GAP_MIN_ROWS:
                cut = gap_start + (gap_height // 2)
                if not is_protected_row(cut, protected_ranges):
                    block_top = max(0, last_cut - PDF_BLOCK_PADDING)
                    block_bottom = min(image.height, cut + PDF_BLOCK_PADDING)
                    if block_bottom > block_top:
                        blocks.append((block_top, block_bottom))
                    last_cut = cut
            in_gap = False
            gap_start = None

    final_top = max(0, last_cut - PDF_BLOCK_PADDING)
    final_bottom = image.height
    if final_bottom > final_top:
        blocks.append((final_top, final_bottom))

    deduped_blocks = []
    prev_bottom = 0
    for top, bottom in blocks:
        top = max(top, prev_bottom)
        if bottom > top:
            deduped_blocks.append((top, bottom))
            prev_bottom = bottom

    return deduped_blocks or [(0, image.height)]


def merge_form_like_blocks(blocks):
    if len(blocks) < PDF_FORM_RUN_MIN_BLOCKS:
        return blocks

    merged = []
    index = 0

    while index < len(blocks):
        current_height = blocks[index][1] - blocks[index][0]
        if not (PDF_FORM_BLOCK_MIN_HEIGHT <= current_height <= PDF_FORM_BLOCK_MAX_HEIGHT):
            merged.append(blocks[index])
            index += 1
            continue

        run_end = index
        run_heights = [current_height]

        while run_end + 1 < len(blocks):
            next_height = blocks[run_end + 1][1] - blocks[run_end + 1][0]
            candidate_heights = run_heights + [next_height]
            if (
                PDF_FORM_BLOCK_MIN_HEIGHT <= next_height <= PDF_FORM_BLOCK_MAX_HEIGHT
                and (max(candidate_heights) - min(candidate_heights)) <= PDF_FORM_BLOCK_VARIANCE
            ):
                run_end += 1
                run_heights.append(next_height)
            else:
                break

        if len(run_heights) >= PDF_FORM_RUN_MIN_BLOCKS:
            merged_end = run_end
            if merged_end + 1 < len(blocks):
                following_height = blocks[merged_end + 1][1] - blocks[merged_end + 1][0]
                if following_height <= PDF_FORM_ATTACH_MAX_HEIGHT:
                    merged_end += 1
            merged.append((blocks[index][0], blocks[merged_end][1]))
            index = merged_end + 1
            continue

        merged.append(blocks[index])
        index += 1

    return merged


def build_question_blocks(question, image, top_trim=0):
    protected_ranges = find_dotted_answer_regions(image)
    part_starts = [
        max(0, y - top_trim)
        for y in find_part_starts_for_question(question)
    ]
    if not part_starts:
        blocks = split_image_into_blocks(image, protected_ranges=protected_ranges)
        return merge_form_like_blocks(blocks)

    starts = [0] + [y for y in part_starts if 0 < y < image.height]
    starts = sorted(set(starts))
    blocks = []

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else image.height
        if end > start:
            blocks.append((start, end))

    return blocks or [(0, image.height)]


def generate_question_paper_pdf(paper_title, selected_questions, source_folder='qp', image_field='img'):
    doc = fitz.open()
    content_width = PDF_PAGE_WIDTH - (2 * PDF_MARGIN_X)
    content_bottom = PDF_PAGE_HEIGHT - PDF_MARGIN_BOTTOM
    source_image_cache = {}

    page = doc.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
    y_cursor = PDF_MARGIN_TOP

    if paper_title:
        title_rect = fitz.Rect(PDF_MARGIN_X, y_cursor, PDF_PAGE_WIDTH - PDF_MARGIN_X, y_cursor + 34)
        page.insert_textbox(
            title_rect,
            paper_title,
            fontsize=14,
            fontname="hebo",
            color=(0, 0, 0),
            align=0,
        )
        y_cursor += PDF_TITLE_GAP

    for index, question in enumerate(selected_questions, start=1):
        image_name = question.get(image_field)
        if not image_name:
            continue
        prepared_image, top_trim = load_question_source_image(
            question,
            source_folder,
            image_name,
            source_image_cache,
        )
        if prepared_image is None:
            continue

        question_image = prepared_image
        image_width, image_height = question_image.size
        blocks = (
            build_question_blocks(question, question_image, top_trim=top_trim)
            if source_folder == 'qp'
            else [(0, image_height)]
        )
        first_segment = True

        for block_top, block_bottom in blocks:
            block_image = trim_vertical_whitespace(
                question_image.crop((0, block_top, image_width, block_bottom)),
                padding=PDF_BLOCK_PADDING,
            )
            block_width, block_height = block_image.size
            protected_ranges = find_dotted_answer_regions(block_image)
            full_page_height = content_bottom - PDF_MARGIN_TOP
            horizontal_offset = PDF_NUMBER_BOX_WIDTH + PDF_NUMBER_PADDING_RIGHT if first_segment else 0
            usable_width = content_width - horizontal_offset
            scale = usable_width / block_width
            rendered_block_height = block_height * scale
            remaining_height = content_bottom - y_cursor

            if rendered_block_height > remaining_height and rendered_block_height <= full_page_height:
                page = doc.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
                y_cursor = PDF_MARGIN_TOP
            elif remaining_height < 80:
                page = doc.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
                y_cursor = PDF_MARGIN_TOP

            current_top_px = 0
            while current_top_px < block_height:
                if first_segment:
                    insert_question_number(page, index, y_cursor)

                horizontal_offset = PDF_NUMBER_BOX_WIDTH + PDF_NUMBER_PADDING_RIGHT if first_segment else 0
                usable_width = content_width - horizontal_offset
                scale = usable_width / block_width
                available_height = content_bottom - y_cursor

                if available_height < 80:
                    page = doc.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
                    y_cursor = PDF_MARGIN_TOP
                    continue

                ideal_slice_height_px = max(1, min(int(available_height / scale), block_height - current_top_px))
                proposed_end_px = current_top_px + ideal_slice_height_px
                split_end_px = find_split_row(
                    block_image,
                    current_top_px,
                    proposed_end_px,
                    block_height,
                    protected_ranges=protected_ranges,
                )

                if split_end_px is None:
                    if y_cursor > PDF_MARGIN_TOP:
                        page = doc.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
                        y_cursor = PDF_MARGIN_TOP
                        continue
                    split_end_px = proposed_end_px

                split_end_px = min(split_end_px, block_height)
                slice_height_px = max(1, min(split_end_px - current_top_px, block_height - current_top_px))
                segment = block_image.crop((0, current_top_px, block_width, current_top_px + slice_height_px))

                segment_buffer = BytesIO()
                segment.save(segment_buffer, format="PNG")
                segment_bytes = segment_buffer.getvalue()

                rendered_height = slice_height_px * scale
                image_rect = fitz.Rect(
                    PDF_MARGIN_X + horizontal_offset,
                    y_cursor,
                    PDF_MARGIN_X + horizontal_offset + (segment.width * scale),
                    y_cursor + rendered_height,
                )
                page.insert_image(image_rect, stream=segment_bytes)

                y_cursor += rendered_height
                current_top_px += slice_height_px
                first_segment = False

                if current_top_px < block_height:
                    page = doc.new_page(width=PDF_PAGE_WIDTH, height=PDF_PAGE_HEIGHT)
                    y_cursor = PDF_MARGIN_TOP

        y_cursor += PDF_QUESTION_GAP

    for page_number, pdf_page in enumerate(doc, start=1):
        insert_page_number(pdf_page, page_number)

    return doc.tobytes(garbage=4, deflate=True)


# --- ROUTES ---

@app.route('/')
@app.route('/level/<target_level>')
def home(target_level=None):
    settings = load_app_settings()
    target_level = normalize_level_choice(target_level or settings["favorite_level"])

    if target_level == "P4":
        return show_topic("P4", target_level="P4")

    topic_list = build_topic_list(target_level)
    paper_list = build_paper_list(target_level)
    saved_papers = load_saved_papers()
    assignment_map = build_saved_paper_assignment_map(saved_papers)
    search_questions = attach_assignments_to_questions(
        build_global_question_list(target_level),
        assignment_map,
    )

    return render_template(
        'dashboard.html',
        topics=topic_list,
        papers=paper_list,
        data={},
        search_questions=search_questions,
        saved_paper_count=len(saved_papers),
        app_settings=settings,
        topic_choices=load_topic_choices(),
        current_topic=None,
        current_level=target_level
        ,
        current_level_name=get_level_name(target_level)
    )


@app.route('/topic/<path:topic_name>')
@app.route('/level/<target_level>/topic/<path:topic_name>')
def show_topic(topic_name, target_level=None):
    settings = load_app_settings()
    target_level = normalize_level_choice(target_level or infer_level_from_topic(topic_name) or settings["favorite_level"])
    valid_topics = {choice["key"] for choice in load_topic_choices()}
    if topic_name not in valid_topics:
        abort(404)

    saved_papers = load_saved_papers()
    assignment_map = build_saved_paper_assignment_map(saved_papers)
    questions_with_metadata = attach_assignments_to_questions(
        build_topic_question_list(topic_name),
        assignment_map,
    )

    topic_list = build_topic_list(target_level)
    paper_list = build_paper_list(target_level)

    return render_template(
        'dashboard.html',
        topics=topic_list,
        papers=paper_list,
        data=questions_with_metadata,
        search_questions=[],
        saved_paper_count=len(saved_papers),
        app_settings=settings,
        topic_choices=load_topic_choices(),
        current_topic=topic_name,
        current_level=target_level,
        current_level_name=get_level_name(target_level) if target_level else None
    )


@app.route('/view/<paper>/<q_num>')
def view_question(paper, q_num):
    qp_img = f"{paper}_q{q_num}.png"
    ms_paper = paper.replace('_qp_', '_ms_')
    ms_img = f"{ms_paper}_q{q_num}.png"
    metadata = find_question_metadata(paper, q_num)
    assignment_map = build_saved_paper_assignment_map(load_saved_papers())
    question_title = request.args.get('title') or metadata["title"] or f"Question {q_num}"
    question_tags = [tag for tag in request.args.getlist('tag') if tag] or metadata["tags"]
    question_assignments = assignment_map.get(question_key(paper, str(q_num)), [])

    return render_template(
        'viewer.html',
        qp_img=qp_img,
        ms_img=ms_img,
        paper=paper,
        q_num=q_num,
        question_title=question_title,
        question_tags=question_tags,
        question_metadata=metadata,
        question_assignments=question_assignments,
    )


@app.route('/builder')
def paper_builder():
    return render_template('builder.html', saved_paper_count=len(load_saved_papers()))


def parse_requested_question_refs(payload):
    return normalize_saved_question_refs((payload or {}).get("questions", []))


@app.route('/api/saved-papers', methods=['GET'])
def api_saved_papers():
    saved_papers = load_saved_papers()
    serialized = sorted(
        (serialize_saved_paper(paper) for paper in saved_papers),
        key=lambda item: (item.get('updated_at') or '', item.get('title') or ''),
        reverse=True,
    )
    return jsonify({"papers": serialized})


@app.route('/api/saved-papers', methods=['POST'])
def create_saved_paper():
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    questions = parse_requested_question_refs(payload)

    if not title or not questions:
        abort(400)

    timestamp = now_iso()
    saved_papers = load_saved_papers()
    new_paper = {
        "id": f"paper_{uuid4().hex[:12]}",
        "title": title,
        "questions": questions,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    saved_papers.append(new_paper)
    save_saved_papers(saved_papers)
    return jsonify({"paper": serialize_saved_paper(new_paper)}), 201


@app.route('/api/saved-papers/<paper_id>', methods=['PUT'])
def update_saved_paper(paper_id):
    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    questions = parse_requested_question_refs(payload)

    if not title or not questions:
        abort(400)

    saved_papers = load_saved_papers()
    for index, saved_paper in enumerate(saved_papers):
        if saved_paper["id"] != paper_id:
            continue

        updated_paper = saved_paper.copy()
        updated_paper["title"] = title
        updated_paper["questions"] = questions
        updated_paper["updated_at"] = now_iso()
        saved_papers[index] = updated_paper
        save_saved_papers(saved_papers)
        return jsonify({"paper": serialize_saved_paper(updated_paper)})

    abort(404)


@app.route('/api/saved-papers/<paper_id>', methods=['DELETE'])
def delete_saved_paper(paper_id):
    saved_papers = load_saved_papers()
    remaining = [paper for paper in saved_papers if paper["id"] != paper_id]

    if len(remaining) == len(saved_papers):
        abort(404)

    save_saved_papers(remaining)
    return ('', 204)


@app.route('/api/settings', methods=['GET'])
def api_settings():
    return jsonify({"settings": load_app_settings()})


@app.route('/api/settings', methods=['PUT'])
def update_settings():
    payload = request.get_json(silent=True) or {}
    settings = {
        "favorite_level": normalize_level_choice(payload.get("favorite_level")),
        "edit_mode": bool(payload.get("edit_mode", False)),
    }
    save_app_settings(settings)
    return jsonify({"settings": settings})


@app.route('/api/questions/<paper>/<q_num>/metadata', methods=['PUT'])
def update_question_metadata(paper, q_num):
    normalized_q_num = str(q_num).strip()
    lookup_key = (paper, normalized_q_num)
    base_metadata = load_base_question_lookup().get(lookup_key)

    if not base_metadata:
        abort(404)

    payload = request.get_json(silent=True) or {}
    title = str(payload.get("title", "")).strip()
    topic_key = str(payload.get("topic_key", "")).strip() or base_metadata["topic_key"]
    tags = normalize_tag_list(payload.get("tags", base_metadata["tags"]))

    valid_topics = {choice["key"] for choice in load_topic_choices()}
    if not title or topic_key not in valid_topics:
        abort(400)

    manual_titles = load_json(MANUAL_TITLES_FILE)
    manual_titles[f"{paper}_q{normalized_q_num}"] = title
    save_json(MANUAL_TITLES_FILE, manual_titles)

    overrides = load_question_overrides().copy()
    question_override_key = question_key(paper, normalized_q_num)
    override_payload = {}

    if topic_key != base_metadata["topic_key"]:
        override_payload["topic_key"] = topic_key

    if tags != list(base_metadata["tags"]):
        override_payload["tags"] = tags

    if override_payload:
        overrides[question_override_key] = override_payload
    else:
        overrides.pop(question_override_key, None)

    save_question_overrides(overrides)
    load_question_lookup.cache_clear()

    return jsonify({"question": find_question_metadata(paper, normalized_q_num)})


@app.route('/generate-paper', methods=['POST'])
def generate_paper():
    payload = request.get_json(silent=True) or {}
    requested_questions = parse_requested_question_refs(payload)
    paper_title = (payload.get("title") or "Custom Question Paper").strip()
    export_type = (payload.get("export_type") or "questions").strip().lower()

    selected_questions = []
    for item in requested_questions:
        paper = str(item.get("paper", "")).strip()
        question = str(item.get("question", "")).strip()
        if not paper or not question:
            continue
        selected_questions.append(find_question_metadata(paper, question))

    if not selected_questions:
        abort(400)

    if export_type == 'markscheme':
        pdf_bytes = generate_question_paper_pdf(
            paper_title,
            selected_questions,
            source_folder='ms',
            image_field='ms_img',
        )
        default_filename = "ms_custom_mark_scheme"
    else:
        pdf_bytes = generate_question_paper_pdf(
            paper_title,
            selected_questions,
            source_folder='qp',
            image_field='img',
        )
        default_filename = "qp_custom_question_paper"

    safe_title = re.sub(r'[^A-Za-z0-9._-]+', '_', paper_title).strip('_')
    prefix = 'ms_' if export_type == 'markscheme' else 'qp_'
    filename = f"{prefix}{safe_title}" if safe_title else default_filename

    return send_file(
        BytesIO(pdf_bytes),
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f"{filename}.pdf"
    )


@app.route('/crops/<folder>/<path:filename>')
def serve_crops(folder, filename):
    return send_from_directory(os.path.join(CROP_FOLDER, folder), filename)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
