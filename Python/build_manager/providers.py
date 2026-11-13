"""Small provider contract; store publication is explicitly unavailable."""
from dataclasses import dataclass


class ProviderOutcomeUnknown(RuntimeError):
    """Reconcile the provider outcome before any manual retry; never auto-replay."""


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

DELIVERY_LABELS = {
    'testflight': 'TestFlight', 'firebase': 'Firebase', 'github': 'GitHub',
    'app-store': 'App Store', 'google-play': 'Google Play',
}


@dataclass(frozen=True)
class SettingHelp:
    text: str
    topic: str
    source: str
    url: str


APPLE_APP_INFORMATION = 'https://developer.apple.com/help/app-store-connect/reference/app-information/app-information'
APPLE_API_KEYS = 'https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api'
FIREBASE_CLI = 'https://firebase.google.com/docs/app-distribution/android/distribute-cli'
GITHUB_CREDENTIALS = 'https://docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git'

GITHUB_REFERENCE_HELP = SettingHelp(
    'For an environment reference, enter the variable name, for example GH_TOKEN. '
    'For a credential helper, use the reference configured on this computer. '
    'Manage shared references in More → Accounts. Keep the token in its credential provider.',
    'account-references', 'GitHub credential setup', GITHUB_CREDENTIALS)

PROVISIONING_HELP = SettingHelp(
    'In Apple Developer → Certificates, Identifiers & Profiles → Profiles, select the App Store Connect '
    'profile for this target’s bundle ID and team. For manual signing, choose the downloaded profile '
    'file stored outside the source checkout.',
    'apple-signing', 'Apple provisioning profiles',
    'https://developer.apple.com/help/account/provisioning-profiles/create-an-app-store-provisioning-profile')

SETTING_HELP = {
    'testflight.app_id': SettingHelp(
        'In App Store Connect, open Apps → your app → General → App Information. Copy the numeric '
        'Apple ID assigned to the app record. TestFlight uses this number to look up the app. The '
        'Bundle ID identifies the built app, the SKU is for inventory, and your Apple Account is your sign-in. '
        'API key and issuer IDs belong to authentication.',
        'testflight', 'Apple App Information reference', APPLE_APP_INFORMATION),
    'testflight.bundle_id': SettingHelp(
        'Find Bundle ID in App Store Connect → Apps → your app → General → App Information. '
        'It must match the bundle identifier in the signed build, such as com.example.app. The numeric '
        'Apple ID on the same page identifies the App Store Connect record.',
        'testflight', 'Apple App Information reference', APPLE_APP_INFORMATION),
    'testflight.external_group': SettingHelp(
        'In App Store Connect, open Apps → your app → TestFlight → External Testing. Copy the '
        'existing external group’s displayed name, such as Beta testers.',
        'testflight', 'Apple external testing groups',
        'https://developer.apple.com/help/app-store-connect/test-a-beta-version/invite-external-testers'),
    'firebase.app_id': SettingHelp(
        'In Firebase Console, select the project, then open Project settings → General → Your apps. '
        'Select the Android app with the matching package name and copy its App ID, in the form '
        '1:1234567890:android:0a1b2c3d4e5f67890. This is the App Distribution --app value. '
        'Firebase lists the project ID, Android package name and API key separately.',
        'firebase', 'Firebase App Distribution CLI', FIREBASE_CLI),
    'firebase.bundle_id': SettingHelp(
        'In Firebase Console → Project settings → General → Your apps, select the Android app. '
        'Its package name, such as com.example.app, must match the Android build. The Firebase App ID '
        'on the same card is the separate App Distribution --app value.',
        'firebase', 'Register an Android app in Firebase', 'https://firebase.google.com/docs/android/setup'),
    'firebase.group': SettingHelp(
        'In Firebase Console → App Distribution → Testers & Groups, open the existing group and '
        'copy its group alias, such as qa-team. This identifies the recipient group for the release.',
        'firebase', 'Firebase tester group aliases', FIREBASE_CLI),
    'github.repository': SettingHelp(
        'Open the destination repository on GitHub and copy the owner and repository name in the '
        'form owner/repository. The project uses this destination for its release or hosted checks.',
        'github', 'GitHub repository reference', 'https://docs.github.com/en/rest/repos/repos#get-a-repository'),
    'github.workflow': SettingHelp(
        'In the destination repository, open .github/workflows and copy the workflow filename, '
        'including .yml or .yaml. The Actions tab can show a different display name.',
        'github', 'GitHub Actions workflow files',
        'https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax'),
    'github.credentials': SettingHelp(
        'Find the hosted workflow’s credentials in the repository’s Settings → Secrets and variables → Actions. '
        'Use the names required by the workflow. Local account references stay on this computer.',
        'github', 'GitHub Actions secrets',
        'https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets'),
    'github.authentication': GITHUB_REFERENCE_HELP,
    'github.token_environment': GITHUB_REFERENCE_HELP,
    'auth.github_reference': GITHUB_REFERENCE_HELP,
    'auth.github_kind': GITHUB_REFERENCE_HELP,
    'auth.testflight_reference': SettingHelp(
        'Choose the existing local authentication JSON created by your project’s App Store Connect setup. '
        'Apple lists API key details under Users and Access → Integrations. Store the JSON and key '
        'in a protected location outside the checkout and select the JSON path here.',
        'account-references', 'Apple App Store Connect API keys', APPLE_API_KEYS),
    'auth.key_reference': SettingHelp(
        'Find App Store Connect API keys under Users and Access → Integrations. Select the path '
        'to the existing downloaded .p8 key in protected storage outside the checkout.',
        'account-references', 'Apple App Store Connect API keys', APPLE_API_KEYS),
}


def setting_help(name):
    if name.startswith('signing.') and name.endswith('_profile'):
        return PROVISIONING_HELP
    return SETTING_HELP.get(name)


def require_provider(provider):
    if not provider:return
    capability=CAPABILITIES.get(provider)
    if capability is None or capability.status!='implemented':
        raise ValueError('Provider operation is not implemented: '+provider)


def unimplemented_distribution_rows(platforms):
    rows={}
    for key in ('app-store','google-play'):
        capability=CAPABILITIES[key]
        if capability.platform in platforms:
            rows['distribution.'+key]=dict(value='Not implemented — '+capability.reason,
                origin='provider capability contract',read_only=True,section='Future distribution',
                label='App Store publication' if key=='app-store' else 'Google Play publication',description=capability.reason)
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


settings_rows = unimplemented_distribution_rows  # Compatibility for project adapters.
