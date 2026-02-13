"""
AI Tutor Module - Handles Gemini (Active) and ChatGPT (Test Mode) integrations

SETUP:
  1. Add your Gemini API key to .env:  GEMINI_API_KEY=your_key_here
  2. Get a free key from: https://aistudio.google.com/apikey
  3. ChatGPT is in TEST MODE — it returns a placeholder until you add OPENAI_API_KEY
"""
import os
import re
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ─── API Keys ───────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

# ─── Model Configuration ────────────────────────────────────────────
# Models verified available for this API key:
GEMINI_MODELS = [
    'gemini-2.0-flash-lite',   # Try lite first (likely best free quota)
    'gemini-flash-latest',     # Stable alias for 1.5 Flash
    'gemini-2.0-flash',        # Advanced, might hit quota
    'gemini-pro'               # Classic fallback
]
GEMINI_API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models'

GPT_MODEL = 'gpt-3.5-turbo'  # Will be used when OPENAI_API_KEY is set
GPT_TEST_MODE = not bool(OPENAI_API_KEY)  # Auto-detect test mode

# ─── System Prompt ──────────────────────────────────────────────────
SYSTEM_PROMPT = (
    "You are PanunSchool AI Tutor — a friendly, expert tutor helping students learn. "
    "Provide clear, well-structured educational explanations. "
    "Use examples, analogies, and step-by-step breakdowns when helpful. "
    "Format responses with markdown: use **bold** for key terms, bullet points for lists, "
    "and code blocks for equations or code. Keep answers concise but thorough."
)

# ─── Category Keywords ──────────────────────────────────────────────
CATEGORY_KEYWORDS = {
    'exams': ['exam', 'test', 'quiz', 'midterm', 'final', 'assessment', 'mcq', 'multiple choice'],
    'questions': ['solve', 'calculate', 'what is', 'how to', 'explain', 'find', 'determine'],
    'answers': ['answer', 'solution', 'result', 'output'],
    'news': ['latest', 'news', 'current', 'recent', 'update', '2024', '2025', '2026'],
    'homework': ['homework', 'assignment', 'project', 'task', 'exercise'],
    'concepts': ['concept', 'theory', 'definition', 'meaning', 'principle', 'law'],
}


def categorize_query(query: str) -> str:
    """Auto-categorize query based on keywords"""
    query_lower = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in query_lower:
                return category
    return 'general'


# ═══════════════════════════════════════════════════════════════════════
#  GEMINI (ACTIVE) — Google Gemini 2.0 Flash via REST API
# ═══════════════════════════════════════════════════════════════════════
def get_gemini_response(question: str, context: list = None) -> tuple:
    """
    Get response from Google Gemini (FREE tier).
    Tries multiple models in fallback order if quota is exceeded.
    
    Returns: (response_text, error_message)
    """
    if not GEMINI_API_KEY:
        return None, "Gemini API key not configured. Add GEMINI_API_KEY to your .env file."

    # Build conversation contents (shared across model attempts)
    contents = []

    if context:
        for msg in context[-6:]:
            role = 'user' if msg.get('role') == 'user' else 'model'
            contents.append({
                'role': role,
                'parts': [{'text': msg.get('content', '')}]
            })

    contents.append({
        'role': 'user',
        'parts': [{'text': question}]
    })

    payload = {
        'contents': contents,
        'systemInstruction': {
            'parts': [{'text': SYSTEM_PROMPT}]
        },
        'generationConfig': {
            'temperature': 0.7,
            'maxOutputTokens': 2048,
            'topP': 0.95,
        }
    }

    last_error = None

    # Try each model in order until one works
    for model_name in GEMINI_MODELS:
        try:
            url = f'{GEMINI_API_BASE}/{model_name}:generateContent?key={GEMINI_API_KEY}'

            response = requests.post(
                url,
                headers={'Content-Type': 'application/json'},
                json=payload,
                timeout=30
            )

            # If quota exceeded (429 or 403), try next model
            if response.status_code in (429, 403):
                error_data = response.json()
                last_error = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                print(f"[AI Tutor] {model_name} quota exceeded, trying next model...")
                continue

            if response.status_code != 200:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', f'HTTP {response.status_code}')
                return None, f"Gemini API Error: {error_msg}"

            data = response.json()

            candidates = data.get('candidates', [])
            if not candidates:
                return None, "Gemini returned an empty response. Try rephrasing your question."

            text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            if not text:
                return None, "Gemini returned an empty response."

            print(f"[AI Tutor] Response from {model_name} ✓")
            return text, None

        except requests.exceptions.Timeout:
            last_error = f"{model_name} timed out"
            continue
        except requests.exceptions.ConnectionError:
            return None, "Could not connect to Gemini API. Check your internet connection."
        except Exception as e:
            last_error = str(e)
            continue

    # All models failed
    return None, f"All Gemini models exhausted. Last error: {last_error}"


