"""Firebase CLI transport; callers own installation, identities and upload approval."""
import json
from pathlib import Path
import subprocess

from .providers import ProviderOutcomeUnknown


class FirebaseError(RuntimeError):
    """The CLI did not provide a usable response; raw diagnostic output is private."""


class FirebaseCLI:
    def __init__(self, executable, workspace, *, environment=None):
        self.executable = str(executable)
        self.workspace = Path(workspace)
        self.environment = environment

    def _json(self, arguments, *, write=False):
        error = ProviderOutcomeUnknown if write else FirebaseError
        message = ('Firebase distribution outcome is unknown; reconcile the recorded attempt before retrying.'
                   if write else 'Firebase access failed; verify authentication, project access and App Distribution setup.')
        try:
            result = subprocess.run(arguments, cwd=self.workspace, env=self.environment,
                                    capture_output=True, text=True)
        except OSError:
            raise error(message) from None
        if result.returncode:
            raise error(message) from None
        try:
            response = json.loads(result.stdout)
            if response.get('status') == 'error':
                raise ValueError('Unsuccessful Firebase response')
            # appdistribution:distribute awaits upload/notes/distribution but
            # returns void (firebase-tools 15.34.0). Its explicit success
            # envelope is a completed CLI command, not a release-resource ID.
            if write and response.get('status') == 'success' and response.get('result') is None:
                return dict(cli_status='success', receipt_kind='completed-command')
            value = response['result']
            if write and (not isinstance(value, dict) or not value):
                raise ValueError('Missing operation receipt')
            return value
        except (ValueError, KeyError, TypeError, AttributeError):
            # CLI logs/responses can include credentials; do not echo them.
            raise error(message) from None

    def query(self, *arguments):
        return self._json([self.executable, *arguments, '--json', '--non-interactive'])

    def login(self, *, reauth=False):
        subprocess.run([self.executable, 'login', *(['--reauth'] if reauth else [])],
                       cwd=self.workspace, env=self.environment, check=True)

    def distribution_command(self, artifact, *, app_id, group, release_notes, json_output=False):
        return [self.executable, 'appdistribution:distribute', str(artifact), '--app', app_id,
                '--groups', group, '--release-notes-file', str(release_notes), '--non-interactive',
                *(['--json'] if json_output else [])]

    def distribute(self, artifact, *, app_id, group, release_notes, capture_result=False):
        command = self.distribution_command(artifact, app_id=app_id, group=group,
            release_notes=release_notes, json_output=capture_result)
        if capture_result:
            return self._json(command, write=True)
        try:
            subprocess.run(command, cwd=self.workspace, env=self.environment, check=True)
        except (OSError, subprocess.SubprocessError):
            raise ProviderOutcomeUnknown('Firebase distribution outcome is unknown; reconcile this operation before retrying.') from None
        return None
