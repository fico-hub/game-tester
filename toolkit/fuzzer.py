"""Boundary value and input fuzzing module.

For each field in a command's payload schema, generates edge-case inputs
and records whether the server accepted or rejected them.
"""

import json
import sys


# Fuzz value generators by type
FUZZ_VALUES = {
    'integer': [
        ('zero', 0),
        ('negative_one', -1),
        ('negative_large', -999999),
        ('max_int32', 2147483647),
        ('max_int32_plus1', 2147483648),
        ('min_int32', -2147483648),
        ('float', 1.5),
        ('string_instead', "abc"),
        ('null', None),
        ('bool_instead', True),
        ('empty_string', ""),
        ('very_large', 999999999999),
    ],
    'string': [
        ('empty', ""),
        ('null', None),
        ('number_instead', 42),
        ('very_long', "A" * 10000),
        ('sql_injection', "' OR 1=1 --"),
        ('xss', "<script>alert(1)</script>"),
        ('null_byte', "test\x00evil"),
        ('unicode', "テスト🎮"),
        ('spaces_only', "   "),
        ('special_chars', "!@#$%^&*()"),
        ('path_traversal', "../../../etc/passwd"),
        ('json_injection', '{"injected": true}'),
    ],
    'boolean': [
        ('null', None),
        ('string_true', "true"),
        ('string_false', "false"),
        ('number_one', 1),
        ('number_zero', 0),
        ('empty_string', ""),
    ],
    'array': [
        ('empty', []),
        ('null', None),
        ('string_instead', "not_array"),
        ('huge', list(range(1000))),
        ('nested', [[[]]]),
        ('mixed_types', [1, "two", True, None, [], {}]),
    ],
    'object': [
        ('empty', {}),
        ('null', None),
        ('string_instead', "not_object"),
        ('array_instead', []),
        ('nested_deep', {"a": {"b": {"c": {"d": {"e": "deep"}}}}}),
    ],
}

# Additional fuzz values for enum fields
def fuzz_enum(valid_values):
    """Generate fuzz values for enum-constrained fields."""
    cases = [
        ('empty', ""),
        ('null', None),
        ('number_instead', 42),
        ('invalid_value', "DEFINITELY_NOT_VALID"),
        ('case_mismatch', valid_values[0].upper() if valid_values else "X"),
        ('with_spaces', f" {valid_values[0]} " if valid_values else " "),
    ]
    return cases


def generate_fuzz_cases(endpoint):
    """Generate all fuzz test cases for a command endpoint."""
    schema = endpoint.get('payload_schema', {})
    cases = []

    for field_name, field_def in schema.items():
        field_type = field_def.get('type', 'string')
        enum_values = field_def.get('enum', [])

        # Get base fuzz values for this type
        type_values = FUZZ_VALUES.get(field_type, FUZZ_VALUES['string'])

        # Add enum-specific fuzz values
        if enum_values:
            type_values = type_values + fuzz_enum(enum_values)

        for case_name, fuzz_value in type_values:
            # Build a payload with the fuzzed field and valid defaults for others
            payload = _build_payload_with_fuzz(schema, field_name, fuzz_value)
            cases.append({
                'field': field_name,
                'case': case_name,
                'value': fuzz_value,
                'payload': payload,
            })

    # Also test: missing required fields
    for field_name, field_def in schema.items():
        if field_def.get('required', False):
            payload = _build_payload_without(schema, field_name)
            cases.append({
                'field': field_name,
                'case': 'missing_required',
                'value': '<MISSING>',
                'payload': payload,
            })

    # Test: completely empty payload
    cases.append({
        'field': '_all',
        'case': 'empty_payload',
        'value': {},
        'payload': {},
    })

    # Test: extra unknown fields
    valid_payload = _build_default_payload(schema)
    valid_payload['_unknown_field'] = "injected"
    valid_payload['__proto__'] = {"polluted": True}
    cases.append({
        'field': '_extra',
        'case': 'extra_fields',
        'value': 'injected',
        'payload': valid_payload,
    })

    return cases


def _build_default_payload(schema):
    """Build a payload with sensible default values for all fields."""
    payload = {}
    for name, field_def in schema.items():
        ft = field_def.get('type', 'string')
        enum = field_def.get('enum', [])
        if enum:
            payload[name] = enum[0]
        elif ft == 'integer':
            payload[name] = field_def.get('min', 1)
        elif ft == 'string':
            payload[name] = "test_value"
        elif ft == 'boolean':
            payload[name] = True
        elif ft == 'array':
            payload[name] = []
        elif ft == 'object':
            payload[name] = {}
    return payload


