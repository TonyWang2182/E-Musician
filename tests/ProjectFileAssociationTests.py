"""Registration contracts: memory fixtures plus one isolated non-association HKCU fixture."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import register_project_file as association


class Registry:
    def __init__(self):
        self.keys = {}

    def exists(self, key):
        return key in self.keys

    def get(self, key, name):
        return copy.deepcopy(self.keys.get(key, {}).get(name))

    def set(self, key, name, value):
        for parent in association.parent_keys(key):
            self.keys.setdefault(parent, {})
        self.keys.setdefault(key, {})[name] = copy.deepcopy(value)

    def delete(self, key, name):
        self.keys.get(key, {}).pop(name, None)

    def delete_if_empty(self, key):
        if not self.keys.get(key) and not any(k.startswith(key + '\\') for k in self.keys):
            self.keys.pop(key, None)


class AssociationTests(unittest.TestCase):
    executable = r'E:\Music & DAW\bin\E-musician.exe'

    def test_launch_command_quotes_spaces_and_keeps_project_placeholder(self):
        plan = association.make_plan(Registry(), self.executable)
        command = next(e['after']['data'] for e in plan['values'] if e['key'] == association.TYPE_KEY + r'\shell\open\command')
        self.assertEqual(command, '"E:\\Music & DAW\\bin\\E-musician.exe" --agent --open-project "%1"')
        self.assertNotIn('cmd.exe', command)

    def test_rejects_command_injection_and_relative_executable(self):
        for value in ['E-musician.exe', 'E:/x/other.exe', 'E:/a" /E-musician.exe', 'E:/a\n/E-musician.exe']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                association.quoted_executable(value)

    def test_legacy_default_is_updated_and_restored_exactly(self):
        store = Registry()
        store.set(association.EXTENSION, '', association.string_value('emproj_auto_file'))
        before = copy.deepcopy(store.keys)
        plan = association.make_plan(store, self.executable)
        association.apply_plan(store, plan)
        self.assertEqual(store.get(association.EXTENSION, '')['data'], association.PROGID)
        association.restore_plan(store, plan)
        self.assertEqual(store.keys, before)

    def test_foreign_default_and_windows_userchoice_are_preserved(self):
        store = Registry()
        store.set(association.EXTENSION, '', association.string_value('AnotherEditor.Project'))
        store.set(association.USER_CHOICE, 'ProgId', association.string_value('AnotherEditor.Project'))
        store.set(association.USER_CHOICE, 'Hash', association.string_value('system-protected-hash'))
        before = copy.deepcopy(store.keys[association.USER_CHOICE])
        plan = association.make_plan(store, self.executable)
        association.apply_plan(store, plan)
        self.assertTrue(plan['foreign_default_preserved'])
        self.assertEqual(store.get(association.EXTENSION, '')['data'], 'AnotherEditor.Project')
        self.assertEqual(store.keys[association.USER_CHOICE], before)

    def test_latest_userchoice_keeps_app_identity_while_owned_path_is_updated(self):
        store = Registry()
        store.set(association.USER_CHOICE_LATEST, 'Hash', association.string_value('protected-latest-hash'))
        store.set(association.USER_CHOICE_LATEST + r'\ProgId', 'ProgId',
                  association.string_value(r'Applications\E-musician.exe'))
        old = association.string_value('"E:\\old\\E-musician.exe" "%1"')
        store.set(association.APPLICATION_KEY + r'\shell\open\command', '', old)
        before = copy.deepcopy(store.keys)
        digest = association.protected_choice_digest(store)
        plan = association.make_plan(store, self.executable)
        association.apply_plan(store, plan)
        self.assertFalse(plan['foreign_application_handler_preserved'])
        self.assertIn('--agent --open-project "%1"', store.get(association.APPLICATION_KEY + r'\shell\open\command', '')['data'])
        self.assertEqual(association.protected_choice_digest(store), digest)
        association.restore_plan(store, plan)
        self.assertEqual(store.keys, before)

    def test_foreign_application_handler_and_legacy_type_handler_are_preserved(self):
        store = Registry()
        foreign = association.string_value('"C:\\Windows\\notepad.exe" "%1"')
        store.set(association.EXTENSION, '', association.string_value('emproj_auto_file'))
        store.set(association.CLASSES + r'\emproj_auto_file\shell\open\command', '', foreign)
        store.set(association.APPLICATION_KEY + r'\shell\open\command', '', foreign)
        plan = association.make_plan(store, self.executable)
        association.apply_plan(store, plan)
        self.assertTrue(plan['foreign_default_preserved'])
        self.assertTrue(plan['foreign_application_handler_preserved'])
        self.assertEqual(store.get(association.EXTENSION, '')['data'], 'emproj_auto_file')
        self.assertEqual(store.get(association.APPLICATION_KEY + r'\shell\open\command', ''), foreign)

    def test_restore_keeps_unrelated_values_added_later(self):
        store = Registry()
        plan = association.make_plan(store, self.executable)
        association.apply_plan(store, plan)
        store.set(association.EXTENSION, 'UserNote', association.string_value('keep me'))
        association.restore_plan(store, plan)
        self.assertEqual(store.keys, {association.EXTENSION: {'UserNote': association.string_value('keep me')}})

    def test_restore_refuses_all_writes_if_any_value_changed(self):
        store = Registry()
        plan = association.make_plan(store, self.executable)
        association.apply_plan(store, plan)
        store.set(association.TYPE_KEY + r'\DefaultIcon', '', association.string_value('user-new-icon.ico'))
        before = copy.deepcopy(store.keys)
        with self.assertRaises(RuntimeError):
            association.restore_plan(store, plan)
        self.assertEqual(store.keys, before)

    def test_restore_cannot_target_arbitrary_registry_keys(self):
        store = Registry()
        plan = association.make_plan(store, self.executable)
        plan['values'][0]['key'] = r'Software\UnrelatedApp'
        with self.assertRaises(ValueError):
            association.restore_plan(store, plan)
        self.assertEqual(store.keys, {})

    def test_binary_registry_values_round_trip_in_backup(self):
        store = Registry()
        store.set(association.EXTENSION + r'\OpenWithProgids', association.PROGID,
                  {'data': b'\x00\x81\xff', 'type': association.REG_NONE})
        before = copy.deepcopy(store.keys)
        plan = association.make_plan(store, self.executable)
        backup = json.loads(json.dumps(plan, default=association.json_default), object_hook=association.json_hook)
        association.apply_plan(store, backup)
        association.restore_plan(store, backup)
        self.assertEqual(store.keys, before)

    def test_partial_write_error_rolls_back_completed_values(self):
        class FailingRegistry(Registry):
            fail = True
            def set(self, key, name, value):
                if self.fail and key.endswith(r'\command'):
                    self.fail = False
                    raise OSError('simulated registry write failure')
                return super().set(key, name, value)
        store = FailingRegistry()
        plan = association.make_plan(store, self.executable)
        with self.assertRaises(OSError):
            association.apply_plan(store, plan)
        self.assertEqual(store.keys, {})

    @unittest.skipUnless(sys.platform == 'win32', 'Windows registry integration')
    def test_real_registry_roundtrip_in_unique_non_association_fixture(self):
        # This is deliberately outside Software\Classes and FileExts. It cannot
        # register an actual file type or change the user's default application.
        root = r'Software\E-musician\AssociationTests' + '\\' + uuid.uuid4().hex
        classes = root + r'\Classes'
        with patch.multiple(association, CLASSES=classes, EXTENSION=classes + r'\.emproj',
                            TYPE_KEY=classes + '\\' + association.PROGID,
                            APPLICATION_KEY=classes + r'\Applications\E-musician.exe',
                            USER_CHOICE=root + r'\UserChoice', USER_CHOICE_LATEST=root + r'\UserChoiceLatest'):
            store = association.WindowsRegistry()
            self.assertFalse(store.exists(root))
            plan = association.make_plan(store, self.executable)
            try:
                association.apply_plan(store, plan)
                self.assertEqual(store.get(association.EXTENSION, '')['data'], association.PROGID)
                self.assertEqual(store.get(association.EXTENSION + r'\OpenWithProgids', association.PROGID),
                                 {'data': b'', 'type': association.REG_NONE})
                self.assertEqual(store.get(association.TYPE_KEY + r'\DefaultIcon', '')['data'],
                                 '"E:\\Music & DAW\\bin\\E-musician.exe",0')
                association.restore_plan(store, plan)
                self.assertFalse(store.exists(association.EXTENSION))
                self.assertFalse(store.exists(association.TYPE_KEY))
            finally:
                association.restore_plan(store, plan)
                store.delete_if_empty(classes)
                store.delete_if_empty(root)
            self.assertFalse(store.exists(root))


if __name__ == '__main__':
    unittest.main(verbosity=2)
