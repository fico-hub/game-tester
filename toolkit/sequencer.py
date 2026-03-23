"""Sequence violation tester.

Tests what happens when API calls are made out of expected order,
with invalid entity IDs, or when actions are replayed.
"""

import json
import sys


def run(client, profile, verbose=False):
    """Execute sequence violation tests.

    Returns list of findings.
    """
    findings = []

    print(f"\n{'='*60}", file=sys.stderr)
    print("SEQUENCE VIOLATION TESTING", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    # Test 1: Actions before prerequisites
    print("\n--- Test: Actions before prerequisites ---", file=sys.stderr)
    prereq_tests = [
        ("army.conscript without army", "army.conscript",
         {"armyId": "fake_army_999", "slot": 0, "unitType": "infantry", "count": 10}),
        ("army.march without army", "army.march",
         {"armyId": "fake_army_999", "target": {"q": 1, "r": -1, "s": 0}}),
        ("army.disband without army", "army.disband",
         {"armyId": "fake_army_999"}),
        ("army.return without march", "army.return",
         {"armyId": "fake_army_999"}),
        ("city.upgrade without build", "city.upgrade",
         {"facilityId": "fake_facility_999"}),
    ]

    for test_name, cmd_type, payload in prereq_tests:
        resp = client.submit_command(cmd_type, payload)
        status = resp.get('status', 0) if resp else 0
        data = resp.get('data', {}) if resp else {}
        cmd_status = data.get('status', '') if isinstance(data, dict) else ''
        error = data.get('error', '') if isinstance(data, dict) else ''

        is_rejected = (
            status >= 400 or
            cmd_status in ('failed', 'rejected', 'blocked') or
            bool(error)
        )

        if not is_rejected:
            print(f"  ⚠️  {test_name}: ACCEPTED (HTTP {status}, cmd={cmd_status})", file=sys.stderr)
            findings.append({
                'severity': 'high',
                'category': 'sequence',
                'title': f'Prerequisite bypass: {test_name}',
                'endpoint': cmd_type,
                'payload': payload,
                'response_status': status,
                'cmd_status': cmd_status,
                'expected': 'Command should be rejected with invalid/nonexistent entity',
                'actual': f'Command accepted (HTTP {status}, cmd_status={cmd_status})',
                'impact': 'Players could skip game progression or affect nonexistent entities',
            })
        else:
            print(f"  ✓ {test_name}: rejected (HTTP {status}, {cmd_status or error})", file=sys.stderr)

    # Test 2: Replay completed commands
    print("\n--- Test: Replay / double execution ---", file=sys.stderr)
    resp1 = client.submit_command("city.build", {"facilityType": "iron_mine"})
    resp2 = client.submit_command("city.build", {"facilityType": "iron_mine"})

    s1 = resp1.get('status', 0) if resp1 else 0
    s2 = resp2.get('status', 0) if resp2 else 0
    print(f"  Build #1: HTTP {s1}", file=sys.stderr)
    print(f"  Build #2: HTTP {s2}", file=sys.stderr)

    # Test 3: Invalid entity ID formats
    print("\n--- Test: Invalid entity ID formats ---", file=sys.stderr)
    id_tests = [
        ("empty string", ""),
        ("numeric", 12345),
        ("SQL injection", "' OR 1=1 --"),
        ("null", None),
        ("very long", "A" * 5000),
        ("negative number string", "-1"),
        ("UUID-like", "00000000-0000-0000-0000-000000000000"),
        ("object instead", {"id": "nested"}),
    ]

    for id_name, fake_id in id_tests:
        resp = client.submit_command("army.disband", {"armyId": fake_id})
        status = resp.get('status', 0) if resp else 0
        data = resp.get('data', {}) if resp else {}

        if status == 500:
            print(f"  ⚠️  army.disband with {id_name}: SERVER ERROR 500", file=sys.stderr)
            findings.append({
                'severity': 'high',
                'category': 'sequence',
                'title': f'Server crash on invalid ID: army.disband with {id_name}',
                'endpoint': 'army.disband',
                'payload': {"armyId": str(fake_id)[:100]},
                'response_status': 500,
                'expected': 'Server should return 400 for invalid entity IDs',
                'actual': 'Server returned 500 (internal error)',
                'impact': 'Invalid input causing server errors may indicate missing validation',
            })
        elif status < 400 and status > 0:
            cmd_status = data.get('status', '') if isinstance(data, dict) else ''
            error = data.get('error', '') if isinstance(data, dict) else ''
            if cmd_status not in ('failed', 'rejected', 'blocked') and not error:
                print(f"  ⚠️  army.disband with {id_name}: ACCEPTED", file=sys.stderr)
                findings.append({
                    'severity': 'medium',
                    'category': 'sequence',
                    'title': f'Invalid ID accepted: army.disband with {id_name}',
                    'endpoint': 'army.disband',
                    'response_status': status,
                    'expected': 'Should reject invalid entity ID',
                    'actual': f'Accepted with status {status}',
                })
            else:
                print(f"  ✓ {id_name}: rejected ({cmd_status or error})", file=sys.stderr)
        else:
            print(f"  ✓ {id_name}: rejected (HTTP {status})", file=sys.stderr)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"SEQUENCE SUMMARY: {len(findings)} findings", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return findings
