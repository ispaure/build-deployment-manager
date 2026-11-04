import io
import json
import unittest

from build_manager.adapter_sdk import serve, operations_for, backend_options, validate_capabilities


class AdapterSDKTests(unittest.TestCase):
    def test_invalid_discovery_metadata_names_the_descriptor_field(self):
        valid = dict(platforms=['native'], operations=['Test', 'Build'])
        cases = [
            ({'platforms': ['native', 'native']}, 'capabilities.platforms'),
            ({'operations_by_target': []}, 'operations_by_target'),
            ({'operations_by_target': {'native': ['Typo']}}, 'operations_by_target.native'),
            ({'backends': {'typo': ['Local']}}, 'backends.typo'),
            ({'backends': {'native': 'Local'}}, 'backends.native'),
            ({'host_backends': []}, 'host_backends'),
            ({'host_backends': {'darwin': []}}, 'host_backends.darwin'),
            ({'host_backends': {'darwin': {'native': {'Typo': ['Local']}}}}, 'darwin.native.Typo'),
            ({'backends': {'native': ['Local', 'Local']}}, 'backends.native'),
            ({'backends': {'native': [None]}}, 'backends.native'),
        ]
        for changes, field in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, field):
                validate_capabilities(dict(valid, **changes))

    def test_discovery_validation_preserves_disabled_choices_and_host_fallbacks(self):
        capabilities = dict(platforms=['native', 'other'], operations=['Test', 'Build'],
            operations_by_target={'native': ['Test'], 'other': []},
            backends={'native': ['Local']},
            host_backends={'darwin': {'native': {'Test': []}}})
        validate_capabilities(capabilities)
        descriptor = dict(capabilities=capabilities)
        self.assertEqual(backend_options(descriptor, 'native', host='darwin'), ())
        self.assertEqual(backend_options(descriptor, 'native', host='linux'), ('Local',))
        self.assertEqual(operations_for(descriptor, 'other'), ())

    def test_dispatch_keeps_diagnostics_off_protocol_and_passes_private_context(self):
        def handler(values, context):
            print('diagnostic')
            return dict(values=values, profile=context['settings_profile'])
        output = io.StringIO()
        serve({'settings': handler}, stdin=io.StringIO(json.dumps(dict(schema=1, action='settings',
            values={'choice': 'one'}, settings_profile='/private/registration/profile.json'))), stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result['result']['profile'], '/private/registration/profile.json')
        self.assertNotIn('diagnostic', output.getvalue())
        with self.assertRaises(ValueError):
            serve({}, stdin=io.StringIO('{"schema":1,"action":"unknown"}'), stdout=io.StringIO())

    def test_capabilities_have_one_source_with_host_overrides(self):
        descriptor = {'capabilities': dict(operations=['Test', 'Build'], operations_by_target={'host': ['Test']},
            backends={'host': ['Local']}, host_backends={'win32': {'host': {'Test': ['Windows']}}})}
        self.assertEqual(operations_for(descriptor, 'host'), ('Test',))
        self.assertEqual(backend_options(descriptor, 'host', host='win32'), ('Windows',))
        self.assertEqual(backend_options(descriptor, 'host', host='linux'), ('Local',))
