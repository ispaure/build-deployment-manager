"""Maintenance requires both explicit recorded identity and the current original adapter."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from build_manager.api import ManagerAPI


class StorageMaintenanceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.row = dict(root='/fixture/project', project_id='fixture', descriptor='a' * 64)
        self.bridge = Mock(row=dict(self.row))
        self.bridge.supports_action.return_value = True
        self.bridge.call.return_value = dict(status='passed')
        self.api = ManagerAPI.__new__(ManagerAPI)
        self.api.registry = Mock()
        self.api.registry.read.return_value = dict(projects={'registration-id': self.row})
        self.plan = SimpleNamespace(adapter=dict(checkout=self.row['root'], project_id='fixture', descriptor_sha256='a' * 64))
        self.patch = patch('build_manager.bridge.ProjectBridge', return_value=self.bridge)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_stale_registration_requires_explicit_review_and_trust_without_calling_adapter(self):
        self.row['descriptor'] = 'b' * 64
        with self.assertRaisesRegex(ValueError, 'build-manager inspect registration-id.*build-manager trust registration-id'):
            self.api.storage_maintenance(self.plan)
        self.bridge.call.assert_not_called()
        self.api.registry.trust.assert_not_called()
        self.assertEqual(self.row['descriptor'], 'b' * 64)

    def test_explicitly_refreshed_original_identity_allows_declared_maintenance(self):
        self.assertEqual(self.api.storage_maintenance(self.plan), dict(status='passed'))
        self.bridge.call.assert_called_once_with('storage_maintenance', timeout=600)

    def test_current_adapter_change_is_rejected_even_if_saved_registration_matches_plan(self):
        for field in ('descriptor', 'project_id'):
            with self.subTest(field=field):
                self.bridge.row = dict(self.row, **{field: 'changed'})
                with self.assertRaisesRegex(ValueError, 'current adapter differs.*saved plan'):
                    self.api.storage_maintenance(self.plan)
        self.bridge.call.assert_not_called()
        self.api.registry.trust.assert_not_called()

    def test_refreshed_changed_identity_cannot_authorize_old_plan(self):
        self.row['descriptor'] = 'b' * 64
        self.bridge.row = dict(self.row)
        with self.assertRaisesRegex(ValueError, 'Refreshing registration cannot authorize'):
            self.api.storage_maintenance(self.plan)
        self.bridge.call.assert_not_called()
