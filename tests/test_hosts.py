"""Unsupported stores fail before credentials/transport; host policy is explicit."""
import unittest
from build_manager.hosts import capabilities,android_abi


class HostCapabilityTests(unittest.TestCase):
    def test_host_policy_never_silently_uses_remote_fallback(self):
        targets=('macos','linux','windows','android','ios')
        for system,native in [('Darwin','macos'),('Linux','linux'),('Windows','windows')]:
            rows=capabilities(targets,system=system,ready=(native,),hosted=('ios',),unavailable={'android':'SDK missing'})
            local={r['target']:r for r in rows if r['location']=='local'}
            self.assertEqual(local[native]['status'],'ready')
            self.assertEqual(local['android']['status'],'unavailable')
            if system!='Darwin':self.assertEqual(local['ios']['status'],'unsupported')
            self.assertEqual([r for r in rows if r['location']=='hosted'][0]['status'],'unconfigured')
        self.assertEqual(android_abi('AMD64'),'x86_64');self.assertEqual(android_abi('aarch64'),'arm64-v8a')
        with self.assertRaises(ValueError):android_abi('unknown')

    def test_android_host_binary_support_is_distinct_from_guest_image_abi(self):
        from build_manager.hosts import android_host_issue
        for system in ('Linux', 'Windows'):
            for architecture in ('arm64', 'aarch64'):
                with self.subTest(system=system, architecture=architecture):
                    self.assertIn('host binary', android_host_issue(system, architecture))
                    rows = capabilities(('android',), system=system, architecture=architecture, ready=('android',), hosted=('android',))
                    self.assertEqual(rows[0]['status'], 'unavailable')
                    self.assertEqual(rows[1]['status'], 'unconfigured')
        for system, architecture in (('Darwin','arm64'), ('Darwin','x86_64'), ('Linux','x86_64'), ('Windows','AMD64')):
            self.assertIsNone(android_host_issue(system, architecture))
            self.assertEqual(capabilities(('android',),system=system,architecture=architecture)[0]['status'], 'unconfigured')
        self.assertEqual(android_abi('arm64'), 'arm64-v8a')
