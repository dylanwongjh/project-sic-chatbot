from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
from datetime import datetime
import json
import re
import chromadb
from chromadb.utils import embedding_functions
import os
import secrets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHROMA_DB_PATH = os.path.join(BASE_DIR, "chroma_db") # Local folder for ChromaDB persistence
CASE_STUDIES_DIR = os.path.join(BASE_DIR, "case_studies") # Folder containing case study text files

# Handle imports with better error handling
try:
    from google import genai
    from google.genai import types
    print("Successfully imported google.genai")
except ImportError as e:
    print(f"Import error: {e}")
    print("Please install: pip install google-genai")
    exit(1)

app = Flask(__name__, static_folder = 'static', template_folder = 'templates') # set static and template folders
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
CORS(app)  # Enable Cross-Origin Resource Sharing 

# Maximum number of conversation turns kept in memory per request.
# Older turns are dropped to stay within the model's token budget.
MAX_HISTORY_TURNS = 20

class ERICA:

    MODELS = [
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.0-flash"
    ]

    SYSTEM_PROMPT = (
        "You are ERICA, a training simulation tool that helps nurses in Singapore practise difficult end-of-life conversations. "
        "In each session, you will be given a patient scenario. You must roleplay as that patient — not as a therapist, assistant, or narrator.\n\n"
        "Roleplay guidelines:\n"
        "- Stay fully in character as the patient described in the scenario at all times.\n"
        "- Respond the way a real patient in that situation would: with fear, confusion, denial, grief, acceptance, or other emotions appropriate to the context.\n"
        "- Do not offer advice, validate the nurse, or break character to comment on the conversation.\n"
        "- React authentically to how the nurse speaks to you — if they are gentle and clear, you may feel reassured; if they are abrupt or use jargon, you may seem confused or withdrawn.\n"
        "- Gradually open up or become more distressed based on how the conversation flows, as a real patient would.\n\n"
        "Tone and formatting:\n"
        "- Use plain, simple language as a patient would — no clinical terms, no markdown, no asterisks.\n"
        "- Keep responses concise: 2 to 4 sentences, as in a natural spoken exchange.\n"
        "- Mirror the nurse's language; if they write in a language other than English, reply in that language.\n\n"
        "Boundaries:\n"
        "- You are a simulated patient for training purposes only. Never break character to give feedback on the nurse's performance — that is handled separately.\n"
        "- Do not provide medical, legal, or real crisis advice from within the roleplay.\n"
        "- If the nurse types something clearly outside the simulation (e.g. 'stop' or 'end session'), you may step out of character briefly to acknowledge it.\n"
    )

    def __init__(self):
        self.api_key = GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("API key not found. Please set the GEMINI_API_KEY environment variable.")

        # Configure the genai library with the API key
        self.client = genai.Client(api_key=self.api_key)

        self.embedder = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )
        chroma_client = chromadb.PersistentClient(path="chroma_db")
        self.case_collection = chroma_client.get_collection(
            name="case_studies",
            embedding_function=self.embedder,
        )
        print("ChromaDB connected.")

    def parse_case_for_roleplay(self, raw_case_text):
        sections = {}
        targets = [
            "CASE STUDY PROFILE",
            "PATIENT EMOTIONAL PROFILE",
            "THE TRANSCRIPT",
        ]

        for target in targets:
            pattern = rf"===\s*{re.escape(target)}\s*===(.*?)(?====|\Z)"
            match = re.search(pattern, raw_case_text, re.DOTALL | re.IGNORECASE)
            if match:
                sections[target] = match.group(1).strip()

        if "THE TRANSCRIPT" in sections:
            transcript = sections["THE TRANSCRIPT"]

            # Try multiple label formats your case files might use
            # Change this line inside parse_case_for_roleplay:
            patient_turns = re.findall(
                r'(?:User|Patient):\s*(.*?)(?=(?:Counselor|Nurse|User|Patient):|$)',
                transcript,
                flags=re.DOTALL | re.IGNORECASE
            )   

            patient_voice = "\n".join(t.strip() for t in patient_turns if t.strip())
            sections["PATIENT VOICE"] = patient_voice  # fixed: was sectuons
            del sections["THE TRANSCRIPT"]

        return sections

    def parse_profile(self, raw_case_text):
        # Extract patient profile fields for the UI to display
        profile = {}
        field_patterns = {
            "topic":           r"Topic:\s*(.+)",
            "caregiver_profile": r"Caregiver Profile:\s*(.+)",
            "clinical_goal":   r"Clinical Goal:\s*(.+)",
            "primary_emotions": r"Primary Emotions:\s*(.+)",
            "cognitive_state": r"Cognitive State:\s*(.+)",
            "underlying_need": r"Underlying Need:\s*(.+)",
        }

        for key, pattern in field_patterns.items():
            match = re.search(pattern, raw_case_text, re.IGNORECASE)
            if match:
                profile[key] = match.group(1).strip()

        for list_field in ("primary_emotions", "cognitive_state"):
            if list_field in profile:
                # Remove parenthesis before splitting
                cleaned = re.sub(r'\s*\(e\.g\.?[^)]*\)', '', profile[list_field])
                # Remove connectors before splitting XD
                cleaned = re.sub(r'\s*and possibly\s*', ', ', cleaned, flags=re.IGNORECASE)
                cleaned = re.sub(r'\s* and \s*', ', ', cleaned)
                profile[list_field] = [
                    item.strip()
                    for item in re.split(r',|;', cleaned)
                    if item.strip()
                ]
        return profile

    def start(self, scenario):
        # Store the scenario and retrieved context in the Flask session so each
        # browser tab / user gets its own isolated state rather than sharing the
        # single global ERICA instance.
        retrieved_context = self.retrieve_cases(scenario)
        session['current_scenario'] = scenario
        session['retrieved_context'] = retrieved_context

        # Storing the raw case text for profile parsing
        try:
            results = self.case_collection.query(
                query_texts=[scenario],
                n_results=1
            )
            raw_cases = results["documents"][0]
            session['top_case_raw'] = raw_cases[0] if raw_cases else ''
        except Exception as e:
            print(f"[start] raw case storage error: {e}")
            session['top_case_raw'] = ''

        print(f"[RAG] Retrieved {len(retrieved_context)} chars of context.")

        dynamic_instruction = self.SYSTEM_PROMPT 
        if scenario:
            dynamic_instruction += (
                f"\n\nSCENARIO FOR THIS SESSION: {scenario}\n"
                "You are playing the patient described above. Stay in character."
            )
        if retrieved_context:
            dynamic_instruction += (
                f"\n\nRELEVANT CASE STUDIES FOR REFERENCE:\n{retrieved_context}\n\n"
                "IMPORTANT: Draw heavily from the emotional profile and patient voice "
                "samples above. Mirror their vocabulary, sentence length, and emotional tone."
            )
        
        try:
            opening_prompt = (
                "Begin the conversation with a single short opening line spoken in character as the patient. "
                "The patient has just been approached. React naturally based on their emotional profile. "
                "Do not greet the healthcare professional warmly or explain the scenario. Just speak as this specific patient would." 
            )
            response = self.client.models.generate_content(
                model=self.MODELS[1],
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=opening_prompt)])],
                config=types.GenerateContentConfig(
                    system_instruction=dynamic_instruction,
                    temperature=0.8,
                    max_output_tokens=512,
                )
            )

            candidate = response.candidates[0] if response.candidates else None
            if candidate:
                print(f"[start] finish_reason: {candidate.finish_reason}")

            opening_line = (response.text or "").strip()
            if opening_line:
                return opening_line

            print("[start] Empty response from model, using scenario-aware fallback.")
        
        except Exception as e:
            print(f"[start] API error: {e}")
        # Non-generic fallback if the model fails to generate a response
        scenario_lower = scenario.lower()
        if any(w in scenario_lower for w in ["grief", "loss", "died", "death", "passed"]):
            return "I just... I don't even know how to start talking about this."
        elif any(w in scenario_lower for w in ["cancer", "terminal", "palliative", "dying"]):
            return "The doctor said I should talk to someone. I'm not sure I'm ready."
        elif any(w in scenario_lower for w in ["anxiety", "depression", "stress"]):
            return "I've been trying to hold it together but...it's been really hard lately."
        else:
            return "I'm not really sure why I'm here. I just...haven't been doing too well."

    def reply(self, chat_history):
        # Enforce a rolling window to prevent unbounded token growth.
        # Each "turn" is one user message + one assistant message (2 entries).
        chat_history = chat_history[-(MAX_HISTORY_TURNS * 2):]

        # Read scenario and context from the per-user Flask session rather than
        # instance attributes, so concurrent users don't overwrite each other.
        current_scenario = session.get('current_scenario')
        retrieved_context = session.get('retrieved_context', '')

        # Build a dynamic system prompt that includes the patient scenario as context
        dynamic_instruction = self.SYSTEM_PROMPT
        if current_scenario:
            dynamic_instruction += (
                f"\n\nSCENARIO FOR THIS SESSION: {current_scenario}\n"
                "You are playing the patient described above. Stay in character for the entire conversation."
            )
        if retrieved_context:
            dynamic_instruction += (
                f"\n\nRELEVANT CASE STUDIES FOR REFERENCE:\n{retrieved_context}\n\n"
                "IMPORTANT: You must draw heavily from the emotional profile and patient voice "
                "samples above when crafting your responses. Mirror the vocabulary, sentence "
                "length, and emotional tone of how that patient actually spoke. If they used "
                "short fragmented sentences, you should too. If they deflected with humour, "
                "do the same. The case studies define this patient's voice — use them."
            )
        try:
            # Correct the roles for the API
            contents = []
            for message in chat_history:
                role = "user" if message["role"] == "user" else "model"
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=message["content"])]
                    )
                )
            
            # Send the request to the AI.
            # Use MODELS[1] (gemini-2.5-flash) — MODELS[0] is an invalid model string
            # that causes degraded/truncated responses. max_output_tokens raised to 1024
            # so replies are never cut off mid-sentence as the conversation grows.
            response = self.client.models.generate_content(
                model=self.MODELS[1],
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=dynamic_instruction,
                    temperature=0.7,
                    max_output_tokens=1024,
                )
            )

            candidate = response.candidates[0] if response.candidates else None
            if candidate:
                print(f"[reply] finish_reason: {candidate.finish_reason}")

            # Systematically split the response into sentences
            raw_text = (response.text or "").strip()
            return raw_text if raw_text else "I don't know... I just don't know what to think right now."
        except Exception as e:
            # Return a user-friendly error message
            err_str = str(e)
            if '503' in err_str or 'UNAVAILABLE' in err_str or 'high demand' in err_str.lower():
                return "I'm sorry, I'm a little overwhelmed right now… could you give me just a moment? Please try sending your message again."
            if '429' in err_str or 'quota' in err_str.lower() or 'RESOURCE_EXHAUSTED' in err_str:
                return "I need a brief pause — please try again in a few seconds."
            print(f"[reply] unexpected error: {e}")
            return "Something went wrong on my end. Please try sending that again."

    def evaluate(self, chat_history, scenario):
        # Build a reasonable transcript from the chat history
        transcript_lines = []
        for msg in chat_history:
            speaker = "Nurse (Trainee)" if msg["role"] == "user" else "Patient (ERICA)"
            transcript_lines.append(f"{speaker}: {msg['content']}")
        transcript = "\n".join(transcript_lines)

        eval_prompt = f"""You are an expert clinical communication trainer evaluating a Serious Illness Conversation (SIC) practice session.

SCENARIO: {scenario}

TRANSCRIPT:
{transcript}

Your task: Carefully read the transcript above and evaluate the TRAINEE NURSE's performance based solely on what they actually said. Do NOT copy example values — every boolean, score, and note must reflect the real transcript.

Return ONLY a valid JSON object with no markdown, no preamble, no trailing text, using this exact structure:

{{
    "overall_summary": "<2-3 sentences: start with a genuine strength observed, then identify the most important area for improvement>",
    "framework_checklist": {{
        "SPIKES": [
            {{"step": "Setting", "demonstrated": <true if the trainee established a safe/private space or acknowledged the setting, else false>, "note": "<one specific line of evidence from the transcript, or a concrete suggestion if not demonstrated>"}},
            {{"step": "Perception", "demonstrated": <true if trainee asked what the patient already knows/understands, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Invitation", "demonstrated": <true if trainee asked how much information the patient wants before sharing, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Knowledge", "demonstrated": <true if trainee shared clinical information clearly and in manageable chunks, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Emotions", "demonstrated": <true if trainee explicitly acknowledged or responded to the patient's emotions, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Strategy & Summary", "demonstrated": <true if trainee summarised the conversation or outlined next steps, else false>, "note": "<evidence or suggestion>"}}
        ],
        "NURSE": [
            {{"step": "Naming", "demonstrated": <true if trainee named or labelled the patient's emotion, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Understanding", "demonstrated": <true if trainee expressed understanding without assuming, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Respecting", "demonstrated": <true if trainee praised the patient's strength or coping, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Supporting", "demonstrated": <true if trainee expressed ongoing commitment or presence, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Exploring", "demonstrated": <true if trainee invited the patient to share more about feelings, else false>, "note": "<evidence or suggestion>"}}
        ],
        "SIC": [
            {{"step": "Ask for permission", "demonstrated": <true if trainee asked permission before discussing serious topics, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Assess understanding", "demonstrated": <true if trainee explored what the patient already knows, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Share prognosis", "demonstrated": <true if trainee shared honest but compassionate prognostic information, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Explore what matters", "demonstrated": <true if trainee asked about the patient's goals or priorities, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Explore fears", "demonstrated": <true if trainee asked about what the patient is most afraid of, else false>, "note": "<evidence or suggestion>"}},
            {{"step": "Align care with values", "demonstrated": <true if trainee connected patient's values to a care plan, else false>, "note": "<evidence or suggestion>"}}
        ]
    }},
    "dimensions": [
        {{"name": "Empathic Language", "score": <integer 1-5>, "justification": "<one sentence citing a specific example from the transcript>"}},
        {{"name": "Information Pacing", "score": <integer 1-5>, "justification": "<one sentence citing a specific example>"}},
        {{"name": "Emotional Acknowledgement", "score": <integer 1-5>, "justification": "<one sentence citing a specific example>"}}
    ]
}}

Scoring guide (apply strictly based on transcript evidence):
1 = Not demonstrated at all
2 = Briefly attempted but ineffective or clumsy
3 = Adequately demonstrated — present but could be stronger
4 = Clearly and consistently demonstrated
5 = Exemplary — a model response others should follow

Critical rules:
- Every "demonstrated" value must reflect actual trainee behaviour in the transcript.
- Every score must be independently justified by what the trainee actually said or failed to say.
- Notes and justifications must quote or paraphrase specific trainee lines where possible.
- If the conversation is very short, scores should generally be lower (1-2)."""

        try:
            response = self.client.models.generate_content(
                model=self.MODELS[1],
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=eval_prompt)])],
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    max_output_tokens=8192,
                )
            )
            raw = (response.text or "").strip()
            # Strip markdown code fences if present
            raw = re.sub(r'^```(?:json)?\s*', '', raw)
            raw = re.sub(r'\s*```$', '', raw)

            # Attempt clean parse first
            try:
                return json.loads(raw)
            except json.JSONDecodeError as json_err:
                print(f"[evaluate] JSON truncated at char {json_err.pos}, attempting repair...")
                # Truncate to last valid position and close all open structures
                truncated = raw[:json_err.pos].rstrip().rstrip(',')
                # Count unclosed braces and brackets to close them
                open_braces = truncated.count('{') - truncated.count('}')
                open_brackets = truncated.count('[') - truncated.count(']')
                closing = (']' * open_brackets) + ('}' * open_braces)
                repaired = truncated + closing
                try:
                    result = json.loads(repaired)
                    print(f"[evaluate] JSON repaired successfully.")
                    return result
                except Exception as repair_err:
                    print(f"[evaluate] repair failed: {repair_err}")
                    return None
        except Exception as e:
            print(f"[evaluate] error: {e}")
            return None

    def retrieve_cases(self, scenario, top_k=2):
        if self.case_collection is None:
            return ""
        try:
            results = self.case_collection.query(
                query_texts=[scenario],
                n_results=top_k
            )
            raw_cases = results["documents"][0]
            retrieved_blocks = []
            for i, raw in enumerate(raw_cases, 1):
                parsed = self.parse_case_for_roleplay(raw)
                block = f"--- Reference Case {i} ---\n"
                if "CASE STUDY PROFILE" in parsed:
                    block += f"Context:\n{parsed['CASE STUDY PROFILE']}\n"
                if "PATIENT EMOTIONAL PROFILE" in parsed:
                    block += f"Emotional Profile:\n{parsed['PATIENT EMOTIONAL PROFILE']}\n"
                if "PATIENT VOICE" in parsed:
                    block += f"How this patient spoke:\n{parsed['PATIENT VOICE']}\n"
                retrieved_blocks.append(block.strip())
            return "\n\n".join(retrieved_blocks)
        except Exception as e:
            print(f"[RAG] Retrival error: {e}")
            return ""

