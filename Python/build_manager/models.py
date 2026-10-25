"""Small serializable contracts supplied by trusted local project adapters."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Phase:
    id: str
    argv: tuple[str, ...]
    cwd: str
    timeout: float = 600
    dependencies: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    required: bool = True
    always: bool = False
    kind: str = 'test'
    artifacts: tuple[str, ...] = ()

    def __post_init__(self):
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', self.id) or not self.argv or not all(isinstance(v, str) and v for v in self.argv)
                or not self.cwd or not 0 < self.timeout <= 14400):
            raise ValueError('A phase needs a name, structured command, working directory and bounded timeout.')
        if any('\x00' in v for v in (*self.argv, self.cwd)):
            raise ValueError('Command arguments cannot contain NUL.')


@dataclass(frozen=True)
class Plan:
    project: str
    operation: str
    source: dict
    phases: tuple[Phase, ...]
    workspace: str
    backend: str = 'local'
    effect: str = 'test'
    secret_environment: tuple[str, ...] = ('GH_TOKEN', 'GITHUB_TOKEN', 'FIREBASE_TOKEN')
    resource_locks: tuple[str, ...] = ()
    schema: int = 1

    def __post_init__(self):
        if self.schema != 1:
            raise ValueError('Unsupported plan schema; keep the original and migrate explicitly.')
        if not self.project or not self.phases or self.effect not in {'inspect', 'test', 'build', 'deploy', 'upload', 'publish'}:
            raise ValueError('Invalid operation plan.')
        seen = set()
        for phase in self.phases:
            if phase.id in seen or any(dependency not in seen for dependency in phase.dependencies):
                raise ValueError('Phase IDs must be unique and dependencies must precede their consumers.')
            if any(phase.environment.get(name) for name in self.secret_environment):
                raise ValueError('Secret environment values must be inherited, not serialized in a plan.')
            seen.add(phase.id)

    def data(self):
        return asdict(self)

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(self.data(), sort_keys=True).encode()).hexdigest()

    def save(self, path):
        Path(path).write_text(json.dumps(self.data(), indent=2) + '\n')

    @classmethod
    def load(cls, path):
        # A plan is trusted executable configuration, like a local script.
        # Profiles and incoming documents never become plans automatically.
        return cls.from_data(json.loads(Path(path).read_text()))

    @classmethod
    def from_data(cls, data):
        data = dict(data)
        data['phases'] = tuple(Phase(**dict(row, argv=tuple(row['argv']),
            dependencies=tuple(row.get('dependencies', ())))) for row in data['phases'])
        return cls(**data)
