"""Evaluator-only regression scenarios for the receipt-replay repair case.

Not distributed with the case materials. challenge_verify.py --regress builds randomized
scenarios here, sends only their inputs into the sandbox, and compares what the submitted
replay() returned against reference_replay() in the parent process. The verdict never
depends on anything the submitted code prints or returns about itself, so it cannot be
forged from inside the sandbox; only producing the correct balances passes.

Running this file directly imports allocation.py in-process and prints a manual summary;
that mode is a convenience for people, not evidence.
"""
import copy
import random


def reference_replay(initial, receipts):
    """Trusted behaviour from contract.txt: batch identity is (receipt, order, sku)."""
    balances = dict(initial); seen = {}
    for row in receipts:
        identity = row['receipt'], row['order'], row['sku']
        if identity in seen:
            if seen[identity] != row['quantity']:
                raise ValueError(identity)
            continue
        seen[identity] = row['quantity']
        key = row['order'], row['sku']
        balances[key] = balances.get(key, 0) + row['quantity']
    return balances


def scenarios(rng=None):
    """[(name, calls)] where calls is a list of (initial, receipts or csv text) run in one process.

    Values are random per run so expected balances cannot be precomputed by the submission.
    """
    rng = rng or random.SystemRandom()
    def tokens(prefix, count):
        return [f'{prefix}{number}' for number in rng.sample(range(10**5, 10**6), count)]

    qty = lambda: rng.randrange(2, 40)
    order, other_order = tokens('O', 2)
    sku, other_sku = tokens('S', 2)
    r1, r2, r3 = tokens('R', 3)
    q, q2 = qty(), qty()
    row = lambda receipt, o, s, n: dict(receipt=receipt, order=o, sku=s, quantity=n)
    opening = {(order, sku): qty(), (other_order, other_sku): qty()}
    return [
        ('exact_retry_with_opening_balance', [(opening, [row(r1, order, sku, q), row(r1, order, sku, q)])]),
        ('same_quantity_is_not_identity', [({}, 'receipt,order,sku,quantity\n'
            f'{r1},{order},{sku},{q}\n{r2},{order},{sku},{q}\n{r1},{order},{other_sku},{q}\n{r1},{other_order},{sku},{q}\n')]),
        ('conflicting_quantity', [({}, [row(r1, order, sku, q), row(r1, order, sku, q + 1)])]),
        ('non_adjacent_retry', [({(order, sku): 1}, [row(r1, order, sku, q), row(r2, order, sku, q), row(r1, order, sku, q)])]),
        ('non_adjacent_conflict', [(opening, [row(r1, order, sku, q), row(r2, order, sku, q), row(r1, order, sku, q + 1)])]),
        ('state_does_not_leak_between_calls', [({}, [row(r3, order, sku, q2)] * 2), ({}, [row(r3, order, sku, q2)] * 2)]),
    ]


def expected(calls):
    """Reference outcome per call: ('ok', balances) or ('error', 'ValueError')."""
    import csv
    import io
    results = []
    for initial, receipts in calls:
        if isinstance(receipts, str):
            receipts = [dict(receipt=r['receipt'], order=r['order'], sku=r['sku'], quantity=int(r['quantity']))
                        for r in csv.DictReader(io.StringIO(receipts))]
        try:
            results.append(('ok', reference_replay(copy.deepcopy(initial), copy.deepcopy(receipts))))
        except ValueError:
            results.append(('error', 'ValueError'))
    return results


if __name__ == '__main__':
    import io
    from allocation import read_receipts, replay
    failures = 0
    for name, calls in scenarios():
        for (initial, receipts), want in zip(calls, expected(calls)):
            rows = read_receipts(io.StringIO(receipts)) if isinstance(receipts, str) else receipts
            try:
                got = ('ok', replay(initial, rows))
            except ValueError:
                got = ('error', 'ValueError')
            failures += got != want
            print(('ok  ' if got == want else 'FAIL'), name)
    raise SystemExit(1 if failures else 0)
