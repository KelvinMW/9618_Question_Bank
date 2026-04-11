import csv
import json
import os

def generate_smart_index(csv_path, syllabus_guide_path):
    # 1. Load the Syllabus Guide
    if not os.path.exists(syllabus_guide_path):
        print(f"Error: {syllabus_guide_path} not found.")
        return

    with open(syllabus_guide_path, 'r', encoding='utf-8') as f:
        syllabus_guide = json.load(f)

    topic_index = {}

    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    # 2. Process the Mapping CSV
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f, skipinitialspace=True)

        for row in reader:
            if not row.get('folder') or row['folder'].lower() != 'qp':
                continue

            paper_name = row['filename']
            q_num = row['q_num']

            # Retrieve manual tags. If empty or 'nan', default to "Whole Topic"
            raw_manual_tags = str(row.get('manual_tag', '')).strip()
            if not raw_manual_tags or raw_manual_tags.lower() == 'nan':
                manual_tag_list = ["Whole Topic"]
            else:
                manual_tag_list = [t.strip() for t in raw_manual_tags.split(';') if t.strip()]

            # Handle Multi-Topic links (e.g., "1;7" or "P4")
            raw_input = str(row.get('topic', '')).split(';')
            topic_queries = [t.strip() for t in raw_input if t.strip()]

            matched_keys = []

            # --- THE MATCHING LOGIC FIX ---
            for t_query in topic_queries:
                # 1. Check for exact match first (Catches "P4", "21", "13.1")
                if t_query in syllabus_guide:
                    matched_keys.append(t_query)
                # 2. If it's a broad number with no dot (e.g. "1"), expand it to "1.1", "1.2"
                elif '.' not in t_query:
                    expanded = [k for k in syllabus_guide.keys() if k.startswith(f"{t_query}.")]
                    matched_keys.extend(expanded)

            # --- POPULATE THE INDEX ---
            for full_topic_key in matched_keys:
                if full_topic_key not in topic_index:
                    topic_index[full_topic_key] = {}

                for tag in manual_tag_list:
                    if tag not in topic_index[full_topic_key]:
                        topic_index[full_topic_key][tag] = []

                    # MARK SCHEME LINKING
                    ms_filename = paper_name.replace('_qp_', '_ms_')
                    ms_img_name = f"{ms_filename}_q{q_num}.png"
                    ms_path = os.path.join('static/crops/ms', ms_img_name)
                    found_ms = ms_img_name if os.path.exists(ms_path) else None

                    entry = {
                        "paper": paper_name,
                        "question": q_num,
                        "img": f"{paper_name}_q{q_num}.png",
                        "ms_img": found_ms,
                        "tags": manual_tag_list
                    }

                    # Prevent duplicates
                    if entry not in topic_index[full_topic_key][tag]:
                        topic_index[full_topic_key][tag].append(entry)

    # 4. Save to file (sort_keys=True ensures 21/P4 lands at the bottom)
    with open('topic_index.json', 'w', encoding='utf-8') as f:
        json.dump(topic_index, f, indent=4, sort_keys=True)

    print("Clean indexing complete! Technical sub-tags have been hidden and exact topics matched.")

if __name__ == "__main__":
    generate_smart_index(csv_path="map.csv", syllabus_guide_path="map.json")
