"""HTTP client wrapper with auth, async command polling, and request logging."""

import json
import time
import sys


try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

if not HAS_REQUESTS:
    print("ERROR: 'requests' package is required. Install: pip3 install requests", file=sys.stderr)
    sys.exit(1)


class GameClient:
    """HTTP client for interacting with a game API."""

    def __init__(self, profile):
        self.profile = profile
        self.session = requests.Session()
        self.session.headers['Content-Type'] = 'application/json'
        self.token = None
        self.player_id = None
        self.credentials = None
        self.request_log = []  # list of (method, url, body, status, response)

    def authenticate(self, username=None, password=None):
        """Register a new test account and login."""
        if username and password:
            self.credentials = {'username': username, 'password': password}
        else:
            self.credentials = self.profile.generate_credentials()

        auth = self.profile.auth_config

        # Register
        reg = auth.get('register', {})
        reg_url = self.profile.full_url(reg['path'])
        # Build register body from profile template + credentials
        reg_body = {}
        template = reg.get('body', {})
        for key, val in template.items():
            if val == '{{random_user}}':
                reg_body[key] = self.credentials['username']
            elif val == '{{random_pass}}':
                reg_body[key] = self.credentials['password']
            else:
                reg_body[key] = val
        if 'username' not in reg_body:
            reg_body['username'] = self.credentials['username']
        if 'password' not in reg_body:
            reg_body['password'] = self.credentials['password']
        resp = self._do_request('POST', reg_url, reg_body, auth_required=False)

        # Extract token from register response
        token_path = reg.get('token_path', 'token')
        self.token = self._extract_field(resp, token_path)
        self.player_id = self._extract_field(resp, 'playerId')

        if self.token:
            self.session.headers['Authorization'] = f"Bearer {self.token}"
            return True

        # If register didn't return token, try login
        login = auth.get('login', {})
        if login:
            login_url = self.profile.full_url(login['path'])
            resp = self._do_request('POST', login_url, reg_body, auth_required=False)
            self.token = self._extract_field(resp, token_path)
            self.player_id = self._extract_field(resp, 'playerId')
            if self.token:
                self.session.headers['Authorization'] = f"Bearer {self.token}"
                return True

        return False

    def get(self, path, auth_required=True):
        """Perform a GET request."""
        url = self.profile.full_url(path)
        return self._do_request('GET', url, auth_required=auth_required)

    def post(self, path, body=None, auth_required=True):
        """Perform a POST request."""
        url = self.profile.full_url(path)
        return self._do_request('POST', url, body, auth_required=auth_required)

    def raw_request(self, method, url, body=None, headers=None):
        """Perform a raw request with custom headers (bypasses auth)."""
        try:
            if method.upper() == 'GET':
                resp = requests.get(url, headers=headers, timeout=15)
            else:
                resp = requests.request(
                    method.upper(), url,
                    json=body, headers=headers, timeout=15
                )
            try:
                data = resp.json()
            except Exception:
                data = {'_raw': resp.text[:500]}
            self.request_log.append((method, url, body, resp.status_code, data))
            return {'status': resp.status_code, 'data': data}
        except Exception as e:
            return {'status': 0, 'error': str(e)}

    def submit_command(self, command_type, payload=None):
        """Submit a command — supports both sync (direct POST) and async (submit+poll) models."""
        # Check if this command has a direct path (sync model)
        cmd_ep = self.profile.get_command_endpoint_by_type(command_type)
        if cmd_ep and cmd_ep.get('path'):
            # Sync model: POST directly to the endpoint path
            method = cmd_ep.get('method', 'POST')
            path = cmd_ep['path']
            url = self.profile.full_url(path)
            return self._do_request(method, url, payload)

        # Async model: submit to command queue and poll
        cmd_config = self.profile.commands_config
        submit = cmd_config.get('submit', {})
        if not submit.get('path'):
            # No command infrastructure — try posting payload to a guessed path
            return self._do_request('POST', self.profile.full_url(f'/{command_type.replace(".", "/")}'), payload)

        submit_url = self.profile.full_url(submit['path'])

        body = {
            submit.get('body_key', 'type'): command_type,
            submit.get('payload_key', 'payload'): payload or {},
        }

        resp = self._do_request('POST', submit_url, body)
        if not resp or resp.get('status', 0) >= 400:
            return resp

        # Extract command ID
        id_path = cmd_config.get('poll', {}).get('id_path', 'commandId')
        cmd_id = self._extract_field(resp, id_path)
        if not cmd_id:
            return resp  # No polling possible

        if not self.profile.is_async_commands:
            return resp

        # Poll for result
        poll_config = cmd_config.get('poll', {})
        poll_path = poll_config['path'].replace('{{id}}', str(cmd_id))
        poll_url = self.profile.full_url(poll_path)
        interval = poll_config.get('poll_interval_ms', 500) / 1000.0
        max_polls = poll_config.get('max_polls', 20)
        terminal = set(poll_config.get('terminal_statuses', ['completed', 'failed']))

        for _ in range(max_polls):
            time.sleep(interval)
            poll_resp = self._do_request('GET', poll_url)
            if poll_resp:
                status = self._extract_field(poll_resp, 'status')
                if status in terminal:
                    return poll_resp
        return poll_resp

    def snapshot_state(self):
        """Capture current game state from all readable endpoints."""
        state = {}
        for ep in self.profile.read_endpoints:
            if ep.get('auth', True) and not self.token:
                continue
            try:
                resp = self.get(ep['path'], auth_required=ep.get('auth', True))
                state[ep['name']] = resp
            except Exception as e:
                state[ep['name']] = {'error': str(e)}
        return state

    def _do_request(self, method, url, body=None, auth_required=True):
        """Internal request handler."""
        try:
            if method == 'GET':
                resp = self.session.get(url, timeout=15)
            elif method == 'POST':
                resp = self.session.post(url, json=body, timeout=15)
            elif method == 'PATCH':
                resp = self.session.patch(url, json=body, timeout=15)
            elif method == 'DELETE':
                resp = self.session.delete(url, timeout=15)
            else:
                resp = self.session.request(method, url, json=body, timeout=15)

            try:
                data = resp.json()
            except Exception:
                data = {'_raw': resp.text[:500]}

            result = {'status': resp.status_code, 'data': data}
            self.request_log.append((method, url, body, resp.status_code, data))
            return result

        except Exception as e:
            result = {'status': 0, 'error': str(e)}
            self.request_log.append((method, url, body, 0, {'error': str(e)}))
            return result

    @staticmethod
    def _extract_field(resp, field_path):
        """Extract a field from response data (supports nested paths)."""
        if not resp:
            return None
        data = resp.get('data', resp)
        if isinstance(data, dict):
            # Try direct
            if field_path in data:
                return data[field_path]
            # Try nested in 'data' wrapper
            if 'data' in data and isinstance(data['data'], dict):
                return data['data'].get(field_path)
        return None
