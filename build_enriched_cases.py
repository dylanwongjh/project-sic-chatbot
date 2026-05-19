# build_enriched_cases.py
import os
import json
from datasets import load_dataset
from openai import OpenAI # Modern OpenAI SDK used for LLM

# Initialise LLM client and folders
client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama", 
)

output_dir = "case_studies"
os.makedirs(output_dir, exist_ok=True)

existing_files = [f for f in os.listdir(output_dir) if f.endswith(".txt") and f.startswith("case_")]
start_count = len(existing_files)
print(f"Found {start_count} existing case files. New files will start at case_{start_count + 1:03d}.txt")

print("Loading MentalChat16K dataset...")
dataset = load_dataset("ShenLab/MentalChat16K")

# System prompt forcing the LLM to act as a clinical data architect for feature enrichment
CLINICAL_PROMPT = """
You are an expert clinical psychologist and  palliative care specialist. Your job is to analyse raw mental health counseling dialogue fragments and transform them into a highly structured clinical case study file.

Analyse the given interaction and output exactly in this Markdown structure:
=== CASE STUDY PROFILE ===
Topic: [Brief specific topic, e.g., Caregiver burnout, Anticipatory grief, etc.]

=== CLINICAL METADATA ===
Caregiver Profile: [Infer age, relationship, or context if possible, else "Not specified"]
Clinical Goal: [What the counselor is trying to achieve clinically]

=== PATIENT EMOTIONAL PROFILE ===
Primary Emotions: [Comma-separated list of 2-4 single words only, e.g., Guilt, Terror, Sadness]
Cognitive State: [Comma-separated list of 1-3 terms only, no examples or explanations, e.g., Catastrophizing, Flooding]
Underlying Need: [One short phrase, e.g., Emotional safety and control]

=== COMMUNICATION TECHNIQUES USED ===
[List specific techniques used by the counselor, e.g., Active listening, Validation, Reframing, etc.]

=== THE TRANSCRIPT ===
User: [User Text]
Counselor: [Counselor Text]
"""

# Process subset of files to prevent hitting the ChromaDB max batch size during ingestion
BATCH_CHUNK_SIZE = 15
processed_this_session = 0

print(f"Starting offline enrichment for {BATCH_CHUNK_SIZE} files...")

for i, item in enumerate(dataset["train"]):
    if processed_this_session >= BATCH_CHUNK_SIZE:
        break

    # Cleaning and Filtering
    user_input = item.get("input", "")
    counselor_output = item.get("output", "")

    # Skip rows with missing or broken dialogue
    if not user_input or not counselor_output:
        continue

    # Skip rows that are too short to hold meaningful clinical context
    if len(user_input) < 10 or len(counselor_output) < 10:
        continue

    if i < start_count:
        continue

    # Optional Palliative Filter
    target_keywords = ["palliative", "hospice", "end of life", "terminal", "dying", "loss", "death", "end-of-life"]
    combined_text = (user_input + " " + counselor_output).lower()
    if not any(keyword in combined_text for keyword in target_keywords):
        continue

    # Feature enrichment using LLM
    raw_dialogue_string = f"User: {user_input}\nCounselor: {counselor_output}"

    try:
        response = client.chat.completions.create( 
            model="llama3.1", # "openai/gpt-oss-120b" is good but costs money :(
            messages=[
                {"role": "system", "content": CLINICAL_PROMPT},
                {"role": "user", "content": f"Analyse this interaction:\n\n{raw_dialogue_string}"}
            ],
            temperature=0.2
        )

        enriched_case_data = response.choices[0].message.content

        start_count += 1
        processed_this_session += 1

        file_name = f"case_{start_count:03d}.txt"
        file_path = os.path.join(output_dir, file_name)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(enriched_case_data)
    
        print(f"[{processed_this_session}/{BATCH_CHUNK_SIZE}] Successfully cleaned and enriched: {file_name}")

    except Exception as e:
        print(f"Error processing case {i}: {e}")
        continue

print(f"\nBatch complete! Locally generated {processed_this_session} cases.")