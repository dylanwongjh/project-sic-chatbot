# clean_cases.py
# Strips the Context/Instruction blocks and the Counselor/Coach responses from the case files.

import os 
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CASE_STUDIES_DIR = os.path.join(BASE_DIR, "case_studies")

def extract_patient_text(raw_text):
    # Remove the Context/Instruction block entirely
    raw_text = re.sub(
        r'Context/Instruction:.*?(?=User/Patient:|$)',
        '',
        raw_text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Extract only the User/Patient block
    patient_turns = re.findall(
        r'User/Patient:\s*(.*?)(?=Counselor/Coach:|User/Patient:|$)',
        raw_text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Join multiple patient turns if present, clean up whitespace
    cleaned = "/n".join(turn.strip() for turn in patient_turns if turn.strip())
    return cleaned

def clean_all():
    files = [f for f in os.listdir(CASE_STUDIES_DIR) if f.endswith(".txt")]
    skipped = 0
    cleaned = 0

    for filename in files:
        filepath = os.path.join(CASE_STUDIES_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            raw_text = f.read()

        patient_text = extract_patient_text(raw_text)

        if not patient_text or len(patient_text) < 30:
            # Skip files with no meaningful patient content
            os.remove(filepath)
            skipped += 1
            continue

        # Overwrite the file with the cleaned patient text
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(patient_text)
        cleaned += 1

        if cleaned % 1000 == 0:
            print(f"Cleaned {cleaned} files...")


    print(f"\nDone. Cleaned {cleaned} files, {skipped} empty/irrelevant files removed.")

if __name__ == "__main__":
    clean_all()