from datasets import load_dataset

dataset = load_dataset("OpenMed/MedDialog")

# Print the overall structure
print("\n--- Dataset Structure ---")
print(dataset)

# Print a smaple conversation from the training split
print("\n--- Sample Conversation ---")
print(dataset["train"][0])