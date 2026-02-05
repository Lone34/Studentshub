"""
AI Tutor Module - Handles ChatGPT and Gemini API integrations
"""
import os
import re
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- OpenAI (ChatGPT) Configuration ---
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

# --- Google Gemini Configuration ---
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')

# Category keywords for auto-classification
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


def get_chatgpt_response(question: str, context: list = None) -> tuple:
    """
    Get response from OpenAI ChatGPT
    Returns: (response_text, error_message)
    """
    if not OPENAI_API_KEY:
        return None, "OpenAI API key not configured. Please add OPENAI_API_KEY to your .env file."
    
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        messages = [
            {
                "role": "system",
                "content": "You are an expert AI tutor helping students learn. Provide clear, educational explanations. Use examples when helpful. Format your responses with proper structure using markdown."
            }
        ]
        
        # Add conversation context if provided
        if context:
            for msg in context[-6:]:  # Keep last 6 messages for context
                messages.append(msg)
        
        messages.append({"role": "user", "content": question})
        
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages,
            max_tokens=2000,
            temperature=0.7
        )
        
        return response.choices[0].message.content, None
        
    except ImportError:
        return None, "OpenAI library not installed. Run: pip install openai"
    except Exception as e:
        return None, f"ChatGPT Error: {str(e)}"


def get_gemini_response(question: str, context: list = None) -> tuple:
    """
    Get response from Google Gemini
    Returns: (response_text, error_message)
    """
    if not GEMINI_API_KEY:
        return None, "Gemini API key not configured. Please add GEMINI_API_KEY to your .env file."
    
    try:
        import google.generativeai as genai
        
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel('gemini-pro')
        
        # Build prompt with context
        prompt = "You are an expert AI tutor helping students learn. Provide clear, educational explanations. Use examples when helpful.\n\n"
        
        if context:
            for msg in context[-6:]:
                role = "Student" if msg.get('role') == 'user' else "Tutor"
                prompt += f"{role}: {msg.get('content', '')}\n"
        
        prompt += f"Student: {question}\nTutor:"
        
        response = model.generate_content(prompt)
        
        return response.text, None
        
    except ImportError:
        return None, "Google Generative AI library not installed. Run: pip install google-generativeai"
    except Exception as e:
        return None, f"Gemini Error: {str(e)}"


def get_ai_response(provider: str, question: str, context: list = None) -> tuple:
    """
    Unified interface for getting AI responses
    
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
