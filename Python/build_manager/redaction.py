"""Conservative child-output filtering, with synthetic credential regression tests."""
import os
import re


class Redactor:
    def __init__(self, secrets=()):
        inherited = (value for name, value in os.environ.items()
                     if re.search(r'(?:TOKEN|PASSWORD|SECRET|PRIVATE_KEY|API_KEY)$', name, re.I) and len(value) >= 8)
        self.secrets = tuple(dict.fromkeys(value for value in (*secrets, *inherited) if value))
        self.private_key = False

    def __call__(self, line):
        if '-----BEGIN ' in line and 'PRIVATE KEY-----' in line:
            self.private_key = True
            return '[private key redacted]\n'
        if self.private_key:
            if '-----END ' in line and 'PRIVATE KEY-----' in line:
                self.private_key = False
            return ''
        for secret in self.secrets:
            line = line.replace(secret, '[redacted]')
        line = re.sub(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{30,})', '[redacted]', line)
        line = re.sub(r'(?i)(authorization\s*:\s*bearer\s+|(?:api[_-]?key|token|password|secret)\s*[=:]\s*)[^\s,;]+', r'\1[redacted]', line)
        return re.sub(r'(https?://)[^/\s:@]+:[^/\s@]+@', r'\1[redacted]@', line)
