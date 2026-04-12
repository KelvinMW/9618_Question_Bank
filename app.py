from flask import Flask, render_template, send_from_directory, abort, request
import json
import os
import re
from collections import OrderedDict

app = Flask(__name__)

# --- CONFIGURATION ---
INDEX_FILE = 'topic_index.json'
MANUAL_TITLES_FILE = 'manual_titles.json'
SYLLABUS_FILE = 'map.json'
CROP_FOLDER = 'static/crops'


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


def is_in_level(topic_key, level):
    topic_key = str(topic_key)

    if level is None:
        return True

    if topic_key == "P4":
        return level == "AL"

    try:
        match = re.search(r'(\d+)', topic_key)
        if match:
            major_num = int(match.group(1))
            if level == 'AS':
                return 1 <= major_num <= 12
            if level == 'AL':
                return 13 <= major_num <= 25
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
                }

    return {
        "title": None,
        "tags": [],
    }


# --- ROUTES ---

@app.route('/')
@app.route('/level/<target_level>')
def home(target_level=None):
    full_index = load_json(INDEX_FILE)
    topic_list = build_topic_list(full_index, target_level)

    return render_template(
        'dashboard.html',
        topics=topic_list,
        data={},
        current_topic=None,
        current_level=target_level
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

    return render_template(
        'dashboard.html',
        topics=topic_list,
        data=questions_with_metadata,
        current_topic=topic_name,
        current_level=target_level
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
        question_tags=question_tags
    )


@app.route('/crops/<folder>/<path:filename>')
def serve_crops(folder, filename):
    return send_from_directory(os.path.join(CROP_FOLDER, folder), filename)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
