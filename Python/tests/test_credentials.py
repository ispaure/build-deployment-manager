"""Credential checks for nested configuration and inherited environment values."""
import unittest
from unittest.mock import Mock, patch

from build_manager.credentials import reject_secrets


class CredentialTests(unittest.TestCase):
    def test_nested_references_use_one_environment_scan(self):
        environment = Mock(spec=dict, wraps={'FIXTURE_TOKEN': 'synthetic-credential'})
        values = {
            'auth.github_reference': 'FIXTURE_TOKEN',
            'steps': ['prepare', ('execute', {'auth.helper_reference': 'credential-helper'})],
        }
        with patch('build_manager.credentials.os.environ', environment):
            reject_secrets(values)
        environment.items.assert_called_once_with()

    def test_nested_forbidden_field_names_keep_their_error(self):
        names = ('AUTH.GitHub-Token', 'db.passwd', 'client-secret', 'signing.private-key', 'some_api_key')
        with patch('build_manager.credentials.os.environ', {}):
            for name in names:
                with self.subTest(name=name):
                    with self.assertRaisesRegex(
                        ValueError, r'^Store protected credential references, never secret values\.$'
                    ):
                        reject_secrets({'steps': [({name: 'environment-reference'},)]})

    def test_nested_credential_contents_keep_their_error(self):
        contents = (
            '-----BEGIN PRIVATE KEY-----',
            'ghp_' + 'x' * 20,
            'github_pat_' + 'x' * 20,
            'AIza' + 'x' * 30,
            'BEARER fixture',
            'https://user:fixture@example.invalid',
        )
        with patch('build_manager.credentials.os.environ', {}):
            for index, value in enumerate(contents):
                with self.subTest(pattern=index):
                    with self.assertRaisesRegex(
                        ValueError, r'^Credential contents cannot be saved; use a protected reference\.$'
                    ):
                        reject_secrets({'steps': [({'reference': value},)]})

    def test_nested_strings_reject_inherited_values_by_suffix_and_minimum_length(self):
        environment = {
            'fixture_token': 'fixture8',
            'FIXTURE_API_KEY': 'length7',
            'FIXTURE_PASSWORD_FILE': 'allowed-fixture',
        }
        with patch('build_manager.credentials.os.environ', environment):
            reject_secrets({'steps': [('length7', 'allowed-fixture')]})
            with self.assertRaisesRegex(
                ValueError, r'^An inherited credential value cannot be saved; use its environment variable name\.$'
            ):
                reject_secrets({'steps': [({'reference': 'prefix-fixture8-suffix'},)]})

    def test_separate_calls_refresh_the_environment_snapshot(self):
        environment = {'FIXTURE_SECRET': 'synthetic-previous'}
        previous = ('synthetic-previous',)
        current = ('synthetic-current',)
        with patch('build_manager.credentials.os.environ', environment):
            reject_secrets(current)
            with self.assertRaisesRegex(ValueError, 'An inherited credential value'):
                reject_secrets(previous)
            environment['FIXTURE_SECRET'] = 'synthetic-current'
            reject_secrets(previous)
            with self.assertRaisesRegex(ValueError, 'An inherited credential value'):
                reject_secrets(current)
