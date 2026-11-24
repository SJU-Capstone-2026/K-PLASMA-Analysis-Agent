"""Give literal quotations a distinct name in numeric d1 review copies."""
from copy import deepcopy
import json

VERSION = 'numeric-citation-name-1'


def rename_numeric_citations(native):
    """Rename provenance keys and their fixed references, never user text."""
    state = json.loads(native['state'])
    scope = state.get('review_view', {})
    if scope.get('kind') != 'numeric_excerpt':
        return deepcopy(native), {'action': 'unchanged', 'version': VERSION}
    if len(native['questions']) != 1 or scope['check_name'] not in native['questions']:
        raise ValueError('invalid citation review scope')
    renamed = 0

    def visit(value):
        nonlocal renamed
        if isinstance(value, list):
            return [visit(item) for item in value]
        if not isinstance(value, dict):
            return value
        literal = value.get('kind') == 'literal'
        if literal:
            if 'citation' in value:
                raise ValueError('conflicting citation key')
            source = value.get('source')
            if not isinstance(source, dict) or set(source) != {'message_key', 'quote'}:
                raise ValueError('invalid citation source')
            renamed += 1
        return {('citation' if literal and key == 'source' else key): visit(item)
                for key, item in value.items()}

    state['plan'] = visit(state['plan'])
    if not renamed:
        raise ValueError('missing literal citation')
    state['tool_contracts']['bindings']['literal'] = state['tool_contracts']['bindings']['literal'].replace(
        'source.quote', 'citation.quote')
    result = deepcopy(native)
    for question in result['questions'].values():
        question['instructions'] = question['instructions'].replace('source.quote', 'citation.quote')
    result['state'] = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    return result, {'action': 'renamed', 'version': VERSION, 'renamed_citations': renamed,
                    'old_path': 'source.quote', 'new_path': 'citation.quote'}
