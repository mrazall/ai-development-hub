from aihub_control.analytics.efficiency import _add, _blank, _cost
from aihub_control.analytics.observations import observations
from aihub_control.analytics.usage import normalize, parse_prices, price_of


def test_normalization_and_prices():
    tokens = normalize('codex', {'input_tokens': 100, 'cached_input_tokens': 60, 'output_tokens': 10})
    assert tokens == {'input': 40, 'cache_read': 60, 'cache_write': 0, 'output': 10}
    claude = normalize('claude_code', {'input_tokens': 10, 'cache_read_input_tokens': 20, 'cache_creation_input_tokens': 5})
    assert price_of(claude, parse_prices('m=2,1,3')['m']) == 50 / 1_000_000


def test_missing_and_partial_cost():
    bucket = _blank()
    assert _cost(bucket) is None
    _add(bucket, {'input': 10, 'cache_read': 0, 'cache_write': 0, 'output': 0}, None)
    assert _cost(bucket) is None and bucket['unpriced'] == 10
    _add(bucket, {'input': 1, 'cache_read': 0, 'cache_write': 0, 'output': 0}, 2.0)
    assert _cost(bucket) == 2.0


def test_observations_only_comparable_done_tasks():
    rows = [{'task_id': str(i), 'status': 'done', 'cost_usd': cost, 'cost_partial': False}
            for i, cost in enumerate([1, 1, 1, 1, 4])]
    rows.append({'task_id': 'other', 'status': 'failed', 'cost_usd': 99, 'cost_partial': False})
    assert [o['subject']['task_id'] for o in observations(rows)] == ['4']


def test_observation_rules_name_their_criterion():
    from aihub_control.analytics.observations import observations, task_warnings

    def row(task_id, **extra):
        base = {'task_id': task_id, 'status': 'review', 'cost_usd': 2.0, 'cost_partial': False, 'retries': 0,
                'wall_s': 60.0, 'orchestrator': {'cost_usd': 1.5}, 'executors': {'cost_usd': 0.5}}
        return {**base, **extra}

    found = observations([row('a'), row('b', retries=3, orchestrator={'cost_usd': 0.1}),
                          row('c', wall_s=None, orchestrator={'cost_usd': None}, executors={'cost_usd': None}),
                          row('d', cost_partial=True)])
    by_code = {}
    for item in found:
        by_code.setdefault(item['code'], []).append(item)
    # 1.5 of 2.0 on the orchestrator (exact prices) — a fact with its criterion, not a verdict; partial costs never count.
    assert [o['subject']['task_id'] for o in by_code['orchestrator_cost_majority']] == ['a']
    assert by_code['orchestrator_cost_majority'][0]['params']['share'] == 0.75
    assert [o['subject']['task_id'] for o in by_code['repeated_retries']] == ['b']
    assert by_code['duration_unknown'][0]['params'] == {'tasks': 1, 'total': 4}
    assert all(o['criterion'] for o in found)

    item = row('x', cost_partial=True, wall_s=None)
    codes = [w['code'] for w in task_warnings(item, [{'attribution': 'exact'}, {'attribution': 'estimated'}])]
    assert codes == ['cost_partial', 'duration_unknown', 'attribution_estimated']
    assert task_warnings(row('y'), [{'attribution': 'exact'}]) == []
