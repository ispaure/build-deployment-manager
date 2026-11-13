"""Manager environment policy around shared line-oriented diagnostic filtering."""
import os
import re
from commonUtils.runtime.diagnostics.redaction import LineRedactor


class Redactor(LineRedactor):
    def __init__(self, secrets=()):
        inherited = (value for name, value in os.environ.items()
                     if re.search(r'(?:TOKEN|PASSWORD|SECRET|PRIVATE_KEY|API_KEY)$', name, re.I) and len(value) >= 8)
        super().__init__((*secrets, *inherited))


class ShareRedactor(Redactor):
    """Conservative local sharing filter; arbitrary unlabeled text is not provably safe.

    Each field is a separate stream. Never pass a clipped tail of a key block.
    Ordinary retained evidence continues to use Redactor unchanged.
    """
    def text(self, value):
        self.private_key = False
        self.secrets = tuple(sorted(self.secrets, key=len, reverse=True))
        value = str(value or '')
        # Bound input before regex work; discard an incomplete boundary line.
        if len(value) > 262144:
            value = value[:262144].rsplit('\n', 1)[0] if '\n' in value[:262144] else ''
        lines = []
        for line in value.splitlines():
            line = re.sub(r'\x1b\].*?(?:\x07|\x1b\\|$)', '', line)
            line = re.sub(r'(?i)(authorization\s*[:=]\s*)(?:bearer|basic)\s+[^\s,;]+', r'\1[redacted]', line)
            # Consume quoted values before the ordinary line filter can replace
            # only their first whitespace-delimited word.
            line = re.sub(r'(?i)([\"\']?(?:password|passwd|token|secret|api[_-]?key|authorization|credential)[\"\']?\s*[:=]\s*)(?:[\"\'][^\"\']*[\"\']|\S+)', r'\1[redacted]', line)
            # Complete lines preserve private-key state before any excerpt cropping.
            line = self(line)
            if not line:
                continue
            line = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', line)
            line = re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', line)
            if re.match(r'\s*(?:[A-Z][A-Z0-9_]*\s*=|(?:command|argv|environment|cwd)\s*[:=])', line, re.I):
                lines.append('[private context omitted]')
                continue
            line = re.sub(r'(?i)\b(?:account(?:[_ -]name|[_ -]id)?|device[_ -]id|recipient|protected[_ -]file|credential[_ -]reference)\s*[:=].*', '[private identity omitted]', line)
            if re.match(r'\s{2,}(?!File [\"\']|[A-Za-z_.]*(?:Error|Exception):)\S', line):
                # Traceback source/argument lines are not needed to locate the frame.
                lines.append('[source context omitted]')
                continue
            line = re.sub(r'(?i)(--[a-z][a-z0-9_-]*(?:=|\s+))(?:[\"\'][^\"\']*[\"\']|[^\s]+)', r'\1[argument omitted]', line)
            line = re.sub(r'(?i)\b(?:env|keychain|credential|account|secret):[^\s,;]+', '[protected reference]', line)
            line = re.sub(r'\b[a-zA-Z][a-zA-Z0-9+.-]{0,31}://[^\s]+', '[url omitted]', line)
            line = re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[address omitted]', line)
            # Quoted paths may contain spaces. Unquoted paths stop at punctuation.
            line = re.sub(r'([\"\'])(?:[A-Za-z]:[\\/]|\\\\|/)[^\"\']*\1', '[path]', line)
            # An unquoted path may contain spaces; conservatively omit the rest
            # of that line rather than leak its trailing private components.
            line = re.sub(r'(?<![\w])(?:[A-Za-z]:[\\/]|\\\\|/).*', '[path]', line)
            lines.append(line)
        return '\n'.join(lines)
