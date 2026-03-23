"""Report generator — aggregates findings into markdown reports."""

import json
import os
import sys
from datetime import datetime


SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'info': 4}
SEVERITY_EMOJI = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🔵', 'info': '⚪'}


def save_findings(findings, module, game, output_dir):
    """Save findings to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{ts}_{module}_{game}.json"
    filepath = os.path.join(output_dir, filename)

    report = {
        'timestamp': datetime.now().isoformat(),
        'game': game,
        'module': module,
        'findings': findings,
        'summary': {
            'total': len(findings),
            'critical': sum(1 for f in findings if f.get('severity') == 'critical'),
            'high': sum(1 for f in findings if f.get('severity') == 'high'),
            'medium': sum(1 for f in findings if f.get('severity') == 'medium'),
            'low': sum(1 for f in findings if f.get('severity') == 'low'),
        }
    }

    with open(filepath, 'w') as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Findings saved to: {filepath}", file=sys.stderr)
    return filepath


def generate_report(findings_dir):
    """Aggregate all findings files and generate a markdown report."""
    all_findings = []

    if not os.path.exists(findings_dir):
        return "No findings directory found."

    for filename in sorted(os.listdir(findings_dir)):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(findings_dir, filename)
        try:
            with open(filepath) as f:
                data = json.load(f)
            for finding in data.get('findings', []):
                finding['_source'] = filename
                finding['_module'] = data.get('module', 'unknown')
                all_findings.append(finding)
        except Exception as e:
            print(f"Warning: could not load {filename}: {e}", file=sys.stderr)

    if not all_findings:
        return "No findings to report."

    # Sort by severity
    all_findings.sort(key=lambda f: SEVERITY_ORDER.get(f.get('severity', 'info'), 99))

    # Build report
    lines = []
    lines.append("# Game Tester — Bug Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Findings:** {len(all_findings)}")
    lines.append("")

    # Summary table
    by_severity = {}
    for f in all_findings:
        sev = f.get('severity', 'info')
        by_severity[sev] = by_severity.get(sev, 0) + 1

    lines.append("## Summary")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|----------|-------|")
    for sev in ['critical', 'high', 'medium', 'low', 'info']:
        count = by_severity.get(sev, 0)
        if count > 0:
            emoji = SEVERITY_EMOJI.get(sev, '')
            lines.append(f"| {emoji} {sev.upper()} | {count} |")
    lines.append("")

    # By category
    by_category = {}
    for f in all_findings:
        cat = f.get('category', 'other')
        by_category[cat] = by_category.get(cat, 0) + 1

    lines.append("| Category | Count |")
    lines.append("|----------|-------|")
    for cat, count in sorted(by_category.items()):
        lines.append(f"| {cat} | {count} |")
    lines.append("")

    # Detailed findings
    lines.append("## Findings")
    lines.append("")

    for i, f in enumerate(all_findings, 1):
        sev = f.get('severity', 'info')
        emoji = SEVERITY_EMOJI.get(sev, '')
        title = f.get('title', 'Untitled')
        lines.append(f"### {emoji} BUG-{i:03d}: {title}")
        lines.append("")
        lines.append(f"- **Severity:** {sev.upper()}")
        lines.append(f"- **Category:** {f.get('category', 'unknown')}")
        if f.get('endpoint'):
            lines.append(f"- **Endpoint:** `{f['endpoint']}`")
        if f.get('expected'):
            lines.append(f"- **Expected:** {f['expected']}")
        if f.get('actual'):
            lines.append(f"- **Actual:** {f['actual']}")
        if f.get('impact'):
            lines.append(f"- **Impact:** {f['impact']}")
        if f.get('details'):
            lines.append(f"- **Details:** {f['details']}")
        if f.get('response_status'):
            lines.append(f"- **Response Status:** {f['response_status']}")
        lines.append(f"- **Source:** {f.get('_module', '?')} ({f.get('_source', '?')})")
        lines.append("")

    return '\n'.join(lines)


def run(findings_dir):
    """Generate and print the report."""
    report = generate_report(findings_dir)
    print(report)
    return report
