"""Game profile loader and session state management."""

import os
import json
import random
import string

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def _random_string(length=10):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


def load_profile(path):
    """Load a game profile from YAML or JSON file."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Profile not found: {path}")

    with open(path, 'r') as f:
        raw = f.read()

    if path.endswith('.yaml') or path.endswith('.yml'):
        if not HAS_YAML:
            raise ImportError("pyyaml is required for YAML profiles. Install: pip3 install pyyaml")
        profile = yaml.safe_load(raw)
    else:
        profile = json.loads(raw)

    return Profile(profile)


class Profile:
    """Parsed game profile with convenience accessors."""

    def __init__(self, data):
        self.raw = data
        self.game = data.get('game', {})
        self.auth_config = data.get('auth', {})
        self.commands_config = data.get('commands', {})
        self.read_endpoints = data.get('read_endpoints', [])
        self.command_endpoints = data.get('command_endpoints', [])
        self.invariants = data.get('invariants', [])
        self.resources = data.get('resources', [])
        self.feedback = data.get('feedback', {})

    @property
    def name(self):
        return self.game.get('name', 'unknown')

    @property
    def base_url(self):
        return self.game.get('base_url', '').rstrip('/')

    @property
    def api_prefix(self):
        return self.game.get('api_prefix', '')

    def full_url(self, path):
        """Build full URL from a relative path."""
        return f"{self.base_url}{self.api_prefix}{path}"

    def generate_credentials(self):
        """Generate random test credentials."""
        return {
            'username': f"tester_{_random_string(8)}",
            'password': f"Test_{_random_string(12)}!",
        }

    @property
    def is_async_commands(self):
        return self.commands_config.get('async', False)

    def get_command_endpoint(self, name):
        """Find a command endpoint by name."""
        for ep in self.command_endpoints:
            if ep['name'] == name:
                return ep
        return None

    def get_command_endpoint_by_type(self, cmd_type):
        """Find a command endpoint by its type field."""
        for ep in self.command_endpoints:
            if ep.get('type') == cmd_type:
                return ep
        return None
