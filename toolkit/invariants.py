"""State integrity and economy invariant checker.

Snapshots game state before and after operations,
then verifies that invariant properties still hold.
"""

import json
import sys


def run(client, profile, verbose=False):
    """Execute invariant checks.

    Returns list of findings (violated invariants).
    """
    findings = []

    print(f"\n{'='*60}", file=sys.stderr)
    print("STATE INVARIANT CHECKING", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Snapshot initial state
    print("\n--- Capturing initial state ---", file=sys.stderr)
    before = client.snapshot_state()
    _print_state_summary(before)

    # Check 1: Resources non-negative (baseline)
    print("\n--- Check: Resources non-negative (baseline) ---", file=sys.stderr)
    finding = _check_resources_non_negative(before, "baseline")
    if finding:
        findings.append(finding)

    # Check 2: Perform an action and verify state consistency
    print("\n--- Check: Build then verify state ---", file=sys.stderr)
    resp = client.submit_command("city.build", {"facilityType": "farm"})
    after = client.snapshot_state()

    finding = _check_resources_non_negative(after, "after_build")
    if finding:
        findings.append(finding)

    # Check 3: Resource conservation — compare before/after
    finding = _check_resource_change(before, after, "city.build (farm)", profile)
    if finding:
        findings.append(finding)

    # Check 4: Double-claim / idempotency check
    print("\n--- Check: Idempotency (submit same command twice) ---", file=sys.stderr)
    resp1 = client.submit_command("city.build", {"facilityType": "lumber_mill"})
    state_mid = client.snapshot_state()
    resp2 = client.submit_command("city.build", {"facilityType": "lumber_mill"})
    state_after = client.snapshot_state()

    # Compare resource states — if second build also deducted resources, that's expected
    # But if the first failed and second succeeded without cost, that's suspicious
    finding = _check_double_action(resp1, resp2, state_mid, state_after, "city.build")
    if finding:
        findings.append(finding)

    # Check 5: Troop count integrity
    print("\n--- Check: Troop count integrity ---", file=sys.stderr)
    armies = after.get('armies', {})
    finding = _check_troop_integrity(armies)
    if finding:
        findings.append(finding)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"INVARIANT SUMMARY: {len(findings)} violations found", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return findings


def _check_resources_non_negative(state, context):
    """Verify no resource value is negative."""
    city = state.get('city', {})
    data = city.get('data', city)
    if isinstance(data, dict):
        resources = data.get('resources', data.get('data', {}).get('resources', {}))
        if isinstance(resources, dict):
            for name, val in resources.items():
                if isinstance(val, (int, float)) and val < 0:
                    print(f"  ⚠️  Negative resource: {name} = {val}", file=sys.stderr)
                    return {
                        'severity': 'critical',
                        'category': 'invariant',
                        'title': f'Negative resource detected: {name} = {val}',
                        'context': context,
                        'expected': f'{name} >= 0',
                        'actual': f'{name} = {val}',
                        'impact': 'Resource underflow could indicate economy exploit',
                    }
            print(f"  ✓ All resources non-negative ({context})", file=sys.stderr)
    return None


def _check_resource_change(before, after, action, profile):
    """Check that resource changes after an action are reasonable."""
    def _get_resources(state):
        city = state.get('city', {})
        data = city.get('data', city)
        if isinstance(data, dict):
            return data.get('resources', data.get('data', {}).get('resources', {}))
        return {}

    res_before = _get_resources(before)
    res_after = _get_resources(after)

    if not res_before or not res_after:
        return None

    # Check for any resource that increased (possible duplication)
    increases = {}
    decreases = {}
    for key in set(list(res_before.keys()) + list(res_after.keys())):
        b = res_before.get(key, 0)
        a = res_after.get(key, 0)
        if isinstance(b, (int, float)) and isinstance(a, (int, float)):
            diff = a - b
            if diff > 0:
                increases[key] = diff
            elif diff < 0:
                decreases[key] = abs(diff)

    if increases and not decreases:
        # Resources increased with no cost — suspicious
        print(f"  ⚠️  Resources increased without cost: {increases}", file=sys.stderr)
        return {
            'severity': 'high',
            'category': 'invariant',
            'title': f'Free resource gain after {action}',
            'details': f'Resources increased: {increases}, no resources decreased',
            'expected': 'Actions should have a resource cost',
            'actual': f'Free resources gained: {increases}',
            'impact': 'Potential economy exploit',
        }

    if verbose := (increases or decreases):
        print(f"  ✓ Resource changes: +{increases} -{decreases}", file=sys.stderr)

    return None


def _check_double_action(resp1, resp2, state_mid, state_after, action):
    """Check if performing the same action twice has expected behavior."""
    # Both succeeded — need to check if that's valid
    s1 = resp1.get('status', 0) if resp1 else 0
    s2 = resp2.get('status', 0) if resp2 else 0

    d1 = resp1.get('data', {}) if resp1 else {}
    d2 = resp2.get('data', {}) if resp2 else {}

    cs1 = d1.get('status', '') if isinstance(d1, dict) else ''
    cs2 = d2.get('status', '') if isinstance(d2, dict) else ''

    print(f"  Cmd 1: HTTP {s1}, cmd status={cs1}", file=sys.stderr)
    print(f"  Cmd 2: HTTP {s2}, cmd status={cs2}", file=sys.stderr)

    return None  # This check is informational for now


def _check_troop_integrity(armies_state):
    """Verify troop counts are non-negative."""
    data = armies_state.get('data', armies_state)
    if isinstance(data, dict):
        army_list = data.get('armies', data.get('data', []))
    elif isinstance(data, list):
        army_list = data
    else:
        return None

    if not isinstance(army_list, list):
        return None

    for army in army_list:
        if not isinstance(army, dict):
            continue
        slots = army.get('slots', army.get('units', []))
        if isinstance(slots, list):
            for slot in slots:
                if isinstance(slot, dict):
                    count = slot.get('count', slot.get('quantity', 0))
                    if isinstance(count, (int, float)) and count < 0:
                        return {
                            'severity': 'critical',
                            'category': 'invariant',
                            'title': f"Negative troop count in army {army.get('id', '?')}",
                            'expected': 'Troop count >= 0',
                            'actual': f'count = {count}',
                            'impact': 'Troop underflow could cause game state corruption',
                        }

    print(f"  ✓ All troop counts non-negative", file=sys.stderr)
    return None


def _print_state_summary(state):
    """Print a brief summary of captured state."""
    for name, data in state.items():
        status = data.get('status', '?') if isinstance(data, dict) else '?'
        print(f"  {name}: HTTP {status}", file=sys.stderr)
