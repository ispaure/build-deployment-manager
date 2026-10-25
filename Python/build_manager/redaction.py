"""Conservative child-output filtering, with synthetic credential regression tests."""
import re


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = tuple(value for value in secrets if value)
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
        line = re.sub(r'(?i)(authorization\s*:\s*bearer\s+|(?:api[_-]?key|token|password)\s*[=:]\s*)[^\s,;]+', r'\1[redacted]', line)
        return re.sub(r'(https?://)[^/\s:@]+:[^/\s@]+@', r'\1[redacted]@', line)
