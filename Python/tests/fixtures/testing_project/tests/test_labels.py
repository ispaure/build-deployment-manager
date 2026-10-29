"""Observable input/output contracts; no services or native SDKs required."""
import unittest

from labels import display_name


class DisplayNameTests(unittest.TestCase):
    def test_surrounding_whitespace_is_removed(self):
        self.assertEqual(display_name('  Notes  '), 'Notes')

    def test_blank_name_gets_a_visible_default(self):
        self.assertEqual(display_name('   '), 'Untitled')
