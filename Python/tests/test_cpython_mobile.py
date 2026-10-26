"""Portable CPython cache/compiler contracts; no native SDK or device required."""
import io
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from build_manager import cpython_mobile as runtime
from build_manager import cpython_testbed as testbed


class CacheTests(unittest.TestCase):
    def archive(self, root):
        archive = root / 'cpython-fixture.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            info = tarfile.TarInfo('cpython-fixture/README')
            info.size = len(b'upstream')
            stream.addfile(info, io.BytesIO(b'upstream'))
        return archive, dict(revision='fixture', sha256=runtime.checksum(archive), archive='https://example.invalid/source')

    def test_source_reuses_verified_archive_and_rejects_changed_upstream_members(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive, pin = self.archive(root)
            cache = root / 'source'
            with patch.object(runtime.urllib.request, 'urlopen', side_effect=AssertionError('offline')):
                runtime.source(cache, pin)
                (cache / 'cross-build').mkdir()
                (cache / 'cross-build/generated').write_bytes(b'generated')
                runtime.source(cache, pin)
                (cache / 'README').write_bytes(b'modified')
                with self.assertRaisesRegex(ValueError, 'source cache changed'):
                    runtime.source(cache, pin)
                archive.write_bytes(b'corrupt')
                with self.assertRaisesRegex(ValueError, 'archive digest differs'):
                    runtime.source(cache, pin)

    def test_downloaded_archive_is_checked_before_extraction(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive, pin = self.archive(root)
            content = archive.read_bytes()
            archive.unlink()
            with patch.object(runtime.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')):
                with self.assertRaisesRegex(ValueError, 'archive digest mismatch'):
                    runtime.source(root / 'source', pin)
            self.assertFalse(archive.exists())
            self.assertFalse((root / 'source').exists())
            self.assertFalse(archive.with_suffix('.download').exists())
            with patch.object(runtime.urllib.request, 'urlopen', return_value=io.BytesIO(content)):
                runtime.source(root / 'source', pin)
            self.assertEqual((root / 'source/README').read_bytes(), b'upstream')

    def test_wheels_require_preparation_and_never_redownload_changed_cache(self):
        import hashlib
        with TemporaryDirectory() as directory:
            cache = Path(directory)
            pin = dict(filename='fixture.whl', sha256=hashlib.sha256(b'wheel').hexdigest(), url='https://example.invalid/wheel')
            with patch.object(runtime.urllib.request, 'urlopen') as network:
                with self.assertRaisesRegex(ValueError, 'Prepare'):
                    runtime.runtime_wheels(cache, [pin])
                network.assert_not_called()
            with patch.object(runtime.urllib.request, 'urlopen', return_value=io.BytesIO(b'wrong')):
                with self.assertRaisesRegex(ValueError, 'download digest differs'):
                    runtime.runtime_wheels(cache, [pin], download=True)
            with patch.object(runtime.urllib.request, 'urlopen', return_value=io.BytesIO(b'wheel')):
                folder = runtime.runtime_wheels(cache, [pin], download=True)
            (folder / 'fixture.whl').write_bytes(b'changed')
            with patch.object(runtime.urllib.request, 'urlopen') as network:
                with self.assertRaisesRegex(ValueError, 'Prepare'):
                    runtime.runtime_wheels(cache, [pin], download=True)
                network.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'single filename'):
                runtime.runtime_wheels(cache, [dict(pin, filename='../escape')], download=True)


class CompilerTests(unittest.TestCase):
    def fixture(self, cache):
        pin = dict(revision='fixture', version='3.14.7', sha256='a'*64, android_target='fixture-android')
        host = cache / 'cross-build/build/python.exe'
        host.parent.mkdir(parents=True)
        host.write_bytes(b'host')
        host.chmod(0o700)
        return pin, host

    def test_android_preserves_receipt_and_refuses_mismatched_pin_without_rebuild(self):
        with TemporaryDirectory() as directory:
            cache = Path(directory) / 'cache'
            pin, host = self.fixture(cache)
            library = cache / 'library.so'
            library.write_bytes(b'library')
            result = cache.parent / 'result.json'
            command = Mock(side_effect=AssertionError('must reuse existing artifacts'))
            options = dict(library_relative='library.so', host_configure_args=['--caller-option'], command=command,
                           prepare_source=Mock(), prepare_wheels=Mock())
            with patch.object(runtime.subprocess, 'check_output', return_value=pin['version']):
                runtime.prepare_android(cache, result, pin, **options)
                saved = json.loads(result.read_text())
                self.assertEqual(saved['host_sha256'], runtime.checksum(host))
                runtime.prepare_android(cache, result, pin, **options)
                self.assertTrue(json.loads(result.read_text())['reused'])
                with self.assertRaisesRegex(ValueError, 'artifacts changed'):
                    runtime.prepare_android(cache, result, dict(pin, sha256='b'*64), **options)
            command.assert_not_called()

    def test_ios_uses_caller_target_and_reuses_only_matching_toolchain_and_framework(self):
        with TemporaryDirectory() as directory:
            cache = Path(directory) / 'cache'
            pin, host = self.fixture(cache)
            framework = cache / 'caller-framework'
            library = framework / 'Python'
            downloads = cache / 'cross-build/downloads'
            downloads.mkdir()
            (downloads / 'dependency.tar.gz').write_bytes(b'dependency')
            def command(argv, cwd, timeout):
                self.assertEqual(argv[-1], 'caller-ios-target')
                self.assertEqual(cwd, cache)
                framework.mkdir()
                library.write_bytes(b'framework')
            options = dict(target='caller-ios-target', framework_relative='caller-framework',
                           host_configure_args=['--caller-option'], command=Mock(side_effect=command),
                           prepare_source=Mock(), prepare_wheels=Mock(),
                           tree_digest=lambda folder: runtime.checksum(folder / 'Python'),
                           current_toolchain=Mock(return_value={'sdk': 'fixture'}))
            result = cache.parent / 'result.json'
            with patch.object(runtime.subprocess, 'check_output', return_value=pin['version']):
                runtime.prepare_ios(cache, result, pin, **options)
                saved = json.loads(result.read_text())
                self.assertEqual(saved['dependencies']['dependency.tar.gz'], runtime.checksum(downloads / 'dependency.tar.gz'))
                runtime.prepare_ios(cache, result, pin, **options)
                self.assertTrue(json.loads(result.read_text())['reused'])
                options['current_toolchain'].return_value = {'sdk': 'changed'}
                with self.assertRaisesRegex(ValueError, 'runtime differs'):
                    runtime.prepare_ios(cache, result, pin, **options)
                options['current_toolchain'].return_value = {'sdk': 'fixture'}
                library.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'runtime differs'):
                    runtime.prepare_ios(cache, result, pin, **options)
            self.assertEqual(options['command'].call_count, 1)

    @unittest.skipIf(os.name == 'nt', 'macOS compiler environment uses symlinks')
    def test_cold_ios_build_keeps_target_after_resolving_compiler_links(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / 'cache'
            cache.mkdir()
            pin = dict(revision='fixture', version='3.14.7', sha256='a'*64)
            host = cache / 'cross-build/build/python.exe'
            framework = cache / 'caller-framework'
            commands = []
            def command(argv, cwd, timeout):
                commands.append(argv)
                if argv[4] == 'build':
                    self.assertEqual(argv[-1], '--caller-openssl')
                    host.parent.mkdir(parents=True)
                    host.write_bytes(b'host')
                else:
                    self.assertEqual(argv[4], 'caller-ios-target')
                    framework.mkdir()
                    (framework / 'Python').write_bytes(b'framework')
                    (cache / 'cross-build/downloads').mkdir()
            def query(argv, **kwargs):
                return str(root / 'sdk') if argv[0] == 'xcrun' else pin['version']
            with patch.dict(os.environ, DEVELOPER_DIR=str(root / 'developer')), patch.object(
                    runtime.subprocess, 'check_output', side_effect=query):
                before = dict(os.environ)
                runtime.prepare_ios(cache, root / 'result.json', pin, target='caller-ios-target',
                    framework_relative='caller-framework', host_configure_args=['--caller-openssl'],
                    command=command, prepare_source=Mock(), prepare_wheels=Mock(),
                    tree_digest=lambda folder: runtime.checksum(folder / 'Python'), current_toolchain=lambda: {})
                self.assertEqual(dict(os.environ), before)
            self.assertEqual(len(commands), 2)

    @unittest.skipIf(os.name == 'nt', 'macOS compiler environment uses symlinks')
    def test_compiler_cancel_restores_environment_and_writes_no_receipt(self):
        for platform in ('android', 'ios'):
            with self.subTest(platform=platform), TemporaryDirectory() as directory:
                cache = Path(directory) / 'cache'
                cache.mkdir()
                sdk, developer = cache.parent / 'sdk', cache.parent / 'developer'
                sdk.mkdir()
                (developer / 'Toolchains/XcodeDefault.xctoolchain').mkdir(parents=True)
                result = cache.parent / 'result.json'
                pin = dict(revision='fixture', version='3.14.7', sha256='a'*64, android_target='fixture-android')
                def command(argv, cwd, timeout):
                    self.assertEqual(argv[-1], '--caller-openssl')
                    self.assertEqual(os.environ['SDKROOT'], str(cache / 'macos-sdk'))
                    raise KeyboardInterrupt
                options = dict(host_configure_args=['--caller-openssl'], command=command,
                               prepare_source=Mock(), prepare_wheels=Mock())
                with patch.dict(os.environ, DEVELOPER_DIR=str(developer)), patch.object(
                        runtime.subprocess, 'check_output', return_value=str(sdk)):
                    original = dict(os.environ)
                    with self.assertRaises(KeyboardInterrupt):
                        if platform == 'android':
                            runtime.prepare_android(cache, result, pin, library_relative='lib.so', **options)
                        else:
                            runtime.prepare_ios(cache, result, pin, target='caller-ios', framework_relative='framework',
                                                tree_digest=Mock(), current_toolchain=Mock(), **options)
                    self.assertEqual(dict(os.environ), original)
                self.assertFalse(result.exists())
                self.assertFalse((cache / 'prepared-manager.json').exists())
                self.assertFalse((cache / 'prepared-manager-ios.json').exists())


class TestbedTests(unittest.TestCase):
    def test_offline_wheel_install_and_android_arguments_are_caller_selected(self):
        command = Mock()
        root = Path('/fixture')
        testbed.install_payload_wheels(root, root / 'payload', root / 'wheels',
                                      ['example==1.2'], command=command)
        argv, cwd, timeout = command.call_args.args
        self.assertIn('--no-index', argv)
        self.assertIn('--no-deps', argv)
        self.assertEqual(argv[-1], 'example==1.2')
        self.assertEqual(cwd, root)
        self.assertEqual(timeout, 180)
        args = ['-m', 'example.smoke', '--identity', 'abc']
        argv = testbed.android_test_command('caller-serial', root / 'payload', args)
        self.assertEqual(argv[-len(args):], args)
        self.assertEqual(argv[4], 'caller-serial')

    def test_scene_adaptation_accepts_a_different_caller_and_is_idempotent(self):
        import plistlib
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app, project = root / 'iOSTestbed', root / 'iOSTestbed.xcodeproj'
            app.mkdir()
            project.mkdir()
            delegate = app / 'AppDelegate.m'
            delegate.write_text('@implementation AppDelegate\n@end\n')
            info = app / 'iOSTestbed-Info.plist'
            info.write_bytes(plistlib.dumps({}))
            pbx = project / 'project.pbxproj'
            pbx.write_text('IPHONEOS_DEPLOYMENT_TARGET = 13.0;\nIPHONEOS_DEPLOYMENT_TARGET = 17.0;\n')
            options = dict(scene_class='ExampleScene', scene_source=testbed.scene_source('ExampleScene'),
                           deployment_target='16.0', adapter_sha256='caller-adapter')
            first = testbed.modernize(root, **options)
            second = testbed.modernize(root, **options)
            self.assertEqual(first['after'], second['after'])
            self.assertIn('IPHONEOS_DEPLOYMENT_TARGET = 16.0;', pbx.read_text())
            self.assertIn('IPHONEOS_DEPLOYMENT_TARGET = 17.0;', pbx.read_text())
            self.assertIn('@interface ExampleScene', delegate.read_text())
            self.assertEqual(first['adapter_sha256'], 'caller-adapter')
            self.assertEqual(first['manager_adapter_sha256'], runtime.checksum(testbed.__file__))
            data = plistlib.loads(info.read_bytes())
            data['UIApplicationSceneManifest']['UISceneConfigurations'] = {'unreviewed': []}
            info.write_bytes(plistlib.dumps(data))
            before = delegate.read_bytes(), info.read_bytes(), pbx.read_bytes()
            with self.assertRaisesRegex(ValueError, 'Unexpected upstream scene'):
                testbed.modernize(root, **options)
            self.assertEqual(before, (delegate.read_bytes(), info.read_bytes(), pbx.read_bytes()))

    def test_clone_preserves_caller_payload_and_arguments(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload, clone = root / 'payload', root / 'app'
            payload.mkdir()
            (payload / 'example.py').write_text('caller payload')
            def command(argv, cwd, timeout):
                self.assertEqual(argv[-3:], ['--framework', str(root / 'framework'), str(clone)])
                clone.mkdir()
                (clone / '__main__.py').write_text('import json\ndef update_test_plan(path, platform, args):\n (path / "args.json").write_text(json.dumps([platform, args]))\n')
            args = ['caller.smoke', '--identity', 'abc']
            receipt = testbed.prepare_ios(root, clone, root / 'framework', payload, args,
                                           command=command, adapt=lambda path: {'adapted': True})
            self.assertEqual(receipt, {'adapted': True})
            self.assertEqual((clone / 'iOSTestbed/app/example.py').read_text(), 'caller payload')
            self.assertEqual(json.loads((clone / 'args.json').read_text()), ['iOS', args])
            build = testbed.ios_build_command(clone, 'owned-device', deployment_target='16.0')
            self.assertIn('platform=iOS Simulator,id=owned-device', build)
            self.assertEqual(build[-1], 'IPHONEOS_DEPLOYMENT_TARGET=16.0')


if __name__ == '__main__':
    unittest.main()
