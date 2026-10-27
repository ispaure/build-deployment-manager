"""Manager environment policy around shared line-oriented diagnostic filtering."""
import os
import re
from commonUtils.runtime.diagnostics.redaction import LineRedactor


class Redactor(LineRedactor):
    def __init__(self, secrets=()):
        inherited = (value for name, value in os.environ.items()
                     if re.search(r'(?:TOKEN|PASSWORD|SECRET|PRIVATE_KEY|API_KEY)$', name, re.I) and len(value) >= 8)
        super().__init__((*secrets, *inherited))
