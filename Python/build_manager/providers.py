"""Small provider contract; store publication is explicitly unavailable."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCapability:
    id: str
    platform: str
    artifacts: tuple[str,...]
    status: str
    reason: str
    credential_reference_kinds: tuple[str,...]=()


CAPABILITIES={
    'github':ProviderCapability('github','source',('zip',),'implemented','Project-owned release policy and explicit review apply.',('credential-helper','environment-name')),
    'testflight':ProviderCapability('testflight','ios',('ipa',),'implemented','Existing project-owned TestFlight distribution.',('protected-file',)),
    'firebase':ProviderCapability('firebase','android',('apk','aab'),'implemented','Existing Firebase App Distribution.',('firebase-cli',)),
    'app-store':ProviderCapability('app-store','ios',('ipa',),'not implemented','App Store publication is a future extension; TestFlight remains separate.'),
    'google-play':ProviderCapability('google-play','android',('aab',),'not implemented','Google Play publication is a future extension; Firebase remains separate.'),
}


def require_provider(provider):
    if not provider:return
    capability=CAPABILITIES.get(provider)
    if capability is None or capability.status!='implemented':
        raise ValueError('Provider operation is not implemented: '+provider)


def settings_rows(platforms):
    rows={}
    for key in ('app-store','google-play'):
        capability=CAPABILITIES[key]
        if capability.platform in platforms:
            rows['distribution.'+key]=dict(value='Not implemented — '+capability.reason,
                origin='provider capability contract',read_only=True,section='Future distribution')
    return rows


@dataclass(frozen=True)
class OperationReceipt:
    """Immutable reconciliation identity, never an instruction to replay effects."""
    provider: str
    operation_id: str
    destination: str
    artifact_sha256: str
    source_identity: str
    status: str


@dataclass(frozen=True)
class PreparedEffect:
    provider: str
    platform: str
    artifact: str
    artifact_sha256: str
    app_identity: str
    destination: str
    source_identity: str
    credential_references: tuple[str,...]=()


# Extension hooks are driven by current prepared artifacts, not speculative store APIs.
from typing import Protocol


class ProviderContract(Protocol):
    def preflight(self, effect: PreparedEffect) -> dict: ...
    def declare_effect(self, effect: PreparedEffect) -> PreparedEffect: ...
    def reconcile(self, operation_id: str, effect: PreparedEffect) -> OperationReceipt | None: ...