# ═══════════════════════════════════════════════════════════════════════
#  CHATGPT (TEST MODE) — Will activate when OPENAI_API_KEY is set
# ═══════════════════════════════════════════════════════════════════════
def get_chatgpt_response(question: str, context: list = None) -> tuple:
    """
    Get response from OpenAI ChatGPT.
    
    TEST MODE: Returns a placeholder message when OPENAI_API_KEY is not set.
    LIVE MODE: Calls the OpenAI API when the key is configured.
    
    Returns: (response_text, error_message)
    """
    if GPT_TEST_MODE:
        return None, (
            "🔧 **ChatGPT is in Test Mode**\n\n"
            "ChatGPT integration is ready but not yet activated. "
            "To enable it, add your OpenAI API key to the `.env` file:\n\n"
            "```\nOPENAI_API_KEY=sk-your-key-here\n```\n\n"
            "For now, Gemini AI is handling all your questions! ✨"
        )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add conversation context
        if context:
            for msg in context[-6:]:
                messages.append(msg)

        messages.append({"role": "user", "content": question})

        response = client.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            max_tokens=2000,
            temperature=0.7
        )

        return response.choices[0].message.content, None

    except ImportError:
        return None, "OpenAI library not installed. Run: pip install openai"
    except Exception as e:
        return None, f"ChatGPT Error: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════
#  UNIFIED INTERFACE
# ═══════════════════════════════════════════════════════════════════════
def get_ai_response(provider: str, question: str, context: list = None) -> tuple:
    """
    Unified interface for getting AI responses.

    Args:
        provider: 'chatgpt' or 'gemini'
        question: User's question
        context: Previous conversation messages

    Returns:
        (response_text, category, error_message)
    """
    category = categorize_query(question)

    if provider == 'chatgpt':
        response, error = get_chatgpt_response(question, context)
    elif provider == 'gemini':
        response, error = get_gemini_response(question, context)
    else:
        return None, category, f"Unknown provider: {provider}"

    return response, category, error

def generate_quiz(subject: str, grade: str, difficulty: str = 'hard') -> list:
    """
    Generates a strict and difficult quiz using Gemini.
    Uses its own API call with higher token limit to avoid truncation.
    Returns a list of dicts:
    [
        {
            "question": "...",
            "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
            "answer": "A",
            "explanation": "..."
        },
        ...
    ]
    """
    if not GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY not configured")
        return []

    prompt = (
        f"Generate exactly 5 DIFFICULT, APPLICATION-BASED multiple-choice questions for {grade} {subject}. "
        f"Difficulty: {difficulty.upper()}. "
        "No simple definitions. Questions must require critical thinking and problem-solving. "
        "Keep questions and options CONCISE (1-2 sentences max). "
        "Keep explanations SHORT (1-2 sentences). "
        "Respond with ONLY a valid JSON array. No markdown, no extra text. "
        "Format: [{\"question\": \"...\", \"options\": {\"A\": \"...\", \"B\": \"...\", \"C\": \"...\", \"D\": \"...\"}, \"answer\": \"A\", \"explanation\": \"...\"}]"
    )

    payload = {
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': 0.8,
            'maxOutputTokens': 8192,
            'topP': 0.95,
        }
    }

    import json as json_mod

    # Try up to 2 times in case of truncated response
    for attempt in range(2):
        for model_name in GEMINI_MODELS:
            try:
                url = f'{GEMINI_API_BASE}/{model_name}:generateContent?key={GEMINI_API_KEY}'
                response = requests.post(
                    url,
                    headers={'Content-Type': 'application/json'},
                    json=payload,
                    timeout=45
                )

                if response.status_code in (429, 403):
                    print(f"[Quiz] {model_name} quota exceeded, trying next...")
                    continue

                if response.status_code != 200:
                    print(f"[Quiz] {model_name} error: HTTP {response.status_code}")
                    continue

                data = response.json()
                candidates = data.get('candidates', [])
                if not candidates:
                    continue

                text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                if not text:
                    continue

                # Clean up response
                clean = text.strip()
                if clean.startswith('```json'):
                    clean = clean[7:]
                if clean.startswith('```'):
                    clean = clean[3:]
                if clean.endswith('```'):
                    clean = clean[:-3]
                clean = clean.strip()

                print(f"[Quiz] Attempt {attempt+1}, model {model_name}: got {len(clean)} chars")

                quiz_data = json_mod.loads(clean)

                # Validate structure
                if not isinstance(quiz_data, list) or len(quiz_data) == 0:
                    print(f"[Quiz] Invalid structure, retrying...")
                    continue

                valid_questions = []
                for q in quiz_data:
                    if all(k in q for k in ('question', 'options', 'answer', 'explanation')):
                        if isinstance(q['options'], dict) and len(q['options']) >= 4:
                            valid_questions.append(q)

                if len(valid_questions) >= 3:  # Accept if at least 3 valid questions
                    print(f"[Quiz] Success: {len(valid_questions)} valid questions generated ✓")
                    return valid_questions
                else:
                    print(f"[Quiz] Only {len(valid_questions)} valid questions, retrying...")
                    continue

            except json_mod.JSONDecodeError as e:
                print(f"[Quiz] JSON parse error on {model_name}: {e}")
                continue
            except requests.exceptions.Timeout:
                print(f"[Quiz] {model_name} timed out")
                continue
            except Exception as e:
                print(f"[Quiz] Unexpected error: {e}")
                continue

    print("[Quiz] All attempts failed to generate valid quiz")
    return []
