"""Authentication and permission boundary tester.

Tests: unauthenticated access, token manipulation, cross-player access (IDOR).
"""

import json
import sys


def run(client, profile, verbose=False):
    """Execute authentication and authorization tests.

    Returns list of findings.
    """
    findings = []

    print(f"\n{'='*60}", file=sys.stderr)
    print("AUTHENTICATION & PERMISSION TESTING", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    base = profile.full_url("")

    # Test 1: Access authenticated endpoints without token
    print("\n--- Test: No-token access to auth-required endpoints ---", file=sys.stderr)
    for ep in profile.read_endpoints:
        if not ep.get('auth', True):
            continue
        url = profile.full_url(ep['path'])
        resp = client.raw_request('GET', url, headers={'Content-Type': 'application/json'})
        status = resp.get('status', 0)

        if 200 <= status < 300:
            print(f"  ⚠️  {ep['name']}: accessible without token (HTTP {status})", file=sys.stderr)
            findings.append({
                'severity': 'critical',
                'category': 'auth',
                'title': f'Unauthenticated access to {ep["name"]}',
                'endpoint': f'GET {ep["path"]}',
                'response_status': status,
                'expected': '401 or 403 without valid token',
                'actual': f'HTTP {status} — data accessible',
                'impact': 'Any unauthenticated user can read game state',
            })
        else:
            print(f"  ✓ {ep['name']}: blocked (HTTP {status})", file=sys.stderr)

    # Test 2: Submit commands without token
    print("\n--- Test: No-token command submission ---", file=sys.stderr)
    cmd_url = profile.full_url(profile.commands_config.get('submit', {}).get('path', '/commands'))
    resp = client.raw_request('POST', cmd_url,
                               body={"type": "city.build", "payload": {"facilityType": "farm"}},
                               headers={'Content-Type': 'application/json'})
    status = resp.get('status', 0)
    if 200 <= status < 300:
        print(f"  ⚠️  Command accepted without token (HTTP {status})", file=sys.stderr)
        findings.append({
            'severity': 'critical',
            'category': 'auth',
            'title': 'Commands accepted without authentication',
            'endpoint': f'POST {cmd_url}',
            'response_status': status,
            'expected': '401 without token',
            'actual': f'HTTP {status} — command accepted',
            'impact': 'Anyone can execute game actions without logging in',
        })
    else:
        print(f"  ✓ Command blocked without token (HTTP {status})", file=sys.stderr)

    # Test 3: Malformed tokens
    print("\n--- Test: Malformed tokens ---", file=sys.stderr)
    malformed_tokens = [
        ("empty", ""),
        ("garbage", "not_a_real_token_12345"),
        ("bearer_only", "Bearer"),
        ("null_string", "null"),
        ("truncated", client.token[:10] if client.token else "abc"),
        ("modified_char", _flip_char(client.token) if client.token else "abc"),
        ("expired_format", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjF9.fake"),
    ]

    for name, token in malformed_tokens:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        }
        resp = client.raw_request('GET', profile.full_url('/city'), headers=headers)
        status = resp.get('status', 0)

        if 200 <= status < 300:
            print(f"  ⚠️  {name} token: accepted (HTTP {status})", file=sys.stderr)
            findings.append({
                'severity': 'critical',
                'category': 'auth',
                'title': f'Malformed token accepted: {name}',
                'endpoint': 'GET /city',
                'token_type': name,
                'response_status': status,
                'expected': '401 for malformed token',
                'actual': f'HTTP {status} — request accepted',
                'impact': 'Token validation is insufficient, enabling unauthorized access',
            })
        else:
            print(f"  ✓ {name} token: rejected (HTTP {status})", file=sys.stderr)

    # Test 4: Cross-player access (IDOR)
    print("\n--- Test: Cross-player access (IDOR) ---", file=sys.stderr)
    # Register a second account
    second_client = _create_second_client(client, profile)
    if second_client:
        # Try to access first player's data with second player's token
        first_state = client.snapshot_state()
        armies = first_state.get('armies', {})
        army_data = armies.get('data', {})
        army_list = _extract_army_list(army_data)

        if army_list:
            army_id = army_list[0].get('id') or army_list[0].get('armyId')
            if army_id:
                # Second player tries to disband first player's army
                resp = second_client.submit_command("army.disband", {"armyId": army_id})
                status = resp.get('status', 0) if resp else 0
                data = resp.get('data', {}) if resp else {}
                cmd_status = data.get('status', '') if isinstance(data, dict) else ''
                error = data.get('error', '') if isinstance(data, dict) else ''

                is_blocked = (
                    status >= 400 or
                    cmd_status in ('failed', 'rejected', 'blocked') or
                    bool(error)
                )

                if not is_blocked:
                    print(f"  ⚠️  IDOR: Player B can disband Player A's army!", file=sys.stderr)
                    findings.append({
                        'severity': 'critical',
                        'category': 'auth',
                        'title': 'IDOR: Cross-player army manipulation',
                        'endpoint': 'army.disband',
                        'details': f'Player B successfully disbands Player A army {army_id}',
                        'expected': 'Server should verify ownership before executing',
                        'actual': 'Command executed on another player\'s entity',
                        'impact': 'Any player can manipulate other players\' armies',
                    })
                else:
                    print(f"  ✓ IDOR blocked: cannot disband other player's army", file=sys.stderr)
        else:
            print(f"  (skipped: no armies to test IDOR against)", file=sys.stderr)
    else:
        print(f"  (skipped: could not create second account)", file=sys.stderr)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"AUTH SUMMARY: {len(findings)} findings", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return findings


def _flip_char(s):
    """Change one character in a string to test token validation."""
    if not s or len(s) < 5:
        return s
    chars = list(s)
    idx = len(s) // 2
    chars[idx] = 'X' if chars[idx] != 'X' else 'Y'
    return ''.join(chars)


def _create_second_client(first_client, profile):
    """Register and authenticate a second test account."""
    from client import GameClient
    try:
        second = GameClient(profile)
        if second.authenticate():
            return second
    except Exception as e:
        print(f"  (second account creation failed: {e})", file=sys.stderr)
    return None


def _extract_army_list(army_data):
    if isinstance(army_data, list):
        return army_data
    if isinstance(army_data, dict):
        for key in ('armies', 'data', 'items'):
            val = army_data.get(key)
            if isinstance(val, list):
                return val
    return []
