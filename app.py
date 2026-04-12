from flask import Flask, render_template, send_from_directory, abort, request, send_file
import csv
import json
import os
import re
from collections import OrderedDict
from functools import lru_cache
from io import BytesIO

import fitz
from PIL import Image, ImageChops

app = Flask(__name__)

# --- CONFIGURATION ---
INDEX_FILE = 'topic_index.json'
MANUAL_TITLES_FILE = 'manual_titles.json'
SYLLABUS_FILE = 'map.json'
CROP_FOLDER = 'static/crops'
MAP_FILE = 'map.csv'
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
PDF_RENDER_SCALE = 4
PDF_HEADER_CUTOFF = 52
PDF_FOOTER_CUTOFF = 48
PDF_LEFT_ANCHOR_LIMIT = 90
PDF_ANCHOR_PADDING = 6
PDF_PART_ANCHOR_LIMIT = 120


# --- HELPERS ---

def load_json(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def get_display_title(paper, q_num, topic_key):
    manual_titles = load_json(MANUAL_TITLES_FILE)
    key = f"{paper}_q{q_num}"

    if key in manual_titles:
        return manual_titles[key]

    topic_name = get_topic_name(topic_key)
    return f"{topic_name} (Q{q_num})"


def get_topic_name(topic_key):
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


def build_topic_list(full_index, target_level):
    filtered_keys = [
        k for k in full_index.keys()
        if is_in_level(k, target_level)
    ]

    sorted_topics = sorted(filtered_keys, key=sort_key_logic)

    topic_list = [
        {
            "key": k,
            "name": get_topic_name(k)
        }
        for k in sorted_topics
    ]

    return topic_list


def build_paper_list(full_index, target_level=None):
    papers = set()

    for topic_key, topic_data in full_index.items():
        if not is_in_level(topic_key, target_level):
            continue

        for questions in topic_data.values():
            for question in questions:
                paper = question.get("paper")
                if paper:
                    papers.add(paper)

    return sorted(papers)


def build_global_question_list(full_index, target_level=None):
    questions = []

    for topic_key, topic_data in full_index.items():
        if not is_in_level(topic_key, target_level):
            continue

        topic_name = get_topic_name(topic_key)
        flattened = flatten_topic_questions(topic_data, topic_key)

        for question in flattened:
            item = question.copy()
            item["topic_key"] = topic_key
            item["topic_name"] = topic_name
            questions.append(item)

    return sorted(
        questions,
        key=lambda item: (
            item.get("title", "").lower(),
            item.get("topic_key", "").lower(),
            item.get("paper", "").lower(),
            int(item.get("question", 0)),
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
    full_index = load_json(INDEX_FILE)
    normalized_q_num = str(q_num)

    for topic_key, topic_data in full_index.items():
        flattened_questions = flatten_topic_questions(topic_data, topic_key)

        for question in flattened_questions:
            if question.get('paper') == paper and str(question.get('question')) == normalized_q_num:
                return {
                    "title": question.get('title') or get_display_title(paper, normalized_q_num, topic_key),
                    "tags": question.get('tags', []),
                    "paper": paper,
                    "question": normalized_q_num,
                    "img": question.get("img") or f"{paper}_q{normalized_q_num}.png",
                    "ms_img": question.get("ms_img") or f"{paper.replace('_qp_', '_ms_')}_q{normalized_q_num}.png",
                }

    return {
        "title": None,
        "tags": [],
        "paper": paper,
        "question": normalized_q_num,
        "img": f"{paper}_q{normalized_q_num}.png",
        "ms_img": f"{paper.replace('_qp_', '_ms_')}_q{normalized_q_num}.png",
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
    background = Image.new(image.mode, image.size, "white")
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()

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
    background = Image.new(image.mode, image.size, "white")
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()

    if not bbox:
        return image

    top = max(0, bbox[1] - padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((0, top, image.width, bottom))


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
    row = image.crop((0, y, image.width, y + 1))
    grayscale = row.convert("L")
    pixels = list(grayscale.getdata())
    white_pixels = sum(1 for pixel in pixels if pixel >= PDF_WHITE_ROW_THRESHOLD)
    return white_pixels / max(1, len(pixels))


def find_split_row(image, start_px, ideal_end_px, max_end_px):
    if ideal_end_px >= max_end_px:
        return max_end_px

    search_start = max(start_px + PDF_MIN_SEGMENT_HEIGHT_PX, ideal_end_px - PDF_SPLIT_SEARCH_WINDOW)
    search_end = min(max_end_px, ideal_end_px + PDF_SPLIT_SEARCH_WINDOW)

    best_before = None
    best_after = None
    gap_start = None

    for y in range(search_start, search_end):
        is_white = row_white_ratio(image, y) >= PDF_WHITE_ROW_RATIO

        if is_white and gap_start is None:
            gap_start = y
        elif not is_white and gap_start is not None:
            gap_height = y - gap_start
            if gap_height >= PDF_MIN_SPLIT_GAP_ROWS:
                gap_mid = gap_start + (gap_height // 2)
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
            words = get_pdf_words(page)
            clip_rect = build_question_clip_rect(
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
                if word[0] > PDF_PART_ANCHOR_LIMIT:
                    continue
                if not (clip_rect.y0 <= word[1] <= clip_rect.y1):
                    continue

                part_y = cumulative_height + int((word[1] - clip_rect.y0) * PDF_RENDER_SCALE)
                part_starts.append(part_y)

            cumulative_height += int(clip_rect.height * PDF_RENDER_SCALE)
    finally:
        doc.close()

    cleaned = sorted({y for y in part_starts if y > 20})
    return cleaned


def split_image_into_blocks(image):
    blocks = []
    in_gap = False
    gap_start = None
    last_cut = 0

    for y in range(image.height):
        is_white_row = row_white_ratio(image, y) >= PDF_WHITE_ROW_RATIO

        if is_white_row and not in_gap:
            in_gap = True
            gap_start = y
        elif not is_white_row and in_gap:
            gap_height = y - gap_start
            if gap_height >= PDF_MAJOR_GAP_MIN_ROWS:
                cut = gap_start + (gap_height // 2)
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


def build_question_blocks(question, image, top_trim=0):
    part_starts = [
        max(0, y - top_trim)
        for y in find_part_starts_for_question(question)
    ]
    if not part_starts:
        return split_image_into_blocks(image)

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
        image_path = os.path.join(CROP_FOLDER, source_folder, image_name)
        if not os.path.exists(image_path):
            continue

        with Image.open(image_path) as image:
            question_image, trim_bbox = trim_outer_whitespace(image.convert("RGB"), return_bbox=True)
            image_width, image_height = question_image.size
            blocks = (
                build_question_blocks(question, question_image, top_trim=trim_bbox[1])
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
                horizontal_offset = PDF_NUMBER_BOX_WIDTH + PDF_NUMBER_PADDING_RIGHT if first_segment else 0
                usable_width = content_width - horizontal_offset
                scale = usable_width / block_width
                rendered_block_height = block_height * scale
                remaining_height = content_bottom - y_cursor

                if rendered_block_height <= remaining_height and first_segment:
                    pass
                elif rendered_block_height <= remaining_height:
                    pass
                elif rendered_block_height <= (content_bottom - PDF_MARGIN_TOP):
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
                    split_end_px = find_split_row(block_image, current_top_px, proposed_end_px, block_height)

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
    target_level = target_level or "P1"

    if target_level == "P4":
        return show_topic("P4", target_level="P4")

    full_index = load_json(INDEX_FILE)
    topic_list = build_topic_list(full_index, target_level)
    paper_list = build_paper_list(full_index, target_level)
    search_questions = build_global_question_list(full_index, target_level)

    return render_template(
        'dashboard.html',
        topics=topic_list,
        papers=paper_list,
        data={},
        search_questions=search_questions,
        current_topic=None,
        current_level=target_level
        ,
        current_level_name=get_level_name(target_level)
    )


@app.route('/topic/<path:topic_name>')
@app.route('/level/<target_level>/topic/<path:topic_name>')
def show_topic(topic_name, target_level=None):
    full_index = load_json(INDEX_FILE)

    if topic_name not in full_index:
        abort(404)

    topic_data = full_index[topic_name]
    questions_with_metadata = flatten_topic_questions(topic_data, topic_name)

    topic_list = build_topic_list(full_index, target_level)
    paper_list = build_paper_list(full_index, target_level)

    return render_template(
        'dashboard.html',
        topics=topic_list,
        papers=paper_list,
        data=questions_with_metadata,
        search_questions=[],
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
    question_title = request.args.get('title') or metadata["title"] or f"Question {q_num}"
    question_tags = [tag for tag in request.args.getlist('tag') if tag] or metadata["tags"]

    return render_template(
        'viewer.html',
        qp_img=qp_img,
        ms_img=ms_img,
        paper=paper,
        q_num=q_num,
        question_title=question_title,
        question_tags=question_tags,
        question_metadata=metadata,
    )


@app.route('/builder')
def paper_builder():
    return render_template('builder.html')


@app.route('/generate-paper', methods=['POST'])
def generate_paper():
    payload = request.get_json(silent=True) or {}
    requested_questions = payload.get("questions", [])
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
