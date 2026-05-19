# Switched from MedDiaLog to MentalChat16K dataset
import os
from datasets import load_dataset

# 1. Setup target directory
output_dir = "case_studies"
os.makedirs(output_dir, exist_ok=True)

print("Loading MentalChat16K dataset...")
dataset = load_dataset("ShenLab/MentalChat16K")

print(f"Extracting counseling dialogues to ./{output_dir}...")

count = 0
for i, item in enumerate(dataset["train"]):
    # Extraction (Depends on the structure of the dataset!!)
    instruction_value = item.get("instruction", "")
    instruction_text = instruction_value.strip() if isinstance(instruction_value, str) else ""
    input_value = item.get("input", "")
    input_text = input_value.strip() if isinstance(input_value, str) else ""
    output_value = item.get("output", "")
    output_text = output_value.strip() if isinstance(output_value, str) else ""

    # If both fields are empty, skip this entry
    if not input_text and not output_text:
        continue

    # Standardise text into a clean RAG-readable narrative
    case_content = []
    if instruction_text:
        case_content.append(f"Context/Instruction:\n{instruction_text}\n")

    case_content.append(f"User/Patient:\n{input_text}\n")
    case_content.append(f"Counselor/Coach:\n{output_text}")

    dialogue_text = "\n".join(case_content)

    # Build fle names matching project structure
    count += 1
    file_name = f"case_{count:03d}.txt"
    file_path = os.path.join(output_dir, file_name)

    # Save the file
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(dialogue_text)

    # Live tracking since the MentalChat16K dataset is large :D
    if count % 1000 == 0:
        print(f"Saved {count} mental health case files...")

print(f"\nSuccess! Extracted {count} highly relevant case studies into the '{output_dir}/' folder.")