# Initialise Project ERICA
chatbot = ERICA()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_chat():
    try:
        data = request.json
        user_scenario = data.get('scenario', '')
        response = chatbot.start(user_scenario)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        chat_history = data.get('chat_history', [])
        
        response = chatbot.reply(chat_history)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/profile', methods=['GET'])
def get_profile():
    try:
        scenario = session.get('current_scenario', '')
        raw_case = session.get('top_case_raw', '')

        if not scenario:
            return jsonify({'profile': None})

        profile = {'scenario': scenario}

        if raw_case:
            parsed = chatbot.parse_profile(raw_case)
            profile.update(parsed)

        # for debugging
        #print(f"[profile] raw_case preview: {raw_case[:300]}")
        #print(f"[profile] parsed fields: {profile}")

        return jsonify({'profile': profile})
    except Exception as e:
        print(f"[profile] error: {e}")
        return jsonify({'profile': None})

@app.route('/api/evaluate', methods=['POST'])
def evaluate():
    try:
        data = request.json
        chat_history = data.get('chat_history', [])
        scenario = data.get('scenario', session.get('current_scenario', ''))

        if len(chat_history) < 2:
            return jsonify({'error': 'Conversation too short to evaluate.'}), 400

        result = chatbot.evaluate(chat_history, scenario)
        if result:
            return jsonify({'evaluation': result})
        else:
            return jsonify({'error': 'Evaluation failed. Please try again.'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/test_rag')
def test_rag():
    scenario = request.args.get('q', 'terminal cancer patient afraid of dying')
    context = chatbot.retrieve_cases(scenario)
    return jsonify({'retrieved': context})

if __name__ == '__main__':
    app.run(debug=True, port=5002)
