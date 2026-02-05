"""
Library module for document processing
- PDF/Image upload handling
- OCR text extraction using Gemini
- Document formatting
"""

import os
from werkzeug.utils import secure_filename
from datetime import datetime
import base64

# Allowed file extensions
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB

# Upload folder
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', 'library')

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(filename):
    """Get file type category"""
    ext = filename.rsplit('.', 1)[1].lower()
    if ext == 'pdf':
        return 'pdf'
    return 'image'

def save_uploaded_file(file, user_id):
    """
    Save uploaded file and return file path
    Returns: (file_path, file_type, error)
    """
    if not file or file.filename == '':
        return None, None, "No file selected"
    
    if not allowed_file(file.filename):
        return None, None, "Invalid file type. Allowed: PDF, PNG, JPG, JPEG, GIF, WEBP"
    
    # Create upload directory if not exists
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Generate unique filename
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_filename = f"{user_id}_{timestamp}_{filename}"
    
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    file_type = get_file_type(filename)
    
    try:
        file.save(file_path)
        return file_path, file_type, None
    except Exception as e:
        return None, None, f"Error saving file: {str(e)}"

def extract_text_with_gemini(file_path, file_type):
    """
    Extract text from document using Gemini Vision API
    Returns: (extracted_text, error)
    """
    try:
        import google.generativeai as genai
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            return None, "Gemini API key not configured"
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if file_type == 'image':
            # Read image and convert to base64
            with open(file_path, 'rb') as f:
                image_data = f.read()
            
            # Get mime type
            ext = file_path.rsplit('.', 1)[1].lower()
            mime_types = {
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'gif': 'image/gif',
                'webp': 'image/webp'
            }
            mime_type = mime_types.get(ext, 'image/jpeg')
            
            # Create image part
            image_part = {
                "mime_type": mime_type,
                "data": base64.b64encode(image_data).decode('utf-8')
            }
            
            prompt = """Extract ALL text from this document image. 
            Preserve the structure, headings, paragraphs, and any lists.
            If it's an exam paper, preserve questions and any options.
            If it's notes, preserve the outline structure.
            Return only the extracted text, well formatted."""
            
            response = model.generate_content([prompt, image_part])
            return response.text, None
            
        elif file_type == 'pdf':
            # For PDF, we need to read pages as images
            # Try using pdf2image if available, otherwise just note it's a PDF
            try:
                from pdf2image import convert_from_path
                
                # Convert PDF pages to images
                images = convert_from_path(file_path, first_page=1, last_page=5)  # Limit to 5 pages
                
                all_text = []
                for i, image in enumerate(images):
                    # Save temp image
                    import io
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format='PNG')
                    img_byte_arr = img_byte_arr.getvalue()
                    
                    image_part = {
                        "mime_type": "image/png",
                        "data": base64.b64encode(img_byte_arr).decode('utf-8')
                    }
                    
                    prompt = f"""Extract ALL text from page {i+1} of this document.
                    Preserve structure, headings, and formatting."""
                    
                    response = model.generate_content([prompt, image_part])
                    all_text.append(f"--- Page {i+1} ---\n{response.text}")
                
                return "\n\n".join(all_text), None
                
            except ImportError:
                # pdf2image not installed - try basic text extraction
                try:
                    import PyPDF2
                    with open(file_path, 'rb') as f:
                        reader = PyPDF2.PdfReader(f)
                        text = []
                        for page in reader.pages[:10]:  # Limit to 10 pages
                            text.append(page.extract_text() or '')
                        return "\n\n".join(text), None
                except:
                    return "PDF uploaded - text extraction pending", None
        
        return None, "Unsupported file type"
        
    except Exception as e:
        return None, f"OCR Error: {str(e)}"

def format_document_content(extracted_text, doc_type, title):
    """
    Use AI to format extracted text into a proper document
    Returns: (formatted_content, error)
    """
    if not extracted_text:
        return None, "No text to format"
    
    try:
        import google.generativeai as genai
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            return extracted_text, None  # Return raw text if no API
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        doc_prompts = {
            'exam': f"""Format this text as a proper exam paper titled "{title}".
                Structure it with:
                - Clear question numbers
                - Properly formatted options (A, B, C, D) if multiple choice
                - Section headers if applicable
                - Mark allocations if visible
                Keep all content, just improve formatting.""",
            
            'notes': f"""Format this text as proper study notes titled "{title}".
                Structure with:
                - Clear headings and subheadings
                - Bullet points for key concepts
                - Numbered lists for steps/processes
                - Bold important terms
                Keep all content, just improve organization.""",
            
            'paper': f"""Format this as an academic paper/assignment titled "{title}".
                Maintain academic structure with sections.
                Keep all content, just improve formatting.""",
            
            'assignment': f"""Format this as a homework/assignment document titled "{title}".
                Structure with clear questions/tasks.
                Keep all content, just improve formatting."""
        }
        
        prompt = doc_prompts.get(doc_type, doc_prompts['notes'])
        prompt += f"\n\nContent to format:\n{extracted_text[:8000]}"  # Limit text length
        
        response = model.generate_content(prompt)
        return response.text, None
        
    except Exception as e:
        return extracted_text, f"Formatting error: {str(e)}"

def search_documents(query, limit=20):
    """
    Search documents by title, description, or content
    Returns list of matching document IDs
    """
    from models import Document
    
    query_lower = f"%{query.lower()}%"
    
    results = Document.query.filter(
        Document.is_approved == True,
        (Document.title.ilike(query_lower)) |
        (Document.description.ilike(query_lower)) |
        (Document.extracted_text.ilike(query_lower))
    ).order_by(Document.downloads.desc()).limit(limit).all()
    
    return results
