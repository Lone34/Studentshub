import json
import html
import re
from bs4 import BeautifulSoup
import traceback
import logging
from typing import Union

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AnswerGenerator:
    def __init__(self):
        self.mathjax_delimiters = {'inline': ['`', '`'], 'display': ['``', '``']}
        self.logger = logging.getLogger(__name__)
        self.symbol_map = {"(therefore)": "\\therefore", "(sigma)": "\\sigma", "(infty)": "\\infty"}

    def is_mathematical_expression(self, text: str) -> bool:
        if not text or len(text.strip()) < 2: return False
        complex_patterns = [r'\\frac\{[^}]+\}\{[^}]+\}', r'[A-Za-z]_[A-Za-z0-9{].*=.*\\frac', r'[A-Za-z0-9]\^[A-Za-z0-9{].*=', r'[A-Za-z]_[A-Za-z]+\s*=\s*[+-]?\s*\\frac', r'\/[A-Za-z0-9]+']
        simple_patterns = [r'[A-Za-z]_[A-Za-z0-9{]', r'[A-Za-z0-9]\^[A-Za-z0-9{]', r'[A-Za-z]\s*=\s*[^a-z]*[0-9]', r'\\[a-zA-Z]+', r'\^[0-9]+']
        for pattern in complex_patterns:
            if re.search(pattern, text): return 'display'
        for pattern in simple_patterns:
            if re.search(pattern, text): return 'inline'
        return False

    def clean_math_expression(self, expr: str) -> str:
        if not expr or not expr.strip(): return ""
        expr = re.sub(r'^`+|`+$', '', expr).strip()
        expr = re.sub(r'_\(\s*([^)]+)\s*\)', r'_\1', expr)
        expr = re.sub(r'_([A-Za-z]{2,})', r'_\1', expr)
        expr = re.sub(r'\^([A-Za-z0-9]{2,})', r'^\1', expr)
        expr = re.sub(r'\^([+-]?\d+)', r'^\1', expr)
        expr = re.sub(r'\^([+-]?[A-Za-z]+)', r'^\1', expr)
        expr = re.sub(r'([A-Za-z]+)\s*/\s*([A-Za-z]+-[A-Za-z]+)', r'\\text{\1}/\\text{\2}', expr)
        expr = re.sub(r'([A-Za-z]+)-([A-Za-z]+)', r'\1 \\cdot \2', expr)
        expr = re.sub(r'(\d+\.\d+)\s*\\text\{([A-Za-z]+)\}/\\text\{([A-Za-z]+ \\cdot [A-Za-z]+)\}', r'\1 \; \\frac{\\text{\2}}{\\text{\3}}', expr)
        expr = expr.replace('*', r'\times').replace('×', r'\times')
        # Key Change: Added a rule to correctly format the Omega symbol for resistance.
        expr = re.sub(r'([0-9])(Omega)', r'\1 \\Omega', expr)
        expr = re.sub(r'([0-9.]+)\s*(KN-m|KN|kN-m|kN|N-m|N)', r'\1 \text{\2}', expr)
        expr = re.sub(r'-\s*frac', r'-frac', expr)
        expr = re.sub(r'([A-Za-z0-9])\^([A-Za-z0-9]+)', r'\1^\2', expr)
        expr = re.sub(r'\(([^)]+)\)\s*/\s*(\d+)', r'frac{\1}{\2}', expr)
        expr = re.sub(r'([A-Za-z0-9]+)/([A-Za-z0-9]+)', r'frac{\1}{\2}', expr)
        expr = re.sub(r'([A-Za-z]+[0-9]*)/([0-9]+)', r'frac{\1}{\2}', expr)
        expr = re.sub(r'=\s*-\s*', r' = -', expr)
        expr = re.sub(r'=\s*\+\s*', r' = +', expr)
        expr = re.sub(r'(\d+(?:\.\d+)?)\s*([A-Za-z]+-[A-Za-z]+)', r'\1 \text{\2}', expr)
        expr = re.sub(r'(\d+(?:\.\d+)?)\s*(KN-m|kN-m|N-m)', r'\1 \text{\2}', expr)
        if expr.count('(') > expr.count(')'): expr += ')' * (expr.count('(') - expr.count(')'))
        expr = expr.replace("Î»", "lambda").replace("\\\\", "\\")
        for text, latex in self.symbol_map.items(): expr = expr.replace(text, latex.replace('\\', ''))
        expr = re.sub(r'\s+', ' ', expr).strip()
        if not expr or expr == "{}": return ""
        return expr

    def _create_editor_content(self, block_type, block_content):
        editor_content = []
        if block_type in ['TEXT', 'EXPLANATION']:
            text_content = block_content.get('text', '') or str(block_content)
            if not text_content.strip() or text_content.strip() == "{}": return []
            editor_content = [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text_content}]}]
        elif block_type == 'EQUATION_RENDERER':
            latex = block_content.get('latex', '') or str(block_content)
            if not latex.strip() or latex.strip() == "{}": return []
            editor_content = [{'type': 'paragraph', 'content': [{'type': 'inlineMath', 'content': [{'text': latex}]}]}]
        elif block_type == 'LIST':
            list_type = block_content.get('listType', 'unordered').lower()
            items = block_content.get('items', []) or [str(block_content)]
            items = [item for item in items if item.strip() and item.strip() != "{}"]
            if not items: return []
            editor_content = [{'type': 'bulletList' if list_type == 'unordered' else 'orderedList',
                             'content': [{'type': 'listItem', 'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': item}]}]} for item in items]}]
        return editor_content

    def _create_blocks_from_nested(self, parsed_body):
        blocks = []
        try:
            if 'stepByStep' in parsed_body and 'steps' in parsed_body['stepByStep']:
                for step_idx, step in enumerate(parsed_body['stepByStep'].get('steps', [])):
                    for block in step.get('blocks', []):
                        block_type = block.get('type', 'UNKNOWN')
                        block_content = block.get('content', {})
                        if isinstance(block_content, str):
                            try: block_content = json.loads(block_content)
                            except json.JSONDecodeError:
                                if not block_content.strip() or block_content.strip() == "{}": continue
                        if not block_content: continue
                        editor_content = self._create_editor_content(block_type, block_content)
                        if not editor_content: continue
                        blocks.append({'type': block_type, 'content': block_content,
                                     'block': {'editorContentState': {'content': editor_content}} if editor_content else block_content,
                                     'label': 'Step-by-step explanation' if block_type == 'EXPLANATION' else None, 'raw': block})
            if 'finalAnswer' in parsed_body and 'blocks' in parsed_body['finalAnswer']:
                for block in parsed_body['finalAnswer'].get('blocks', []):
                    block_type = block.get('type', 'UNKNOWN')
                    block_content = block.get('content', {})
                    if isinstance(block_content, str):
                        try: block_content = json.loads(block_content)
                        except json.JSONDecodeError:
                            if not block_content.strip() or block_content.strip() == "{}": continue
                    if not block_content: continue
                    editor_content = self._create_editor_content(block_type, block_content)
                    if not editor_content: continue
                    blocks.append({'type': block_type, 'content': block_content,
                                 'block': {'editorContentState': {'content': editor_content}} if editor_content else block_content,
                                 'label': 'Final Answer' if block_type == 'EXPLANATION' else None, 'raw': block})
            return blocks if blocks else []
        except Exception as e:
            self.logger.error(f"Error processing nested content: {e}")
            return []

    def format_answer_content(self, answer_data):
        try:
            if isinstance(answer_data, str):
                if not answer_data.strip() or answer_data == "<p>Answer not found</p>":
                    return {'text': "", 'html': "", 'blocks': []}
                return {'text': answer_data, 'html': answer_data,
                       'blocks': [{'type': 'HTML', 'content': answer_data,
                                 'block': {'editorContentState': {'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': answer_data}]}]}}}]}
            
            question_data = answer_data.get('questionByUuid') or answer_data.get('questionByLegacyId') or answer_data
            if not question_data: return {'text': "", 'html': "", 'blocks': []}
            
            answer_data_structured = {'blocks': [], 'explanation_blocks': [], 'text': '', 'html': '',
                                    'stepByStep': {'steps': []}, 'finalAnswer': {'blocks': []}}
            display_answers = question_data.get('displayAnswers', {})
            answer_type = display_answers.get('__typename', '')
            
            if answer_type == 'HTMLAnswers':
                html_answers = display_answers.get('htmlAnswers', [])
                if html_answers:
                    answer_data_structured['html'] = html_answers[0].get('answerData', {}).get('html', "")
                    answer_data_structured['text'] = html_answers[0].get('answerData', {}).get('text', "")
                    if answer_data_structured['html'].strip():
                        answer_data_structured['blocks'].append({'type': 'HTML', 'content': answer_data_structured['html'],
                                                               'block': {'editorContentState': {'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': answer_data_structured['text']}]}]}}})
            elif answer_type == 'SqnaAnswers':
                sqna_answers = display_answers.get('sqnaAnswers', {}).get('answerData', [])
                if sqna_answers:
                    body_v2 = sqna_answers[0].get('bodyV2', {})
                    if isinstance(body_v2, dict) and ('blocks' in body_v2 or 'stepByStep' in body_v2):
                        for section in ['stepByStep', 'finalAnswer', 'blocks']:
                            if section == 'stepByStep' and section in body_v2:
                                answer_data_structured['stepByStep'] = body_v2['stepByStep']
                                for step_idx, step in enumerate(body_v2['stepByStep'].get('steps', [])):
                                    for block in step.get('blocks', []):
                                        self._process_block_to_structured(block, answer_data_structured, f'step {step_idx + 1}')
                            elif section == 'finalAnswer' and section in body_v2:
                                answer_data_structured['finalAnswer'] = body_v2['finalAnswer']
                                for block in body_v2['finalAnswer'].get('blocks', []):
                                    self._process_block_to_structured(block, answer_data_structured, 'finalAnswer')
                            elif section == 'blocks' and section in body_v2:
                                for block in body_v2.get('blocks', []):
                                    self._process_block_to_structured(block, answer_data_structured, 'top-level')
                    else:
                        answer_data_structured['text'] = body_v2.get('text', "")
                        if isinstance(answer_data_structured['text'], str) and answer_data_structured['text'].strip().startswith('{'):
                            try:
                                parsed_body = json.loads(answer_data_structured['text'])
                                if 'stepByStep' in parsed_body or 'finalAnswer' in parsed_body or 'blocks' in parsed_body:
                                    answer_data_structured['stepByStep'] = parsed_body.get('stepByStep', {'steps': []})
                                    answer_data_structured['finalAnswer'] = parsed_body.get('finalAnswer', {'blocks': []})
                                    answer_data_structured['blocks'] = self._create_blocks_from_nested(parsed_body)
                                else:
                                    if answer_data_structured['text'].strip():
                                        answer_data_structured['blocks'].append({'type': 'TEXT', 'content': answer_data_structured['text'],
                                                                               'block': {'editorContentState': {'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': answer_data_structured['text']}]}]}}})
                            except json.JSONDecodeError:
                                if answer_data_structured['text'].strip():
                                    answer_data_structured['blocks'].append({'type': 'TEXT', 'content': answer_data_structured['text'],
                                                                           'block': {'editorContentState': {'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': answer_data_structured['text']}]}]}}})
            elif answer_type == 'TextAnswer':
                answer_text = display_answers.get('bodyMdText', "")
                if answer_text.strip():
                    answer_data_structured['text'] = answer_text
                    answer_data_structured['blocks'].append({'type': 'TEXT', 'content': answer_text,
                                                           'block': {'editorContentState': {'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': answer_text}]}]}}})
            return answer_data_structured
        except Exception as e:
            self.logger.error(f"Error formatting answer content: {e}")
            return {'text': "", 'html': "", 'blocks': []}

    def _process_block_to_structured(self, block, answer_data_structured, context):
        block_type = block.get('type', 'UNKNOWN')
        block_content = block.get('content', {})
        if isinstance(block_content, str):
            try: block_content = json.loads(block_content)
            except json.JSONDecodeError:
                if not block_content.strip() or block_content.strip() == "{}": return
        if not block_content: return
        editor_content = self._create_editor_content(block_type, block_content)
        if not editor_content: return
        structured_block = {'type': block_type, 'content': block_content,
                          'block': {'editorContentState': {'content': editor_content}} if editor_content else block_content,
                          'label': 'Step-by-step explanation' if block_type == 'EXPLANATION' and 'step' in context else 'Final Answer' if block_type == 'EXPLANATION' else None,
                          'raw': block}
        answer_data_structured['blocks'].append(structured_block)
        if block_type == 'EXPLANATION': answer_data_structured['explanation_blocks'].append(structured_block)

    def process_block_enhanced(self, block: dict, mode='display') -> str:
        block_type = block.get("type", "UNKNOWN")
        try:
            if block_type in ["TEXT", "EXPLANATION"]:
                return self._process_text_block(block, block_type, mode=mode)
            elif block_type == "EQUATION_RENDERER": return self.process_equation_block(block, mode=mode)
            elif block_type == "ACCOUNTING_TABLE": return self.process_accounting_table(block, mode=mode)
            elif block_type == "TABLE": return self.process_generic_table(block, mode=mode)
            elif block_type == "DRAWING": return self.process_drawing_block(block)
            elif block_type == "CIRCUIT": print(block); return self.process_circuit_block(block)
            elif block_type == "LIST": return self._process_list_block(block, mode=mode)
            elif block_type == "HTML": return block.get("content", "") if block.get("content", "").strip() else ""
            elif block_type == "CODE_SNIPPET": return self.process_code_snippet(block)
            elif block_type == "IMAGE_UPLOAD": return self.process_image_upload(block)
            elif block_type == "MATH_IN_TEXT": return self.process_math_in_text_block(block, mode=mode)
            return ""
        except Exception as e:
            self.logger.error(f"Error processing block type {block_type}: {e}")
            return ""

    def process_circuit_block(self, block: dict) -> str:
        """
        Process a CIRCUIT block with comprehensive circuit element rendering
        """
        try:
            # Get the circuit data - it can be nested in different ways
            circuit_data = block.get("block", {})
            if not circuit_data:
                circuit_data = block.get("content", {})
            
            # Log the structure for debugging
            self.logger.info(f"Processing circuit block with keys: {circuit_data.keys()}")
            
            # Extract settings and shapes
            settings = circuit_data.get("settings", {})
            shapes = circuit_data.get("shapes", [])
            
            if not settings and not shapes:
                # Try alternative structure
                settings = circuit_data.get("settings", {})
                shapes = circuit_data.get("shapes", [])
            
            # If still no data, return empty
            if not settings and not shapes:
                self.logger.warning("No circuit settings or shapes found")
                return ""
                
            # Create a properly structured drawing block for processing
            drawing_block = {
                "block": {
                    "settings": settings,
                    "shapes": shapes,
                    "type": "CIRCUIT",
                    "version": circuit_data.get("version", "1.0.0")
                }
            }
            
            self.logger.info(f"Circuit has {len(shapes)} shapes")
            
            # Process using the enhanced drawing logic
            return self.process_drawing_block(drawing_block)
            
        except Exception as e:
            self.logger.error(f"Error processing CIRCUIT block: {e}")
            traceback.print_exc()
            return ""

    def process_math_in_text_block(self, block: dict, mode='display') -> str:
        try:
            block_data = block.get("block", {})
            title = block_data.get("title", {}).get("content", [{}])[0].get("content", [{}])[0].get("text", "")
            expression = block_data.get("expression", {}).get("content", [])
            result = block_data.get("result", {}).get("content", [{}])[0].get("content", [{}])[0].get("text", "")
            html_content = ""
            if title:
                html_content += f'<p>{html.escape(title)}</p>'
            for expr in expression:
                expr_text = expr.get("content", [{}])[0].get("text", "")
                if expr_text.strip() and expr_text.strip() != "{}":
                    math_type = self.is_mathematical_expression(expr_text)
                    cleaned_expr = self.clean_math_expression(expr_text)
                    if cleaned_expr:
                        if mode == 'display':
                            html_content += f'<span class="equation-line">`{cleaned_expr}`</span>'
                        else:
                            html_content += f'<span data-math-type="mhchem">{cleaned_expr}</span>'
            if result.strip() and result.strip() != "{}":
                math_type = self.is_mathematical_expression(result)
                cleaned_result = self.clean_math_expression(result)
                if cleaned_result:
                    if mode == 'display':
                        html_content += f'<span class="equation-line">`{cleaned_result}`</span>'
                    else:
                        html_content += f'<span data-math-type="mhchem">{cleaned_result}</span>'
            return html_content
        except Exception as e:
            self.logger.error(f"Error processing MATH_IN_TEXT block: {e}")
            return ""

    def _process_text_block(self, block, block_type, mode='display'):
        editor_content = block.get("block", {}).get("editorContentState", {}).get("content", [])
        if not editor_content:
            text_content = block.get("content", {}).get("text", "") or str(block.get("content", ""))
            if not text_content.strip() or text_content.strip() == "{}": return ""
            editor_content = [{'type': 'paragraph', 'content': [{'type': 'text', 'text': text_content}]}]
        has_content = any(item.get("type") == "paragraph" and item.get("content") and any(
            c.get("type") == "text" and c.get("text", "").strip() and c.get("text", "").strip() != "{}"
            for c in item.get("content", [])) or item.get("type") in ["bulletList", "orderedList"] and item.get("content")
            for item in editor_content)
        if not has_content: return ""
        html_content = ""
        if block_type == "EXPLANATION":
            label = block.get("label", "Explanation")
            html_content += f'<div class="explanation-block"><h2>{html.escape(label)}</h2>'
        for item in editor_content:
            processed_item = self.process_content_item(item, mode=mode)
            if processed_item.strip(): html_content += processed_item
        if block_type == "EXPLANATION" and html_content.strip(): html_content += '</div>'
        return html_content if html_content.strip() else ""

    def _process_list_block(self, block, mode='display'):
        editor_content = block.get("block", {}).get("editorContentState", {}).get("content", [])
        html_content = ""
        for item in editor_content:
            processed_item = self.process_content_item(item, mode=mode)
            if processed_item.strip(): html_content += processed_item
        return html_content

    def process_code_snippet(self, block: dict) -> str:
        try:
            content = block.get("block", {}).get("content", {}).get("content", [])
            if not content: return ""
            code_text = content[0].get("content", [{}])[0].get("text", "")
            if not code_text.strip() or code_text.strip() == "{}": return ""
            escaped_code = code_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            return f'<pre><code>{escaped_code}</code></pre>'
        except: return ""

    def process_image_upload(self, block: dict) -> str:
        try:
            image_path = block.get("block", {}).get("imagePath", "") or block.get("content", {}).get("imagePath", "")
            if not image_path.strip(): return ""
            alt_text = block.get("block", {}).get("altText", "Image") or block.get("content", {}).get("altText", "Image")
            return f'<a href="{html.escape(image_path)}" data-fancybox="gallery"><img src="{html.escape(image_path)}" alt="{html.escape(alt_text)}" style="max-width: 100%; height: auto; border-radius: 12px;"></a>'
        except: return ""

    def process_equation_block(self, block: dict, mode='display') -> str:
        try:
            block_data = block.get("block", {})
            equation_html = ""
            for eqn in block_data.get("lines", []):
                equation_str = f"{eqn.get('left', '')} {eqn.get('operator', '')} {eqn.get('right', '')}"
                cleaned_equation = self.clean_math_expression(equation_str)
                if not cleaned_equation: continue
                if mode == 'display':
                    equation_html += f'<span class="equation-line">`{cleaned_equation}`</span>'
                else:
                    equation_html += f'<p><span data-math-type="mhchem">{cleaned_equation}</span></p>'
            return equation_html if equation_html.strip() else ""
        except: return ""

    def determine_cell_alignment(self, cell_value, mode='display'):
        """Enhanced cell alignment determination with better logic"""
        try:
            content = ""
            
            if isinstance(cell_value, dict) and 'type' in cell_value and cell_value['type'] == 'doc':
                content_items = cell_value.get('content', [{}])
                for item in content_items:
                    if item.get('type') == 'paragraph':
                        para_content = item.get('content', [{}])
                        for para_item in para_content:
                            if para_item.get('type') == 'text':
                                text = para_item.get('text', '').strip()
                                if text and text != "{}":
                                    content = text
                                    break
                    if content:
                        break
            elif isinstance(cell_value, str):
                content = cell_value.strip()
            
            if not content or content == "{}":
                return "", "left"
            
            math_type = self.is_mathematical_expression(content)
            if math_type:
                cleaned_math = self.clean_math_expression(content)
                if cleaned_math:
                    if mode == 'display':
                        return f'<span class="equation-line">`{cleaned_math}`</span>', "center"
                    else:
                        return f'<span data-math-type="mhchem">{cleaned_math}</span>', "center"
            
            if re.match(r'^[\$\¢\£\¥\€]?[-]?\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?$', content):
                return html.escape(content), "right"
            if re.match(r'^\d+(?:\.\d+)?%$', content):
                return html.escape(content), "right"
            if re.match(r'^[-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?$', content):
                return html.escape(content), "right"
            if re.match(r'^\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}$', content):
                return html.escape(content), "center"
            
            header_keywords = ['date', 'account', 'name', 'debit', 'credit', 'transaction', 'amount', 
                             'description', 'category', 'effect', 'liabilities', 'assets', 'equity']
            if any(keyword in content.lower() for keyword in header_keywords):
                return html.escape(content), "center"
                
            return html.escape(content), "left"
            
        except Exception as e:
            self.logger.error(f"Error determining cell alignment for {cell_value}: {e}")
            return html.escape(str(cell_value)), "left"

    def _extract_cell_data(self, cell_value_obj: dict) -> (str, str):
        """
        Recursively extracts text content and alignment from a cell's value object.
        """
        try:
            if not isinstance(cell_value_obj, dict):
                return "", "left"

            text_parts = []
            alignment = "left"

            def recurse_content(content_list):
                nonlocal alignment
                for item in content_list:
                    if item.get("type") == "text" and "text" in item:
                        text_parts.append(item["text"])
                    
                    if item.get("type") == "paragraph":
                        align_attr = item.get("attrs", {}).get("textAlign")
                        if align_attr in ["center", "right"]:
                            alignment = align_attr

                    if "content" in item:
                        recurse_content(item["content"])

            if "content" in cell_value_obj:
                recurse_content(cell_value_obj["content"])
            
            return "".join(text_parts), alignment
        except Exception:
            return "", "left"

    def process_accounting_table(self, block: dict, mode='display') -> str:
        try:
            block_data = block.get("block", {}) or block.get("content", {})
            entries = block_data.get("entries", [])
            
            if not entries:
                return ""
            
            table_html = '<div class="table-container"><table class="data-table accounting-table">'
            has_content = False

            for entry_idx, entry in enumerate(entries):
                headers = entry.get("headerCells", {})
                body_cells = entry.get("bodyCells", {})
                
                all_keys = set()
                if headers:
                    all_keys.update(headers.keys())
                if body_cells:
                    all_keys.update(body_cells.keys())
                
                if not all_keys:
                    continue
                
                positions = []
                for key in all_keys:
                    try:
                        row, col = map(int, key.split('-'))
                        positions.append((row, col))
                    except:
                        continue
                
                if not positions:
                    continue
                
                max_row = max(pos[0] for pos in positions)
                max_col = max(pos[1] for pos in positions)
                
                if headers:
                    header_keys = [k for k in headers.keys() if k.startswith('0-')]
                    if header_keys:
                        table_html += "<thead><tr>"
                        header_keys.sort(key=lambda x: int(x.split('-')[1]))
                        for key in header_keys:
                            cell = headers[key]
                            cell_content, align = self.determine_cell_alignment(cell.get("value", ""), mode=mode)
                            if cell_content: 
                                has_content = True
                            
                            colspan = cell.get("style", {}).get("span", {}).get("colSpan", 1)
                            rowspan = cell.get("style", {}).get("span", {}).get("rowSpan", 1)
                            colspan_attr = f' colspan="{colspan}"' if colspan > 1 else ""
                            rowspan_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ""
                            
                            table_html += f'<th{colspan_attr}{rowspan_attr} class="table-header" style="text-align: {align}; font-weight: bold; background-color: #f8f9fa;">{cell_content}</th>'
                        table_html += "</tr></thead>"
                
                if body_cells:
                    rows_data = {}
                    for key, cell in body_cells.items():
                        try:
                            row, col = map(int, key.split('-'))
                            if row not in rows_data:
                                rows_data[row] = {}
                            rows_data[row][col] = cell
                        except:
                            continue
                    
                    if rows_data:
                        table_html += "<tbody>"
                        for row_idx in sorted(rows_data.keys()):
                            table_html += f'<tr class="table-row row-{row_idx}">'
                            row_data = rows_data[row_idx]
                            for col_idx in range(max_col + 1):
                                if col_idx in row_data:
                                    cell = row_data[col_idx]
                                    cell_content, align = self.determine_cell_alignment(cell.get("value", ""), mode=mode)
                                    if cell_content: 
                                        has_content = True
                                    
                                    colspan = cell.get("style", {}).get("span", {}).get("colSpan", 1)
                                    rowspan = cell.get("style", {}).get("span", {}).get("rowSpan", 1)
                                    colspan_attr = f' colspan="{colspan}"' if colspan > 1 else ""
                                    rowspan_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ""
                                    
                                    cell_class = "table-cell"
                                    if align == "right":
                                        cell_class += " numeric-cell"
                                    elif align == "center":
                                        cell_class += " centered-cell"
                                    
                                    table_html += f'<td{colspan_attr}{rowspan_attr} class="{cell_class}" style="text-align: {align}; padding: 8px; border: 1px solid #dee2e6;">{cell_content}</td>'
                                else:
                                    table_html += '<td class="table-cell empty-cell" style="padding: 8px; border: 1px solid #dee2e6;"></td>'
                            table_html += "</tr>"
                        table_html += "</tbody>"

            table_html += "</table></div>"
            
            if not has_content:
                self.logger.debug("Accounting table has no valid content, returning empty string")
                return ""
            
            self.logger.info("Successfully processed accounting table")
            return table_html
            
        except Exception as e:
            self.logger.error(f"Error processing accounting table: {e}")
            traceback.print_exc()
            return ""

    def process_generic_table(self, block: dict, mode='display') -> str:
        """
        Processes a generic table block with a flat 'cells' structure into an HTML table.
        This version correctly handles nested cell content and spans.
        """
        try:
            block_data = block.get("block", {})
            if not block_data:
                return ""

            cells = block_data.get("cells", {})
            row_count = block_data.get("rows", 0)
            col_count = block_data.get("columns", 0)
            row_spans = block_data.get("rowSpans", {})
            col_spans = block_data.get("columnSpans", {})
            
            corrected_cells = {}
            for key, cell_data in cells.items():
                try:
                    r, c = map(int, key.split('-'))
                    new_key = f"{c}-{r}"
                    corrected_cells[new_key] = cell_data
                except ValueError:
                    corrected_cells[key] = cell_data
            
            cells = corrected_cells
            original_row_count = row_count
            row_count = col_count
            col_count = original_row_count
            
            if not cells:
                return ""

            max_row, max_col = 0, 0
            for key in cells.keys():
                try:
                    r, c = map(int, key.split('-'))
                    if r > max_row: max_row = r
                    if c > max_col: max_col = c
                except (ValueError, IndexError):
                    continue

            row_count = max_row + 1
            col_count = max_col + 1

            if not cells or row_count == 0 or col_count == 0:
                return ""

            shadow_grid = [[False for _ in range(col_count)] for _ in range(row_count)]
            html = '<div class="table-container"><table class="data-table generic-table">'
            has_content = False

            for r in range(row_count):
                if r == 0:
                    html += "<thead>"
                elif r == 1:
                    html += "<tbody>"
                
                html += f'<tr class="table-row row-{r}">'
                
                for c in range(col_count):
                    if shadow_grid[r][c]:
                        continue

                    key = f"{r}-{c}"
                    cell = cells.get(key)
                    
                    if cell:
                        cell_content, align = self._extract_cell_data(cell.get("value", {}))
                        if cell_content.strip():
                            has_content = True

                        rowspan = row_spans.get(key, 1)
                        colspan = col_spans.get(key, 1)

                        for i in range(rowspan):
                            for j in range(colspan):
                                if r + i < row_count and c + j < col_count:
                                    shadow_grid[r + i][c + j] = True
                        
                        tag = "th" if r == 0 else "td"
                        style = f'text-align: {align}; padding: 8px; border: 1px solid #dee2e6;'
                        rowspan_attr = f' rowspan="{rowspan}"' if rowspan > 1 else ""
                        colspan_attr = f' colspan="{colspan}"' if colspan > 1 else ""
                        
                        html += f'<{tag}{rowspan_attr}{colspan_attr} style="{style}">{cell_content}</{tag}>'
                    else:
                        html += '<td></td>'

                html += "</tr>"

                if r == 0:
                    html += "</thead>"

            if row_count > 1:
                html += "</tbody>"
                
            html += "</table></div>"

            return html if has_content else ""

        except Exception as e:
            print(f"Error processing generic table: {e}")
            traceback.print_exc()
            return ""

    def process_content_item(self, content_item: dict, mode='display') -> str:
        try:
            item_type = content_item.get("type", "")
            if item_type == "paragraph": return self.process_paragraph(content_item, mode=mode)
            elif item_type == "bulletList": return self.process_bullet_list(content_item, mode=mode)
            elif item_type == "orderedList": return self.process_ordered_list(content_item, mode=mode)
            elif item_type == "heading": return self.process_heading(content_item, mode=mode)
            return ""
        except: return ""

    def process_paragraph(self, content_item: dict, mode='display') -> str:
        try:
            content = content_item.get("content", [])
            if not content: return ""
            paragraph_html = "<p>"
            has_valid_content = False
            for item in content:
                if item.get("type") == "text":
                    raw_text = item.get("text", "")
                    if not raw_text.strip() or raw_text.strip() == "{}": continue
                    math_type = self.is_mathematical_expression(raw_text)
                    if math_type:
                        cleaned_text = self.clean_math_expression(raw_text)
                        if not cleaned_text: continue
                        if mode == 'display':
                            delim = '`'
                            span_start = '<span class="equation-line">' if math_type == 'display' else ''
                            span_end = '</span>' if math_type == 'display' else ''
                        else:
                            delim = ''
                            span_start = '<span data-math-type="mhchem">'
                            span_end = '</span>'
                        text = span_start + delim + cleaned_text + delim + span_end
                    else: text = html.escape(raw_text)
                    marks = item.get("marks", [])
                    for mark in marks:
                        if mark.get("type") == "bold": text = f"<strong>{text}</strong>"
                        elif mark.get("type") == "italic": text = f"<i>{text}</i>"
                        elif mark.get("type") == "code": text = f"<code>{text}</code>"
                    paragraph_html += text
                    has_valid_content = True
                elif item.get("type") == "inlineMath":
                    math_text = item.get("content", [{}])[0].get("text", "")
                    math_text = self.clean_math_expression(math_text)
                    if not math_text: continue
                    math_type = self.is_mathematical_expression(math_text)
                    if mode == 'display':
                        delim = '`'
                        span_start = '<span class="equation-line">' if math_type == 'display' else ''
                        span_end = '</span>' if math_type == 'display' else ''
                    else:
                        delim = ''
                        span_start = '<span data-math-type="mhchem">'
                        span_end = '</span>'
                    text = span_start + delim + math_text + delim + span_end
                    paragraph_html += text
                    has_valid_content = True
                elif item.get("type") == "hardBreak":
                    paragraph_html += "<br>"
                    has_valid_content = True
            paragraph_html += "</p>"
            return paragraph_html if has_valid_content else ""
        except: return ""

    def process_bullet_list(self, content_item: dict, mode='display', indent_level: int = 0) -> str:
        try:
            content = content_item.get("content", [])
            if not content: return ""
            list_html = f'<ul class="{f"nested-list-{indent_level}" if indent_level > 0 else "" }">'
            has_valid_content = False
            for list_item in content:
                if list_item.get("type") == "listItem":
                    item_html = "<li>"
                    item_has_content = False
                    for item in list_item.get("content", []):
                        processed_item = self.process_content_item(item, mode=mode)
                        if processed_item.strip():
                            item_html += processed_item
                            item_has_content = True
                    item_html += "</li>"
                    if item_has_content:
                        list_html += item_html
                        has_valid_content = True
            list_html += "</ul>"
            return list_html if has_valid_content else ""
        except: return ""

    def process_ordered_list(self, content_item: dict, mode='display', indent_level: int = 0) -> str:
        try:
            content = content_item.get("content", [])
            if not content: return ""
            start = content_item.get("attrs", {}).get("start", 1)
            list_html = f'<ul class="{f"nested-list-{indent_level}" if indent_level > 0 else "" }">'
            has_valid_content = False
            for list_item in content:
                if list_item.get("type") == "listItem":
                    item_html = "<li>"
                    item_has_content = False
                    for item in list_item.get("content", []):
                        processed_item = self.process_content_item(item, mode=mode)
                        if processed_item.strip():
                            item_html += processed_item
                            item_has_content = True
                    item_html += "</li>"
                    if item_has_content:
                        list_html += item_html
                        has_valid_content = True
            list_html += "</ol>"
            return list_html if has_valid_content else ""
        except: return ""

    def process_heading(self, content_item: dict, mode='display') -> str:
        try:
            level = content_item.get("attrs", {}).get("level", 3)
            content = content_item.get("content", [])
            heading_text = ""
            for item in content:
                if item.get("type") == "text":
                    text = item.get("text", "")
                    if not text.strip() or text.strip() == "{}": continue
                    math_type = self.is_mathematical_expression(text)
                    if math_type:
                        cleaned_text = self.clean_math_expression(text)
                        if not cleaned_text: continue
                        if mode == 'display':
                            delim = '`'
                            span_start = '<span class="equation-line">' if math_type == 'display' else ''
                            span_end = '</span>' if math_type == 'display' else ''
                        else:
                            delim = ''
                            span_start = '<span data-math-type="mhchem">'
                            span_end = '</span>'
                        text = span_start + delim + cleaned_text + delim + span_end
                    else: text = html.escape(text)
                    for mark in item.get("marks", []):
                        if mark.get("type") == "bold": text = f"<strong>{text}</strong>"
                    heading_text += text
            return f"<h{level}>{heading_text}</h{level}>" if heading_text else ""
        except: return ""

    def convert_html_to_markdown(self, html_content: str) -> str:
        try:
            if not html_content or html_content == "<p>Answer not found</p>": return ""
            soup = BeautifulSoup(html_content, 'html.parser')
            markdown_lines = []
            def process_element(element, indent=0):
                if isinstance(element, str):
                    text = element.strip()
                    if text and text != "{}": markdown_lines.append("  " * indent + text)
                elif element.name:
                    if element.name == 'p':
                        text = element.get_text(strip=True)
                        if text and text != "{}": markdown_lines.append("  " * indent + text + "\n")
                    elif element.name in ['strong', 'b']:
                        text = element.get_text(strip=True)
                        if text and text != "{}": markdown_lines.append("  " * indent + f"**{text}**")
                    elif element.name in ['i', 'em']:
                        text = element.get_text(strip=True)
                        if text and text != "{}": markdown_lines.append("  " * indent + f"*{text}*")
                    elif element.name == 'code' and element.parent.name == 'pre':
                        text = element.get_text(strip=True)
                        if text and text != "{}": markdown_lines.append("  " * indent + f"```text\n{text}\n```")
                    elif element.name == 'span' and 'equation-line' in element.get('class', []):
                        text = element.get_text(strip=True)
                        if text and text != "{}": markdown_lines.append("  " * indent + f"`{text}`\n")
                    elif element.name == 'table':
                        rows = element.find_all('tr')
                        if rows:
                            headers = rows[0].find_all(['th', 'td'])
                            header_row = "| " + " | ".join(h.get_text(strip=True) for h in headers if h.get_text(strip=True) and h.get_text(strip=True) != "{}") + " |"
                            markdown_lines.append("  " * indent + header_row)
                            markdown_lines.append("  " * indent + "| " + " | ".join(['---'] * len(headers)) + " |")
                            for row in rows[1:]:
                                cells = row.find_all('td')
                                row_text = "| " + " | ".join(c.get_text(strip=True) for c in cells if c.get_text(strip=True) and c.get_text(strip=True) != "{}") + " |"
                                if row_text != "|  |": markdown_lines.append("  " * indent + row_text)
                    elif element.name in ['h1', 'h2', 'h3']:
                        level = {'h1': '#', 'h2': '##', 'h3': '###'}.get(element.name, '###')
                        text = element.get_text(strip=True)
                        if text and text != "{}": markdown_lines.append("  " * indent + f"{level} {text}\n")
                    else:
                        for child in element.children: process_element(child, indent)
            for element in soup: process_element(element, 0)
            return "\n".join(line.rstrip() for line in markdown_lines if line.strip() and line.strip() != "{}")
        except: return ""

    def process_sqna_content_for_html(self, content_obj: dict, mode='display') -> str:
        try:
            html_content = ""
            if "stepByStep" in content_obj and "steps" in content_obj["stepByStep"]:
                for i, step in enumerate(content_obj["stepByStep"]["steps"]):
                    step_title = step.get("title", "").strip()
                    step_blocks = step.get("blocks", [])
                    if not step_blocks: continue
                    step_html = ""
                    for block in step_blocks:
                        processed_block = self.process_block_enhanced(block, mode=mode)
                        if processed_block.strip(): step_html += processed_block
                    if step_html:
                        step_header = f'<div class="step-header">Step {i + 1} of {len(content_obj["stepByStep"]["steps"])}'
                        if step_title: step_header += f': {html.escape(step_title)}'
                        step_header += '</div>'
                        html_content += step_header + step_html
            if "finalAnswer" in content_obj and "blocks" in content_obj["finalAnswer"]:
                final_answer_html = ""
                for block in content_obj["finalAnswer"].get("blocks", []):
                    processed_block = self.process_block_enhanced(block, mode=mode)
                    if processed_block.strip(): final_answer_html += processed_block
                if final_answer_html.strip(): html_content += '<div class="final-answer"><h3>Final Answer</h3>' + final_answer_html + "</div>"
            if "blocks" in content_obj:
                for block in content_obj["blocks"]:
                    processed_block = self.process_block_enhanced(block, mode=mode)
                    if processed_block.strip(): html_content += processed_block
            return html_content or ""
        except: return ""

    # ==============================================================================
    # START OF UPDATED CODE BLOCK
    # ==============================================================================

    def process_drawing_block(self, block: dict) -> str:
        """
        Converts a JSON block representing a drawing or circuit into an SVG string.
        This corrected version properly handles component orientation and text alignment.
        """
        try:
            settings = block.get("block", {}).get("settings", {}) or block.get("content", {})
            viewBox = settings.get('viewBox', {})
            shapes = block.get("block", {}).get("shapes", []) or block.get("content", {}).get("shapes", [])
            
            if not viewBox or not shapes: 
                self.logger.warning("No viewBox or shapes found in drawing/circuit")
                return ""
                
            shape_types = [shape.get('type', 'unknown') for shape in shapes]
            self.logger.info(f"Processing {len(shapes)} shapes: {set(shape_types)}")
            
            viewBox_str = f"{viewBox.get('x', 0)} {viewBox.get('y', 0)} {viewBox.get('w', 100)} {viewBox.get('h', 100)}"
            svg_html = f'<svg width="100%" height="auto" viewBox="{viewBox_str}" xmlns="http://www.w3.org/2000/svg" xmlns:xhtml="http://www.w3.org/1999/xhtml">'
            
            svg_html += '''<defs>
                <marker id="arrow-end" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
                    <polygon points="0 0, 10 3.5, 0 7" fill="black"/>
                </marker>
                <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="5" refY="3.5" orient="auto" markerUnits="strokeWidth">
                    <path d="M0,0 L0,7 L10,3.5 z" fill="#000"/>
                </marker>
            </defs>'''

            def get_style(style):
                base_style = {'fill': 'transparent', 'stroke': 'black', 'stroke-width': 2}
                if not style: return ';'.join(f"{k}:{v}" for k, v in base_style.items())
                
                final_style = base_style.copy()
                # Apply custom styles from the shape data
                for k, v in style.items():
                    if k == 'stroke': final_style['stroke'] = v
                    elif k == 'strokeWidth': final_style['stroke-width'] = v
                    elif k == 'strokeDasharray': final_style['stroke-dasharray'] = v
                    elif k == 'fill': final_style['fill'] = v
                
                return ';'.join(f"{k}:{v}" for k,v in final_style.items())

            def processShape(shape, parent_x=0, parent_y=0):
                nonlocal svg_html
                if not shape: return
                
                shape_type = shape.get('type', 'unknown')
                style_props = shape.get('style', {})
                # Force transparent fill for specific components to avoid solid black shapes
                if shape_type == 'PythagorasSVG':
                    style_props['fill'] = 'transparent'
                style = get_style(style_props)
                
                # Calculate absolute position including parent offset
                x = shape.get('x', 0) + parent_x
                y = shape.get('y', 0) + parent_y
                w = shape.get('w', 0)
                h = shape.get('h', 0)

                # Consolidate transformations
                transform = shape.get('transform', '') or ''
                if shape.get('rotation'):
                    rotation = shape['rotation']
                    x_center = x + w / 2
                    y_center = y + h / 2
                    transform += f" rotate({rotation} {x_center} {y_center})"
                transform = transform.strip()

                if shape_type == "Line":
                    points = shape.get('points', [{}, {}])
                    if len(points) >= 2:
                        x1 = points[0].get("x", 0) + x
                        y1 = points[0].get("y", 0) + y
                        x2 = points[1].get("x", 0) + x
                        y2 = points[1].get("y", 0) + y
                        marker = ' marker-end="url(#arrowhead)"' if shape.get('style', {}).get('markerEnd') else ''
                        svg_html += f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" style="{style}"{marker} transform="{transform}"/>'
                        
                elif shape_type == "Connection":
                    points = shape.get('points', [])
                    if points:
                        points_str = [f"{p.get('x', 0) + x},{p.get('y', 0) + y}" for p in points]
                        if points_str:
                            marker = ' marker-end="url(#arrowhead)"' if shape.get('style', {}).get('markerEnd') else ''
                            svg_html += f'<polyline points="{" ".join(points_str)}" style="{style}"{marker} transform="{transform}"/>'
                
                elif shape_type in ["Square", "Rect"]:
                    svg_html += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" style="{style}" transform="{transform}"/>'
                    
                elif shape_type == "Circle":
                    cx = x + w / 2
                    cy = y + h / 2
                    r = min(w, h) / 2
                    svg_html += f'<circle cx="{cx}" cy="{cy}" r="{r}" style="{style}" transform="{transform}"/>'
                    
                elif shape_type == "Ellipse":
                    cx = x + w / 2
                    cy = y + h / 2
                    rx, ry = w / 2, h / 2
                    svg_html += f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" style="{style}" transform="{transform}"/>'
                    
                elif shape_type == "Path":
                    d = shape.get("d", "")
                    if d: 
                        path_transform = f"translate({x} {y}) {transform}"
                        svg_html += f'<path d="{html.escape(d)}" style="{style}" transform="{path_transform.strip()}"/>'
                        
                elif shape_type in ["Polygon", "Polyline"]:
                    points = shape.get("points", [])
                    if points:
                        points_str = " ".join(f"{p.get('x', 0) + x},{p.get('y', 0) + y}" for p in points)
                        marker = ' marker-end="url(#arrowhead)"' if shape.get('style', {}).get('markerEnd') and shape_type == "Polyline" else ''
                        svg_html += f'<{shape_type.lower()} points="{points_str}" style="{style}"{marker} transform="{transform}"/>'
                        
                elif shape_type == "Text":
                    text_value = ""
                    if 'value' in shape and shape['value']:
                        text_value = shape['value'][0].get("text", "") if isinstance(shape['value'], list) else str(shape['value'])
                    
                    if text_value.strip() and text_value.strip() != "{}":
                        font_size = shape.get('style', {}).get("fontSize", "14px")
                        text_anchor = shape.get('style', {}).get("textAnchor", "start")
                        # Vertically align text within its bounding box
                        svg_html += f'<text x="{x}" y="{y + h/2}" font-size="{font_size}" text-anchor="{text_anchor}" dominant-baseline="central" style="fill:black;stroke:none;" transform="{transform}">{html.escape(text_value)}</text>'
                        
                elif shape_type == "Math":
                    math_text = ""
                    if 'value' in shape and shape['value']:
                        math_text = shape['value'][0].get("text", "") if isinstance(shape['value'], list) else str(shape['value'])
                    
                    if math_text.strip() and math_text.strip() != "{}":
                        cleaned_math = self.clean_math_expression(math_text)
                        if cleaned_math:
                            font_size = shape.get('style', {}).get("fontSize", "14px")
                            # Use shape's dimensions for foreignObject, providing a fallback
                            math_w = w if w > 0 else max(50, len(cleaned_math) * 9)
                            math_h = h if h > 0 else 30
                            # The y-coordinate is already correct, no adjustment needed
                            svg_html += f'<foreignObject x="{x}" y="{y}" width="{math_w}" height="{math_h}" transform="{transform}"><xhtml:div style="height:100%;display:flex;align-items:center;justify-content:center;font-size:{font_size};"><span class="equation-line">`{html.escape(cleaned_math)}`</span></xhtml:div></foreignObject>'
                            
                elif shape_type == "PythagorasSVG":
                    svg_shape_name = shape.get("SVGShapeName", "")
                    
                    if svg_shape_name == "Resistor":
                        if w >= h: # Horizontal orientation
                            mid_y = y + h/2
                            lead = w/5
                            path = f"M {x},{mid_y} l {lead},0 "
                            segment_w = (w - 2*lead) / 6
                            for i in range(6):
                                path += f"l {segment_w},{h/2 if i%2==0 else -h/2} "
                            path += f"l {lead},0"
                        else: # Vertical orientation
                            mid_x = x + w/2
                            lead = h/5
                            path = f"M {mid_x},{y} l 0,{lead} "
                            segment_h = (h - 2*lead) / 6
                            for i in range(6):
                                path += f"l {w/2 if i%2==0 else -w/2},{segment_h} "
                            path += f"l 0,{lead}"
                        svg_html += f'<path d="{path}" style="{style}" transform="{transform}"/>'

                    elif svg_shape_name == "Inductor":
                        if w >= h: # Horizontal
                            mid_y = y + h/2; num_coils = 4; coil_w = w / num_coils
                            path = f"M {x},{mid_y}"
                            for _ in range(num_coils): path += f" c {coil_w*0.25},-{h} {coil_w*0.75},-{h} {coil_w},0"
                        else: # Vertical
                            mid_x = x + w/2; num_coils = 4; coil_h = h / num_coils
                            path = f"M {mid_x},{y}"
                            for _ in range(num_coils): path += f" c {w}, {coil_h*0.25} {w}, {coil_h*0.75} 0,{coil_h}"
                        svg_html += f'<path d="{path}" style="{style}" transform="{transform}"/>'
                        
                    elif svg_shape_name in ["Capacitor", "Polarized Capacitor"]:
                        if w > h: # Horizontal
                            plate_gap = 4; mid_y = y + h/2; line_len = (w - plate_gap) / 2
                            svg_html += f'<path d="M {x},{mid_y} L {x+line_len},{mid_y} M {x+line_len},{y} L {x+line_len},{y+h} M {x+w-line_len},{y} L {x+w-line_len},{y+h} M {x+w-line_len},{mid_y} L {x+w},{mid_y}" style="{style}" transform="{transform}"/>'
                            if svg_shape_name == "Polarized Capacitor": svg_html += f'<text x="{x + line_len - 12}" y="{y}" font-size="16" style="fill:black; stroke:none;" transform="{transform}">+</text>'
                        else: # Vertical
                            plate_gap = 4; mid_x = x + w/2; line_len = (h - plate_gap) / 2
                            svg_html += f'<path d="M {mid_x},{y} L {mid_x},{y+line_len} M {x},{y+line_len} L {x+w},{y+line_len} M {x},{y+h-line_len} L {x+w},{y+h-line_len} M {mid_x},{y+h-line_len} L {mid_x},{y+h}" style="{style}" transform="{transform}"/>'
                            if svg_shape_name == "Polarized Capacitor": svg_html += f'<text x="{x+w+2}" y="{y+line_len+5}" font-size="16" style="fill:black; stroke:none;" transform="{transform}">+</text>'
                             
                    elif svg_shape_name == "DC Voltage Source":
                        cx, cy = x + w/2, y + h/2
                        if w > h: # Horizontal
                            plate_gap = w/5; short_plate_h = h*0.5; plate_x1 = cx-plate_gap/2; plate_x2 = cx+plate_gap/2
                            svg_html += f'<path d="M {x},{cy} L {plate_x1},{cy} M {plate_x1},{y} L {plate_x1},{y+h} M {plate_x2},{y+(h-short_plate_h)/2} L {plate_x2},{y+(h+short_plate_h)/2} M {plate_x2},{cy} L {x+w},{cy}" style="{style}" transform="{transform}"/>'
                            svg_html += f'<text x="{plate_x1}" y="{y-2}" font-size="{h/2}" text-anchor="middle" style="fill:black; stroke:none;" transform="{transform}">+</text>'
                        else: # Vertical
                            plate_gap = h/5; short_plate_w = w*0.5; plate_y1 = cy-plate_gap/2; plate_y2 = cy+plate_gap/2
                            svg_html += f'<path d="M {cx},{y} L {cx},{plate_y1} M {x},{plate_y1} L {x+w},{plate_y1} M {x+(w-short_plate_w)/2},{plate_y2} L {x+(w+short_plate_w)/2},{plate_y2} M {cx},{plate_y2} L {cx},{y+h}" style="{style}" transform="{transform}"/>'
                            svg_html += f'<text x="{x+w+2}" y="{plate_y1+4}" font-size="{w*0.75}" style="fill:black; stroke:none;" transform="{transform}">+</text>'
                        
                    elif svg_shape_name == "Semicircle":
                        # Arcs are tricky with transforms, better to draw as path
                        if w >= h:
                            d = f"M{x},{y+h/2} A{w/2},{h/2} 0 0,1 {x+w},{y+h/2}"
                        else:
                            d = f"M{x+w/2},{y} A{w/2},{h/2} 0 0,1 {x+w/2},{y+h}"
                        svg_html += f'<path d="{d}" style="{style}" transform="{transform}"/>'
                        
                    else: # Fallback for unknown shapes
                        svg_html += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" style="{style}" transform="{transform}"/>'
                        svg_html += f'<text x="{x + w/2}" y="{y + h/2}" font-size="10" text-anchor="middle" dominant-baseline="central" style="fill:blue;stroke:none;" transform="{transform}">{svg_shape_name}</text>'
                        
                elif shape_type == "IsocelesTriangle":
                    points_str = f"{x + w/2},{y} {x},{y + h} {x + w},{y + h}"
                    svg_html += f'<polygon points="{points_str}" style="{style}" transform="{transform}"/>'
                    
                elif shape_type in ["CompoundShape", "Group"]:
                    inner_shapes = shape.get("shapes", {})
                    # Ensure inner_shapes is a dict for uniform processing
                    if isinstance(inner_shapes, list): 
                        inner_shapes = {str(i): s for i, s in enumerate(inner_shapes)}
                    
                    for inner_shape in inner_shapes.values():
                        if inner_shape:
                            processShape(inner_shape, parent_x=x, parent_y=y)

            # Process all top-level shapes
            for shape in shapes:
                if shape and shape.get('type'):
                    processShape(shape)
                    
            svg_html += '</svg>'
            
            self.logger.info("Successfully processed drawing/circuit with corrected coordinate handling and symbols.")
            return svg_html
            
        except Exception as e:
            self.logger.error(f"Error processing drawing/circuit block: {e}")
            traceback.print_exc()
            return ""

    # ==============================================================================
    # END OF UPDATED CODE BLOCK
    # ==============================================================================

    def _convert_asciimath_to_latex_for_copy(self, asciimath_str: str) -> str:
        if not asciimath_str: return ""
        latex_str = asciimath_str.replace('frac{', r'\frac{').replace(' \times ', r'\times ').replace('text{', r'\text{')
        latex_str = re.sub(r'_([A-Za-z0-9]+)', r'_{\1}', latex_str)
        latex_str = re.sub(r'\^([A-Za-z0-9]+)', r'^{\1}', latex_str)
        latex_str = re.sub(r'\(([A-Za-z]+)\)/\(([A-Za-z]+(?:-[A-Za-z]+)?)\)', r'(\1)/(\2)', latex_str)
        for key, val in self.symbol_map.items(): latex_str = latex_str.replace(key.strip('()'), val)
        return latex_str.replace('lambda', r'\lambda')

    def _convert_answer_to_clean_text(self, formatted_answer: dict) -> str:
        """
        Convert the formatted answer to clean text for copying with LaTeX math and markdown formatting.
        """
        try:
            text_content = []

            def process_content_item(item, indent=0):
                result_text = ""
                if item.get("type") == "paragraph":
                    paragraph_text = ""
                    for sub_item in item.get("content", []):
                        if sub_item.get("type") == "text":
                            text = sub_item.get("text", "")
                            if not text.strip() or text.strip() == "{}": continue
                            
                            math_type = self.is_mathematical_expression(text)
                            if math_type:
                                cleaned_expr = self.clean_math_expression(text)
                                latex_expr = self._convert_asciimath_to_latex_for_copy(cleaned_expr)
                                if math_type == 'display':
                                    text = f"$${latex_expr}$$"
                                else:
                                    text = f"${latex_expr}$"
                            
                            for mark in sub_item.get("marks", []):
                                if mark.get("type") == "bold": 
                                    text = f"**{text}**"
                                elif mark.get("type") == "italic": 
                                    text = f"*{text}*"
                                elif mark.get("type") == "code": 
                                    text = f"`{text}`"
                            
                            paragraph_text += text
                            
                        elif sub_item.get("type") == "inlineMath":
                            math_text = sub_item.get("content", [{}])[0].get("text", "")
                            cleaned_expr = self.clean_math_expression(math_text)
                            latex_expr = self._convert_asciimath_to_latex_for_copy(cleaned_expr)
                            paragraph_text += f"${latex_expr}$"
                            
                        elif sub_item.get("type") == "hardBreak":
                            paragraph_text += "\n"
                    
                    if paragraph_text:
                        result_text = "  " * indent + paragraph_text
                        
                elif item.get("type") in ["bulletList", "orderedList"]:
                    list_items = []
                    for list_item in item.get("content", []):
                        item_text = ""
                        for sub_item in list_item.get("content", []):
                            sub_result = process_content_item(sub_item, 0)
                            if sub_result: item_text += sub_result.strip()
                        if item_text:
                            prefix = "• " if item.get("type") == "bulletList" else f"{len(list_items) + 1}. "
                            list_items.append("  " * indent + prefix + item_text)
                    result_text = "\n".join(list_items)
                    
                elif item.get("type") == "heading":
                    level = item.get("attrs", {}).get("level", 3)
                    heading_text = ""
                    for sub_item in item.get("content", []):
                        if sub_item.get("type") == "text":
                            text = sub_item.get("text", "")
                            if not text.strip() or text.strip() == "{}": continue
                            
                            if self.is_mathematical_expression(text):
                                cleaned_expr = self.clean_math_expression(text)
                                latex_expr = self._convert_asciimath_to_latex_for_copy(cleaned_expr)
                                text = f"${latex_expr}$"
                            
                            for mark in sub_item.get("marks", []):
                                if mark.get("type") == "bold": 
                                    text = f"**{text}**"
                            heading_text += text
                    
                    if heading_text:
                        result_text = "  " * indent + "#" * level + " " + heading_text
                
                return result_text

            def process_block(block):
                block_type = block.get("type", "UNKNOWN")
                
                if block_type in ["TEXT", "EXPLANATION"]:
                    if block.get("label"):
                        text_content.append(f"**{block.get('label')}**")
                    
                    for item in block.get("block", {}).get("editorContentState", {}).get("content", []):
                        result = process_content_item(item)
                        if result: text_content.append(result)
                        
                elif block_type == "EQUATION_RENDERER":
                    for eqn in block.get("block", {}).get("lines", []):
                        equation_str = f"{eqn.get('left', '')} {eqn.get('operator', '')} {eqn.get('right', '')}"
                        cleaned_equation = self.clean_math_expression(equation_str)
                        latex_equation = self._convert_asciimath_to_latex_for_copy(cleaned_equation)
                        if latex_equation: 
                            text_content.append(f"$${latex_equation}$$")
                            
                elif block_type == "CODE_SNIPPET":
                    code_text = block.get("block", {}).get("content", {}).get("content", [{}])[0].get("content", [{}])[0].get("text", "")
                    if code_text.strip(): 
                        text_content.append(f"```\n{code_text}\n```")
                        
                elif block_type == "LIST":
                    for item in block.get("block", {}).get("editorContentState", {}).get("content", []):
                        result = process_content_item(item)
                        if result: text_content.append(result)
                        
                elif block_type in ["ACCOUNTING_TABLE", "TABLE"]:
                    block_data = block.get("block", {}) or block.get("content", {})
                    
                    if block_type == "ACCOUNTING_TABLE":
                        entries = block_data.get("entries", [])
                        for entry in entries:
                            headers = entry.get("headerCells", {})
                            body_cells = entry.get("bodyCells", {})
                            
                            if headers:
                                header_row = []
                                for key in sorted(headers.keys(), key=lambda x: int(x.split('-')[1]) if '-' in x else 0):
                                    cell_value = headers[key].get("value", "")
                                    if isinstance(cell_value, dict) and 'type' in cell_value:
                                        cell_content = cell_value.get('content', [{}])[0].get('content', [{}])[0].get('text', '')
                                    else:
                                        cell_content = str(cell_value) if cell_value else ""
                                    
                                    if cell_content and self.is_mathematical_expression(cell_content):
                                        cleaned_expr = self.clean_math_expression(cell_content)
                                        latex_expr = self._convert_asciimath_to_latex_for_copy(cleaned_expr)
                                        cell_content = f"${latex_expr}$"
                                    
                                    if cell_content: header_row.append(cell_content)
                                
                                if header_row:
                                    text_content.append("| " + " | ".join(header_row) + " |")
                                    text_content.append("| " + " | ".join(["---"] * len(header_row)) + " |")
                            
                            if body_cells:
                                rows_data = {}
                                for key, cell in body_cells.items():
                                    try:
                                        row, col = map(int, key.split('-'))
                                        if row not in rows_data:
                                            rows_data[row] = {}
                                        rows_data[row][col] = cell
                                    except:
                                        continue
                                
                                for row_idx in sorted(rows_data.keys()):
                                    row_cells = []
                                    row_data = rows_data[row_idx]
                                    max_col = max(row_data.keys()) if row_data else 0
                                    for col_idx in range(max_col + 1):
                                        cell = row_data.get(col_idx, {})
                                        cell_value = cell.get("value", "")
                                        
                                        if isinstance(cell_value, dict) and 'type' in cell_value:
                                            cell_content = cell_value.get('content', [{}])[0].get('content', [{}])[0].get('text', '')
                                        else:
                                            cell_content = str(cell_value) if cell_value else ""
                                        
                                        if cell_content and self.is_mathematical_expression(cell_content):
                                            cleaned_expr = self.clean_math_expression(cell_content)
                                            latex_expr = self._convert_asciimath_to_latex_for_copy(cleaned_expr)
                                            cell_content = f"${latex_expr}$"
                                        
                                        row_cells.append(cell_content)
                                    
                                    text_content.append("| " + " | ".join(row_cells) + " |")
                    
                    elif block_type == "TABLE":
                        cells = block_data.get("cells", {})
                        columns = block_data.get("columns", 0)
                        row_count = block_data.get("rows", 0) if isinstance(block_data.get("rows"), int) else len(block_data.get("rows", []))
                        
                        for row_idx in range(row_count):
                            row_cells = []
                            for col_idx in range(columns):
                                cell_key = f"{row_idx}-{col_idx}"
                                cell = cells.get(cell_key, {})
                                cell_value = cell.get("value", "")
                                
                                if isinstance(cell_value, dict) and 'type' in cell_value:
                                    cell_content = cell_value.get('content', [{}])[0].get('content', [{}])[0].get('text', '')
                                else:
                                    cell_content = str(cell_value) if cell_value else ""
                                
                                if cell_content and self.is_mathematical_expression(cell_content):
                                    cleaned_expr = self.clean_math_expression(cell_content)
                                    latex_expr = self._convert_asciimath_to_latex_for_copy(cleaned_expr)
                                    cell_content = f"${latex_expr}$"
                                
                                row_cells.append(cell_content)
                            
                            text_content.append("| " + " | ".join(row_cells) + " |")
                            if row_idx == 0:
                                text_content.append("| " + " | ".join(["---"] * columns) + " |")

            if "stepByStep" in formatted_answer and formatted_answer["stepByStep"]["steps"]:
                for i, step in enumerate(formatted_answer["stepByStep"]["steps"]):
                    step_title = step.get("title", "").strip()
                    
                    step_header = f"**Step {i + 1}"
                    if step_title:
                        step_header += f": {step_title}"
                    step_header += "**"
                    text_content.append(step_header)
                    
                    for block in step.get("blocks", []):
                        process_block(block)
                    
                    text_content.append("")

            if "finalAnswer" in formatted_answer and formatted_answer["finalAnswer"]["blocks"]:
                text_content.append("**Final Answer**")
                for block in formatted_answer["finalAnswer"]["blocks"]:
                    process_block(block)

            if ("blocks" in formatted_answer and 
                not (formatted_answer.get("stepByStep", {}).get("steps") or 
                     formatted_answer.get("finalAnswer", {}).get("blocks"))):
                for block in formatted_answer["blocks"]:
                    process_block(block)

            result = "\n".join(line for line in text_content if line.strip())
            return result

        except Exception as e:
            self.logger.error(f"Error converting answer to clean text: {e}")
            return ""

    def generate_html_string(self, question_data_obj) -> str:
        """
        Generates HTML string directly for web rendering.
        """
        try:
            # Extract raw question content
            q_content_raw = (
                question_data_obj.get('content', {}).get('body') or
                question_data_obj.get('content', {}).get('textContent') or
                question_data_obj.get('content', {}).get('transcribedData') or
                ""
            )
                
            # Format Answer
            formatted_answer = self.format_answer_content(question_data_obj)
            answer_content = self.process_sqna_content_for_html(formatted_answer, mode='display')
                
            # Process images in question
            question_soup = BeautifulSoup(q_content_raw, 'html.parser')
            for img in question_soup.find_all('img'):
                if 'src' in img.attrs:
                    img['style'] = 'max-width: 100%; height: auto; border-radius: 12px;'
                else: 
                    img.decompose()
            formatted_question_content = str(question_soup)
                
            # Construct Final HTML
            html_content = f'''
            <div class="solution-container animate-fade-in">
                <div class="mb-8">
                    <h2 class="text-2xl font-bold text-slate-800 mb-4 border-b pb-2">Question</h2>
                    <div class="prose max-w-none text-slate-700 bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
                        {formatted_question_content}
                    </div>
                </div>
                    
                <div>
                    <h2 class="text-2xl font-bold text-slate-800 mb-4 border-b pb-2">Solution</h2>
                    <div class="prose max-w-none text-slate-700 bg-white p-6 rounded-xl border border-slate-200 shadow-sm" id="solution-content">
                        {answer_content}
                    </div>
                </div>
            </div>
            '''
            return html_content
        except Exception as e:
            self.logger.error(f"Error generating HTML: {e}")
            return f"<div class='p-4 bg-red-50 text-red-600 rounded'>Error formatting solution: {str(e)}</div>"

answer_generator = AnswerGenerator()
__all__ = ['AnswerGenerator', 'answer_generator']
