# Game Tester

AI-powered super game tester agent that systematically finds bugs, exploits, and edge cases in API-based games.

## Architecture

```
game-tester/
├── SKILL.md              # Agent persona & methodology
├── toolkit/
│   ├── cli.py            # CLI entry point
│   ├── config.py         # Game profile loader
│   ├── client.py         # HTTP client with auth & async commands
│   ├── fuzzer.py         # Boundary value fuzzing
│   ├── racer.py          # Race condition testing
│   ├── invariants.py     # State integrity checks
│   ├── sequencer.py      # Sequence violation testing
│   ├── auth_tester.py    # Auth & permission boundary tests
│   ├── exploits.py       # Known exploit patterns
│   └── reporter.py       # Report generation
├── profiles/             # Game profiles (YAML)
│   └── clislg.yaml       # CLI SLG profile
└── findings/             # Test results (JSON)
```

## Quick Start

```bash
pip3 install requests pyyaml

# Run all tests against CLI SLG
python3 toolkit/cli.py full-run --profile profiles/clislg.yaml

# Run specific module
python3 toolkit/cli.py fuzz --profile profiles/clislg.yaml
python3 toolkit/cli.py race --profile profiles/clislg.yaml
python3 toolkit/cli.py auth --profile profiles/clislg.yaml

# Generate report
python3 toolkit/cli.py report --profile profiles/clislg.yaml
```

## Test Modules

| Module | What it tests |
|--------|---------------|
| `fuzz` | Negative values, overflow, SQL injection, XSS, missing fields, type confusion |
| `race` | Duplicate commands, concurrent requests, rate limiting |
| `invariants` | Resource non-negativity, economy conservation, troop integrity |
| `sequence` | Prerequisite bypass, invalid IDs, replay attacks |
| `auth` | No-token access, malformed tokens, IDOR (cross-player access) |
| `exploit` | Negative injection, integer overflow, map boundary, prototype pollution |

## Adding a New Game

Create a YAML profile in `profiles/`. See `profiles/clislg.yaml` for the format.
