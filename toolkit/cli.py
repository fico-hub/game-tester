#!/usr/bin/env python3
"""Game Tester CLI — main entry point.

Usage:
    python3 toolkit/cli.py <command> --profile profiles/clislg.yaml [options]

Commands:
    fuzz        Boundary value fuzzing
    race        Concurrent request race condition testing
    invariants  State integrity checks
    sequence    Sequence violation testing
    auth        Authentication & permission testing
    exploit     Known exploit patterns
    report      Generate markdown report from findings
    full-run    Execute all test modules
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# Ensure toolkit package is importable
TOOLKIT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(TOOLKIT_DIR)
sys.path.insert(0, TOOLKIT_DIR)

from config import load_profile
from client import GameClient
from reporter import save_findings, generate_report


def cmd_fuzz(args, client, profile):
    from fuzzer import run
    findings = run(client, profile, endpoint_name=args.endpoint, verbose=args.verbose)
    _output(findings, 'fuzzer', profile, args)
    return findings


def cmd_race(args, client, profile):
    from racer import run
    findings = run(client, profile, threads=args.threads, verbose=args.verbose)
    _output(findings, 'racer', profile, args)
    return findings


def cmd_invariants(args, client, profile):
    from invariants import run
    findings = run(client, profile, verbose=args.verbose)
    _output(findings, 'invariants', profile, args)
    return findings


def cmd_sequence(args, client, profile):
    from sequencer import run
    findings = run(client, profile, verbose=args.verbose)
    _output(findings, 'sequencer', profile, args)
    return findings


def cmd_auth(args, client, profile):
    from auth_tester import run
    findings = run(client, profile, verbose=args.verbose)
    _output(findings, 'auth', profile, args)
    return findings


def cmd_exploit(args, client, profile):
    from exploits import run
    findings = run(client, profile, verbose=args.verbose)
    _output(findings, 'exploits', profile, args)
    return findings


def cmd_report(args, client, profile):
    findings_dir = args.findings_dir or os.path.join(SKILL_DIR, 'findings')
    report = generate_report(findings_dir)
    print(report)
    return []


def cmd_full_run(args, client, profile):
    """Execute all test modules in sequence."""
    all_findings = []
    modules = [
        ('fuzzer', cmd_fuzz),
        ('racer', cmd_race),
        ('invariants', cmd_invariants),
        ('sequencer', cmd_sequence),
        ('auth', cmd_auth),
        ('exploits', cmd_exploit),
    ]

    print(f"\n{'#'*60}", file=sys.stderr)
    print(f"# FULL TEST RUN — {profile.name}", file=sys.stderr)
    print(f"# Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", file=sys.stderr)
    print(f"{'#'*60}", file=sys.stderr)

    for name, func in modules:
        print(f"\n>>> Running module: {name} <<<", file=sys.stderr)
        try:
            findings = func(args, client, profile)
            all_findings.extend(findings)
        except Exception as e:
            print(f"ERROR in {name}: {e}", file=sys.stderr)

    # Save combined report
    findings_dir = os.path.join(SKILL_DIR, 'findings')
    save_findings(all_findings, 'full-run', profile.name, findings_dir)

    # Generate and print markdown report
    print(f"\n{'#'*60}", file=sys.stderr)
    print(f"# FULL RUN COMPLETE", file=sys.stderr)
    print(f"# Total findings: {len(all_findings)}", file=sys.stderr)
    print(f"{'#'*60}", file=sys.stderr)

    report = generate_report(findings_dir)
    print("\n<FINDINGS>")
    print(report)
    print("</FINDINGS>")

    return all_findings


def _output(findings, module, profile, args):
    """Save findings and output summary."""
    findings_dir = os.path.join(SKILL_DIR, 'findings')
    if findings:
        save_findings(findings, module, profile.name, findings_dir)

    # Print findings as JSON for agent consumption
    output = {
        'module': module,
        'game': profile.name,
        'count': len(findings),
        'findings': findings,
    }
    print(f"\n<FINDINGS>{json.dumps(output, indent=2, default=str)}</FINDINGS>")


def main():
    parser = argparse.ArgumentParser(
        prog='game-tester',
        description='Super Game Tester — AI-powered exploit hunter'
    )
    parser.add_argument('--profile', '-p', required=True, help='Path to game profile YAML/JSON')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--username', help='Use existing account username')
    parser.add_argument('--password', help='Use existing account password')

    sub = parser.add_subparsers(dest='command', required=True)

    # fuzz
    fuzz_p = sub.add_parser('fuzz', help='Boundary value fuzzing')
    fuzz_p.add_argument('--endpoint', '-e', help='Test specific endpoint only')

    # race
    race_p = sub.add_parser('race', help='Race condition testing')
    race_p.add_argument('--threads', '-t', type=int, default=10, help='Concurrent threads')

    # invariants
    sub.add_parser('invariants', help='State integrity checks')

    # sequence
    sub.add_parser('sequence', help='Sequence violation testing')

    # auth
    sub.add_parser('auth', help='Auth & permission testing')

    # exploit
    sub.add_parser('exploit', help='Known exploit patterns')

    # report
    report_p = sub.add_parser('report', help='Generate report from findings')
    report_p.add_argument('--findings-dir', '-d', help='Findings directory')

    # full-run
    full_p = sub.add_parser('full-run', help='Run all test modules')
    full_p.add_argument('--threads', '-t', type=int, default=10, help='Concurrent threads for race tests')
    full_p.add_argument('--endpoint', '-e', help='(unused, for compatibility)')
    full_p.add_argument('--findings-dir', '-d', help='(unused, for compatibility)')

    args = parser.parse_args()

    # Load profile
    profile_path = args.profile
    if not os.path.isabs(profile_path):
        profile_path = os.path.join(SKILL_DIR, profile_path)
    profile = load_profile(profile_path)

    print(f"Game: {profile.name}", file=sys.stderr)
    print(f"Base URL: {profile.base_url}", file=sys.stderr)

    # Create client and authenticate
    client = GameClient(profile)

    if args.command != 'report':
        print("Authenticating...", file=sys.stderr)
        if args.username and args.password:
            ok = client.authenticate(args.username, args.password)
        else:
            ok = client.authenticate()

        if ok:
            print(f"Authenticated as: {client.credentials['username']}", file=sys.stderr)
            print(f"Player ID: {client.player_id}", file=sys.stderr)

            # Join season (required for most games)
            print("Joining season...", file=sys.stderr)
            client.submit_command("season.join", {})
        else:
            print("WARNING: Authentication failed, some tests may be limited", file=sys.stderr)

    # Dispatch
    commands = {
        'fuzz': cmd_fuzz,
        'race': cmd_race,
        'invariants': cmd_invariants,
        'sequence': cmd_sequence,
        'auth': cmd_auth,
        'exploit': cmd_exploit,
        'report': cmd_report,
        'full-run': cmd_full_run,
    }

    func = commands.get(args.command)
    if func:
        func(args, client, profile)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
