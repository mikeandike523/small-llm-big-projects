import json

from requests.exceptions import HTTPError

def add_indent(text, indent: str | int):
    lines = text.split("\n")
    indent_string = indent if isinstance(indent, str) else " " * indent
    return "\n".join(indent_string + line for line in lines)

def format_http_error(error: HTTPError):
    try:
        has_body_json = False
        body_json = None
        body_text = error.response.text
        
        try:
            body_json = json.loads(body_text)
            has_body_json = True
        except:
            pass

        
        result = f"Status: {error.response.status_code}\n"
        if has_body_json:
            result += f"Data:\n\n{add_indent(json.dumps(body_json, indent=2), 2)}"
        result += f"\n\nBody:\n\n{add_indent(body_text, 2)}"
        return result
        

    except Exception as e:
        return f"Could not format http error: {e}"