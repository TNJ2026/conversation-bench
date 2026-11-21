"""Evaluator-only regression scenarios for the three Extension10 repair cases.

Not distributed with the case materials. challenge_verify.py --regress builds randomized
scenarios here, sends only their inputs into the sandbox, and compares the raw results of the
submitted program.py with the reference implementations below in the parent process. Nothing
the submission prints decides the verdict, and the inputs differ on every run, so special-casing
the visible tests cannot pass.

Results use one JSON form on both sides:
  {'kind': 'ok', ...payload}   the call returned a value that follows the contract's shape
  {'kind': 'error'}            the call raised ValueError
  {'kind': 'bad', 'detail'}    the call broke the contract (mutated input, wrong return type)
  {'kind': 'crash', 'detail'}  any other exception
"""
import random

STABLE = 'repair-stable-priority'
ATOMIC = 'repair-atomic-batch'
WINDOW = 'repair-overnight-window'
CASES = (STABLE, ATOMIC, WINDOW)


# ---------- trusted behaviour, from each case's contract.txt ----------

def reference_rank(rows):
    """Input indices in output order: priority descending, ties in arrival order."""
    return [i for i, _ in sorted(enumerate(rows), key=lambda pair: -pair[1]['priority'])]


def reference_apply(current, updates):
    for name, amount in updates:
        if name not in current or type(amount) is not int or not 0 <= amount <= 20:
            return dict(kind='error')
    result = dict(current)
    for name, amount in updates:
        result[name] = amount
    return dict(kind='ok', value=sorted([k, v] for k, v in result.items()))


def reference_inside(start, end, minute):
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end


def expected(case_id, calls):
    """Reference result per call, in the same JSON form the sandbox returns."""
    if case_id == STABLE:
        return [dict(kind='ok', rows=[call['rows'][i] for i in reference_rank(call['rows'])]) for call in calls]
    if case_id == ATOMIC:
        return [reference_apply(dict(call['current']), [tuple(u) for u in call['updates']]) for call in calls]
    if case_id == WINDOW:
        return [dict(kind='ok', values=[reference_inside(*t) for t in call['triples']]) for call in calls]
    raise ValueError(f'unknown Extension10 repair case: {case_id}')


# ---------- randomized inputs ----------

def scenarios(case_id, rng=None):
    """[(name, calls)]; every value is JSON-safe and random per run."""
    rng = rng or random.SystemRandom()
    if case_id == STABLE:
        return _rank_scenarios(rng)
    if case_id == ATOMIC:
        return _update_scenarios(rng)
    if case_id == WINDOW:
        return _window_scenarios(rng)
    raise ValueError(f'unknown Extension10 repair case: {case_id}')


def _ids(rng, count):
    return [f'T{n}' for n in rng.sample(range(10**4, 10**5), count)]


def _rank_scenarios(rng):
    def rows(ids, priorities, **extra):
        return [dict(id=i, priority=p, **extra) for i, p in zip(ids, priorities)]

    # Tied rows arrive in reverse ID order, so any fix that lets the ID break ties is caught.
    high, low = rng.randrange(5, 50), rng.randrange(-5, 5)
    against = sorted(_ids(rng, 6), reverse=True)
    pattern = [high, low, high, low, high, low]
    many = _ids(rng, 14)
    return [
        ('ties_against_id_order', [dict(rows=rows(against, pattern))]),
        ('random_ties', [dict(rows=rows(many, [rng.randrange(0, 3) for _ in many]))]),
        ('negative_priorities', [dict(rows=rows(_ids(rng, 8), [rng.randrange(-4, 3) for _ in range(8)]))]),
        ('extra_fields_untouched', [dict(rows=rows(_ids(rng, 5), [rng.randrange(0, 2) for _ in range(5)],
                                                    note=f'n{rng.randrange(100)}'))]),
        ('empty_input', [dict(rows=[])]),
    ]


def _update_scenarios(rng):
    keys = _ids(rng, 3)
    current = {k: rng.randrange(0, 21) for k in keys}
    a, b, c = keys
    ok = lambda: rng.randrange(0, 21)
    too_big = rng.randrange(21, 99)
    unknown = _ids(rng, 1)[0]
    repeats = [[a, ok()] for _ in range(rng.randrange(2, 6))]
    call = lambda updates: [dict(current=dict(current), updates=updates)]
    return [
        ('invalid_after_valid', call([[a, ok()], [b, too_big]])),
        ('later_value_masks_invalid', call([[a, too_big], [a, ok()]])),
        ('negative_rejected', call([[c, ok()], [a, -rng.randrange(1, 9)]])),
        ('bool_rejected', call([[b, ok()], [a, True]])),
        ('float_rejected', call([[a, float(ok())]])),
        ('string_rejected', call([[a, str(ok())]])),
        ('unknown_key_last', call([[a, ok()], [b, ok()], [unknown, ok()]])),
        ('bounds_accepted', call([[a, 0], [b, 20]])),
        ('repeats_last_wins', call(repeats + [[c, ok()]])),
        ('empty_batch_returns_copy', call([])),
    ]


def _window_scenarios(rng):
    def minutes(start, end):
        near = {start - 1, start, start + 1, end - 1, end, end + 1, 0, 1439}
        return sorted(m % 1440 for m in near)

    overnight = rng.randrange(1000, 1439), rng.randrange(1, 400)
    same_day = sorted(rng.sample(range(1, 1439), 2))
    point = rng.randrange(0, 1440)
    edges = [[s, e, m] for s, e in (overnight, tuple(same_day), (point, point), (rng.randrange(1, 1440), 0))
             for m in minutes(s, e)]
    noise = [[rng.randrange(1440), rng.randrange(1440), rng.randrange(1440)] for _ in range(400)]
    return [('edges', [dict(triples=edges)]), ('random_windows', [dict(triples=noise)])]


if __name__ == '__main__':
    # Manual convenience run against ./program.py in-process; not evidence.
    import importlib
    import json
    import sys
    case_id = sys.argv[1] if len(sys.argv) > 1 else STABLE
    program = importlib.import_module('program')
    failures = 0
    for name, calls in scenarios(case_id):
        for call, want in zip(calls, expected(case_id, calls)):
            try:
                if case_id == STABLE:
                    got = dict(kind='ok', rows=program.rank(call['rows']))
                elif case_id == ATOMIC:
                    out = program.apply_updates(dict(call['current']), [tuple(u) for u in call['updates']])
                    got = dict(kind='ok', value=sorted([k, v] for k, v in out.items()))
                else:
                    got = dict(kind='ok', values=[program.inside(*t) for t in call['triples']])
            except ValueError:
                got = dict(kind='error')
            matched = json.dumps(got, sort_keys=True) == json.dumps(want, sort_keys=True)
            failures += not matched
            print('ok  ' if matched else 'FAIL', name)
    raise SystemExit(1 if failures else 0)
