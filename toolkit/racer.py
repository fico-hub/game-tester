"""Concurrent request race condition tester.

Sends multiple identical or conflicting requests simultaneously
to detect duplicate effects, resource multiplication, or state corruption.
"""

import threading
import time
import json
import sys


def run(client, profile, threads=10, verbose=False):
    """Execute race condition tests.

    Returns list of findings (potential bugs).
    """
    findings = []

    # We need a valid game state to race test
    state = client.snapshot_state()
    city = state.get('city', {})
    armies = state.get('armies', {})

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"RACE CONDITION TESTING — {threads} concurrent threads", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Test 1: Duplicate command submission
    print("\n--- Test: Duplicate season.join ---", file=sys.stderr)
    result = _race_command(client, "season.join", {}, threads)
    finding = _analyze_race(result, "season.join", "duplicate_submit", threads)
    if finding:
        findings.append(finding)

    # Test 2: Duplicate city.build
    print("\n--- Test: Duplicate city.build ---", file=sys.stderr)
    result = _race_command(client, "city.build", {"facilityType": "farm"}, threads)
    finding = _analyze_race(result, "city.build", "duplicate_build", threads)
    if finding:
        findings.append(finding)

    # Test 3: Race on army operations (if armies exist)
    army_data = armies.get('data', {})
    army_list = None
    if isinstance(army_data, dict):
        army_list = army_data.get('armies', army_data.get('data', []))
    if isinstance(army_data, list):
        army_list = army_data
    if army_list and len(army_list) > 0:
        army_id = army_list[0].get('id') or army_list[0].get('armyId')
        if army_id:
            print(f"\n--- Test: Duplicate army.conscript (army={army_id}) ---", file=sys.stderr)
            result = _race_command(
                client, "army.conscript",
                {"armyId": army_id, "slot": 0, "unitType": "infantry", "count": 10},
                threads
            )
            finding = _analyze_race(result, "army.conscript", "duplicate_conscript", threads)
            if finding:
                findings.append(finding)

    # Test 4: Rapid-fire requests to detect rate limiting
    print("\n--- Test: Rate limit probe (50 rapid GETs) ---", file=sys.stderr)
    result = _race_get(client, profile, "/city", 50)
    rate_limited = sum(1 for r in result if r.get('status') == 429)
    if rate_limited == 0:
        findings.append({
            'severity': 'low',
            'category': 'race',
            'title': 'No rate limiting detected on authenticated endpoints',
            'endpoint': 'GET /city',
            'details': f"50 concurrent requests all returned successfully, no 429 responses",
            'expected': 'Server should rate-limit rapid requests',
            'actual': f"All {len(result)} requests succeeded",
        })
        print(f"  ⚠️  No rate limiting: 0/{len(result)} got 429", file=sys.stderr)
    else:
        print(f"  ✓ Rate limiting active: {rate_limited}/{len(result)} got 429", file=sys.stderr)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"RACE SUMMARY: {len(findings)} findings", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return findings


def _race_command(client, cmd_type, payload, count):
    """Fire N identical commands simultaneously using a barrier."""
    results = [None] * count
    barrier = threading.Barrier(count, timeout=10)

    def fire(i):
        try:
            barrier.wait()
            results[i] = client.submit_command(cmd_type, payload)
        except Exception as e:
            results[i] = {'status': 0, 'error': str(e)}

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # Log results
    statuses = {}
    for r in results:
        if r:
            s = r.get('status', 0)
            statuses[s] = statuses.get(s, 0) + 1
    print(f"  Results: {statuses}", file=sys.stderr)

    return results


def _race_get(client, profile, path, count):
    """Fire N identical GET requests simultaneously."""
    results = [None] * count
    barrier = threading.Barrier(count, timeout=10)

    def fire(i):
        try:
            barrier.wait()
            results[i] = client.get(path)
        except Exception as e:
            results[i] = {'status': 0, 'error': str(e)}

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    return results


def _analyze_race(results, cmd_type, test_name, expected_count):
    """Analyze race results for duplicate effects."""
    successes = 0
    failures = 0
    errors = 0

    for r in results:
        if not r:
            errors += 1
            continue
        status = r.get('status', 0)
        if status == 0:
            errors += 1
        elif status >= 400:
            failures += 1
        else:
            # Check command result
            data = r.get('data', {})
            cmd_status = data.get('status', '')
            if cmd_status in ('completed', 'pending', 'running'):
                successes += 1
            elif cmd_status in ('failed', 'rejected', 'blocked'):
                failures += 1
            else:
                successes += 1  # Assume success if no explicit failure

    print(f"  Success: {successes}, Failed: {failures}, Errors: {errors}", file=sys.stderr)

    # If multiple identical commands all succeeded, that's suspicious
    if successes > 1:
        return {
            'severity': 'medium',
            'category': 'race',
            'title': f'Multiple duplicate {cmd_type} commands succeeded simultaneously',
            'endpoint': cmd_type,
            'test': test_name,
            'details': f"{successes}/{expected_count} duplicate commands succeeded",
            'expected': f"At most 1 of {expected_count} duplicate commands should succeed",
            'actual': f"{successes} commands succeeded, potentially causing duplicate effects",
        }

    return None
