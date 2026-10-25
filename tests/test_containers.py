"""Container plans retain normal-user and ownership protections."""
import unittest
from build_manager.containers import RootlessContainer


class ContainerTests(unittest.TestCase):
    def test_command_uses_normal_user_and_default_security(self):
        container = RootlessContainer('/var/tmp/cache', 1000, 'build-manager-fixture', 'sha256:fixture')
        argv = container.run('/var/tmp/workspace', ['python3','-c','print("literal")'])
        self.assertIn('--userns=keep-id', argv)
        self.assertIn('1000:1000', argv)
        self.assertNotIn('--privileged', argv)
        self.assertNotIn('--security-opt', argv)
        self.assertEqual(argv[-3:], ['python3','-c','print("literal")'])
        self.assertIn("get('build-manager.owner')!=name", container.cleanup_script())

    def test_root_and_unowned_containers_are_rejected(self):
        with self.assertRaises(ValueError):
            RootlessContainer('/var/tmp/cache', 0, 'build-manager-fixture', 'image')
        with self.assertRaises(ValueError):
            RootlessContainer('/var/tmp/cache',1000,'user-container','image')
