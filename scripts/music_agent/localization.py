"""English authored copy with Unicode-safe user and model content."""
from copy import deepcopy


class TranslatedText(str):
    """Compatibility wrapper for authored text; new call sites use plain English."""
    def __new__(cls, value, english=None):
        value = str(value if english is None else english)
        result = super().__new__(cls, value)
        result.english = value
        return result

    def __getnewargs__(self):
        return str(self), self.english


L = TranslatedText


def english(value):
    return value.english if isinstance(value, TranslatedText) else value


def normalize_language(value):
    # Legacy saved locale codes remain accepted, but authored UI copy is English.
    return "en"


def authored(value, *, error=False):
    """Translate only a known authored value, never arbitrary user/model text."""
    if isinstance(value, TranslatedText):
        return value.english
    if not isinstance(value, str):
        return value
    if error and any('\u4e00' <= char <= '\u9fff' for char in value):
        # Unknown diagnostics remain intact in runtime state for troubleshooting.
        # Do not run a paid translation or rewrite an embedded project name.
        return "This request could not be completed. Review the selected objects and task settings."
    return value


def _typed(value):
    if isinstance(value, TranslatedText):
        return value.english
    if isinstance(value, dict):
        return {key: _typed(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_typed(item) for item in value]
    return value


def public_response(value, language):
    if not isinstance(value, dict):
        return value
    result = _typed(deepcopy(value))
    if result.get('error'):
        result['error'] = authored(result['error'], error=True)
    if result.get('last_result'):
        result['last_result'] = authored(result['last_result'], error=True)
    if isinstance(result.get('progress'), dict):
        result['progress']['label'] = authored(result['progress'].get('label', ''), error=True)
    for message in result.get('messages', []):
        if message.get('origin') == 'runtime':
            message['content'] = authored(message['content'], error=True)
    preview = result.get('generation_preview')
    if isinstance(preview, dict) and preview.get('detail'):
        preview['detail'] = authored(preview['detail'], error=True)
    return result


def response_instruction(language):
    name = 'English'
    return (f"\nThe interface language for this request is {name}. Write all assistant replies, "
            f"plan summaries and explanations in {name}, including after tool results. "
            "The language of internal tool descriptions, previous messages and project data does not override this. "
            "If the user explicitly requests a different response language, honor that request. "
            "Preserve user-provided track names, filenames, music descriptions and lyrics in their original language; "
            "do not translate or rename project data just to match the interface.\n")