def _build_payload_with_fuzz(schema, fuzz_field, fuzz_value):
    """Build payload with default values, replacing one field with fuzz value."""
    payload = _build_default_payload(schema)
    if fuzz_value is None:
        payload[fuzz_field] = None
    else:
        payload[fuzz_field] = fuzz_value
    return payload


def _build_payload_without(schema, exclude_field):
    """Build payload with all fields except the excluded one."""
    payload = _build_default_payload(schema)
    payload.pop(exclude_field, None)
    return payload


def run(client, profile, endpoint_name=None, verbose=False):
    """Execute fuzzing tests against command endpoints.

    Returns list of findings (potential bugs).
    """
    findings = []
    endpoints = profile.command_endpoints

    if endpoint_name:
        endpoints = [ep for ep in endpoints if ep['name'] == endpoint_name]
        if not endpoints:
            print(f"ERROR: Endpoint '{endpoint_name}' not found", file=sys.stderr)
            return findings

    total_tests = 0
    total_suspicious = 0

    for ep in endpoints:
        ep_name = ep['name']
        cmd_type = ep['type']
        cases = generate_fuzz_cases(ep)

        if not cases:
            continue

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"FUZZING: {ep_name} ({cmd_type}) — {len(cases)} cases", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        for case in cases:
            total_tests += 1
            field = case['field']
            case_name = case['case']
            payload = case['payload']

            try:
                resp = client.submit_command(cmd_type, payload)
            except Exception as e:
                resp = {'status': 0, 'error': str(e)}

            status = resp.get('status', 0) if resp else 0
            is_error = status >= 400 or status == 0
            cmd_status = None
            if resp and 'data' in resp:
                cmd_status = resp['data'].get('status')

            # Determine if this is suspicious
            suspicious = False
            severity = 'info'
            reason = ''

            if not is_error and case_name in ('negative_one', 'negative_large', 'min_int32'):
                suspicious = True
                severity = 'high'
                reason = f"Server accepted negative value ({case['value']}) for {field}"

            elif not is_error and case_name in ('max_int32_plus1', 'very_large'):
                suspicious = True
                severity = 'medium'
                reason = f"Server accepted overflow value ({case['value']}) for {field}"

            elif not is_error and case_name == 'sql_injection':
                suspicious = True
                severity = 'critical'
                reason = f"Server accepted SQL injection string for {field}"

            elif not is_error and case_name == 'xss':
                suspicious = True
                severity = 'high'
                reason = f"Server accepted XSS payload for {field}"

            elif not is_error and case_name == 'missing_required':
                suspicious = True
                severity = 'medium'
                reason = f"Server accepted request without required field {field}"

            elif not is_error and case_name in ('null', 'empty'):
                # Accepting null/empty for required fields is suspicious
                field_def = ep.get('payload_schema', {}).get(field, {})
                if field_def.get('required', False):
                    suspicious = True
                    severity = 'medium'
                    reason = f"Server accepted null/empty for required field {field}"

            elif status == 500:
                suspicious = True
                severity = 'high'
                reason = f"Server crashed (500) on fuzz input for {field} ({case_name})"

            elif status == 0:
                suspicious = True
                severity = 'medium'
                reason = f"Server timeout/connection error on {field} ({case_name})"

            # Log
            marker = "⚠️ " if suspicious else "  "
            if verbose or suspicious:
                print(f"{marker}[{status}] {field}.{case_name} = {_truncate(case['value'])}", file=sys.stderr)

            if suspicious:
                total_suspicious += 1
                findings.append({
                    'severity': severity,
                    'category': 'boundary',
                    'title': reason,
                    'endpoint': f"{cmd_type}",
                    'field': field,
                    'fuzz_case': case_name,
                    'fuzz_value': _safe_serialize(case['value']),
                    'request_payload': _safe_serialize(payload),
                    'response_status': status,
                    'response_body': _safe_serialize(resp.get('data', {}) if resp else {}),
                    'expected': f"Server should reject invalid input for {field}",
                    'actual': reason,
                })

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"FUZZ SUMMARY: {total_tests} tests, {total_suspicious} suspicious", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    return findings


def _truncate(val, max_len=80):
    s = str(val)
    return s[:max_len] + '...' if len(s) > max_len else s


def _safe_serialize(val):
    try:
        json.dumps(val)
        return val
    except (TypeError, ValueError):
        return str(val)
