"""Small serializable contracts supplied by trusted local project adapters."""
from dataclasses import asdict, dataclass, field
import hashlib
import json
import os
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
    effect: str = 'inherit'
    resources: dict[str, int] = field(default_factory=dict)
    artifact_types: dict[str, str] = field(default_factory=dict)
    provider: str = ''
    stop_grace: float = 1

    def __post_init__(self):
        from .providers import require_provider
        require_provider(self.provider)
        if self.effect not in {'inherit','inspect','test','build','deploy','upload','publish'}:
            raise ValueError('Unsupported step effect.')
        if any(not isinstance(name,str) or not name or type(amount) is not int or amount<1 for name,amount in self.resources.items()):
            raise ValueError('Invalid step resources.')
        if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', self.id) or not self.argv or not all(isinstance(v, str) and v for v in self.argv)
                or not self.cwd or not 0 < self.timeout <= 14400 or not 0 < self.stop_grace <= 300):
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
    max_workers: int = 1
    capacities: dict[str, int] = field(default_factory=dict)
    resources: dict[str, int] = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    adapter: dict = field(default_factory=dict)
    journey: dict = field(default_factory=dict)

    def __post_init__(self):
        if not all(isinstance(value,dict) for value in (self.source,self.settings,self.adapter,self.resources,self.capacities,self.journey)):
            raise ValueError('Source, settings, adapter and resource data must be objects.')
        if type(self.max_workers) is not int or not 1<=self.max_workers<=16:
            raise ValueError('Choose 1–16 bounded workers.')
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
        if self.journey:
            from .journeys import validate_plan
            validate_plan(self)

    def data(self):
        data = asdict(self)
        # Preserve pre-journey plan hashes so retained legacy runs still resume.
        if not self.journey:
            data.pop('journey')
        return data

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(self.data(), sort_keys=True).encode()).hexdigest()

    def save(self, path):
        from .credentials import reject_secrets
        reject_secrets(self.data())
        encoded = json.dumps(self.data(), indent=2) + '\n'
        if any(os.environ.get(name) and os.environ[name] in encoded for name in self.secret_environment):
            raise ValueError('Plan data contains an inherited secret; use protected credential references.')
        from .profiles import save_json
        save_json(path, self.data())

    @classmethod
    def load(cls, path):
        # A plan is trusted executable configuration, like a local script.
        # Profiles and incoming documents never become plans automatically.
        return cls.from_data(json.loads(Path(path).read_text()))

    @classmethod
    def from_data(cls, data):
        try:
            if not isinstance(data,dict) or not isinstance(data.get('phases'),(list,tuple)):
                raise ValueError('Plan must be an object with structured phases.')
            data=dict(data)
            phases=[]
            for row in data['phases']:
                if not isinstance(row,dict) or not isinstance(row.get('argv'),(list,tuple)):
                    raise ValueError('Plan commands must be argument lists, never shell strings.')
                phases.append(Phase(**dict(row,argv=tuple(row['argv']),dependencies=tuple(row.get('dependencies',())))))
            data['phases']=tuple(phases)
            return cls(**data)
        except (TypeError,KeyError) as error:
            raise ValueError('Invalid or unsupported plan fields; preserve the original and inspect a new plan.') from error
