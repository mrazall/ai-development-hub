"""Deterministic, explainable observations: each names the rule that fired. No model calls, no scores."""
from statistics import median


def observations(rows):
    found = []
    comparable = [r for r in rows if r['status'] == 'done' and r['cost_usd'] is not None and not r['cost_partial']]
    if len(comparable) >= 5:
        middle = median(r['cost_usd'] for r in comparable)
        found += [{'code': 'task_cost_above_median', 'severity': 'notice', 'subject': {'task_id': r['task_id']},
                   'params': {'cost_usd': r['cost_usd'], 'median_cost_usd': middle, 'n': len(comparable)},
                   'criterion': 'cost > 3 × median of comparable tasks (n ≥ 5)'}
                  for r in sorted(comparable, key=lambda x: x['task_id']) if r['cost_usd'] > 3 * middle]
    for r in sorted(rows, key=lambda x: x['task_id']):
        orchestrator = (r.get('orchestrator') or {}).get('cost_usd')
        executors = (r.get('executors') or {}).get('cost_usd')
        # Only exact prices and a real orchestration (both sides spent): a high share is a fact, not a verdict.
        if not r['cost_partial'] and orchestrator is not None and executors and orchestrator + executors >= 1:
            share = orchestrator / (orchestrator + executors)
            if share > 0.5:
                found.append({'code': 'orchestrator_cost_majority', 'severity': 'info', 'subject': {'task_id': r['task_id']},
                              'params': {'share': share, 'orchestrator_cost_usd': orchestrator, 'executors_cost_usd': executors},
                              'criterion': 'orchestrator cost > 50 % of the orchestration (exact prices, total ≥ $1)'})
        if r.get('retries', 0) >= 2:
            found.append({'code': 'repeated_retries', 'severity': 'notice', 'subject': {'task_id': r['task_id']},
                          'params': {'retries': r.get('retries', 0)},
                          'criterion': '≥ 2 confirmed re-runs after a failure'})
    unknown = [r for r in rows if 'wall_s' in r and r['wall_s'] is None]
    if unknown:
        found.append({'code': 'duration_unknown', 'severity': 'info', 'subject': {},
                      'params': {'tasks': len(unknown), 'total': len(rows)},
                      'criterion': 'no confirmed start and end in the session status events'})
    return found


def task_warnings(item, runs):
    """What is incomplete in one task's numbers, so the reader knows which figures are estimates."""
    warnings = []
    if item['cost_partial']:
        warnings.append({'code': 'cost_partial', 'params': {}})
    if item['wall_s'] is None:
        warnings.append({'code': 'duration_unknown', 'params': {}})
    elif item.get('duration_basis') == 'estimated':
        warnings.append({'code': 'duration_estimated', 'params': {}})
    inexact = sum(1 for run in runs if run.get('attribution') != 'exact')
    if inexact:
        warnings.append({'code': 'attribution_estimated', 'params': {'runs': inexact, 'total': len(runs)}})
    return warnings
