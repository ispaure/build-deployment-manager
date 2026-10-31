import io
import json
import unittest

from build_manager.adapter_sdk import serve, operations_for, backend_options


class AdapterSDKTests(unittest.TestCase):
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
