import os
import shutil
import glob

def cleanup_orphaned_ms():
    # Define folder paths (assuming script is run from the parent directory)
    ms_dir = 'ms'
    qp_dir = 'qp'
    dup_dir = 'duplicate_papers'

    # Create the duplicate folder if it doesn't exist
    if not os.path.exists(dup_dir):
        os.makedirs(dup_dir)
        print(f"Created directory: {dup_dir}")

    # Search for files matching the pattern: yy_month_ms_xx.pdf
    # This captures the year, month, and variant/component
    ms_files = glob.glob(os.path.join(ms_dir, "*_ms_*.pdf"))

    moved_count = 0
    checked_count = 0

    print("Starting cleanup process...")

    for ms_path in ms_files:
        ms_filename = os.path.basename(ms_path)

        # Determine the matching QP filename by replacing '_ms_' with '_qp_'
        qp_filename = ms_filename.replace('_ms_', '_qp_')
        qp_path = os.path.join(qp_dir, qp_filename)

        # Check if the QP version exists
        if not os.path.exists(qp_path):
            # Move the orphaned MS file to the duplicate/orphaned folder
            dest_path = os.path.join(dup_dir, ms_filename)
            shutil.move(ms_path, dest_path)
            print(f"Moved: {ms_filename} (No matching QP found)")
            moved_count += 1

        checked_count += 1

    print("-" * 30)
    print(f"Cleanup complete.")
    print(f"Total MS files checked: {checked_count}")
    print(f"Files moved to '{dup_dir}': {moved_count}")

if __name__ == "__main__":
    cleanup_orphaned_ms()
