"""Evaluation-only numeric plan excerpts; original execution plans stay intact."""
from copy import deepcopy
import json

from kplasma_agent.v2_local_llm.core.contracts import PlanDraft
from kplasma_agent.v2_local_llm.core.plan_checks import build_check_specs

VERSION = 'literal-numeric-excerpt-1'


def _literal_only(value):
    if isinstance(value, dict):
        if 'kind' in value:
            return value['kind'] == 'literal' and type(value.get('value')) in (int, float)
        return all(_literal_only(item) for item in value.values())
    if isinstance(value, list):
        return all(_literal_only(item) for item in value)
    return True


def project_numeric_review(native):
    """Select literal filter operands; keep all other checks byte-identical."""
    try:
        if len(native['questions']) != 1:
            raise ValueError('not_singleton')
        qid = next(iter(native['questions']))
        state = json.loads(native['state'])
        spec, = [s for s in state['check_specs'] if s['name'] == qid]
        if spec['kind'] != 'filter':
            return deepcopy(native), {'action': 'unchanged', 'reason': 'not_numeric', 'version': VERSION}
        plan = state['plan']
        PlanDraft.model_validate(plan)
        if state['check_specs'] != build_check_specs(plan) or len(spec['step_ids']) != 1 or not spec['paths']:
            raise ValueError('unknown_check')
        index, = {path[1] for path in spec['paths']}
        step = plan['steps'][index]
        if step['id'] != spec['step_ids'][0] or any(step.get(k) for k in ('depends_on', 'run_if', 'required_prior_outputs')):
            raise ValueError('dependent_numeric_input')
        selected: dict = ({key: [{'omitted_from_review': True} for _ in step['inputs'][key]]
                     for key in ('constraints', 'goals')} if step.get('tool') == 'reverse_search' else {})
        for path in spec['paths']:
            if path[:3] != ['steps', index, 'inputs']:
                raise ValueError('unsupported_path')
            if step.get('tool') == 'forward_lookup' and len(path) == 4:
                field = path[3]
                if field != spec['metric'] or field not in {'pressure', 'source_power', 'bias_power'}:
                    raise ValueError('unsupported_metric')
                operand = step['inputs'][field]
                if not isinstance(operand, dict) or not _literal_only(operand):
                    raise ValueError('nonliteral_numeric_input')
                selected[field] = deepcopy(operand)
            elif step.get('tool') == 'reverse_search' and len(path) == 5 and path[3] in {'constraints', 'goals'}:
                key, row_index = path[3:]
                operand = step['inputs'][key][row_index]
                if operand['field'] != spec['metric'] or not _literal_only(operand):
                    raise ValueError('nonliteral_numeric_input')
                if key not in selected:
                    selected[key] = [{'omitted_from_review': True} for _ in step['inputs'][key]]
                selected[key][row_index] = deepcopy(operand)
            else:
                raise ValueError('unsupported_path')
        view = deepcopy(state)
        excerpt = view['plan']
        excerpt['requirements'] = [{k: r[k] for k in ('id', 'handled_by')} for r in plan['requirements']]
        for i, original in enumerate(plan['steps']):
            if i == index:
                excerpt['steps'][i]['inputs'] = selected
            else:
                excerpt['steps'][i] = {k: original[k] for k in ('id', 'kind', 'tool', 'operation', 'confirmation') if k in original}
                excerpt['steps'][i]['omitted_from_review'] = True
        view['check_specs'] = [deepcopy(spec)]
        view.pop('program_effects', None)
        view.pop('execution_view', None)
        view['review_view'] = {'kind': 'numeric_excerpt', 'complete_executable_plan': False,
                               'check_name': qid, 'included_plan_paths': deepcopy(spec['paths']),
                               'omitted_fields_are_not_missing_plan_fields': True}
        result = deepcopy(native)
        result['state'] = json.dumps(view, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        return result, {'action': 'selected', 'version': VERSION, 'check_name': qid,
                        'preserved_plan_paths': deepcopy(spec['paths']), 'step_index': index}
    except (ValueError, KeyError, IndexError, TypeError, StopIteration) as error:
        return deepcopy(native), {'action': 'fallback', 'reason': str(error), 'version': VERSION}
