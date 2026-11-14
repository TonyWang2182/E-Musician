"""Reversible, per-user .emproj association. Never rewrites Windows UserChoice.

Run `status` first, then `apply --exe ... --backup ...`. The backup records only
the values this tool owns; restore refuses to overwrite subsequent user changes.
No administrator privileges, Explorer restart, or icon-cache deletion required.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import datetime as dt
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import sys

CLASSES = r"Software\Classes"
EXTENSION = CLASSES + r"\.emproj"
PROGID = "E-musician.Project"
TYPE_KEY = CLASSES + "\\" + PROGID
APPLICATION_KEY = CLASSES + r"\Applications\E-musician.exe"
USER_CHOICE = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.emproj\UserChoice"
USER_CHOICE_LATEST = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.emproj\UserChoiceLatest"
REG_NONE, REG_SZ = 0, 1


def string_value(data):
    return {"data": data, "type": REG_SZ}


def quoted_executable(executable):
    text = str(executable)
    if any(c in text for c in ('"', '\x00', '\r', '\n')):
        raise ValueError("Executable path contains an invalid command character.")
    path = PureWindowsPath(text)
    if not path.is_absolute() or path.name.lower() != 'e-musician.exe':
        raise ValueError("Use an absolute path to E-musician.exe.")
    return '"' + str(path) + '"'


def parent_keys(key):
    result = []
    while key != CLASSES and key.startswith(CLASSES + "\\"):
        result.append(key)
        key = key.rsplit("\\", 1)[0]
    return result


def is_emusician_handler(value):
    if value is None:
        return True
    if value['type'] != REG_SZ or not isinstance(value['data'], str):
        return False
    match = re.fullmatch(r'\s*"([^"\r\n]+)"(?:\s+(?:"%1"|--agent\s+--open-project\s+"%1"))?\s*', value['data'])
    if match is None:
        return False
    path = PureWindowsPath(match.group(1))
    return path.is_absolute() and path.name.lower() == 'e-musician.exe'


def protected_choice_digest(store):
    # Observe both Windows layouts, but never write them or retain their hashes
    # in the backup/log. Application registration can update the selected app's
    # install path without replacing the user's protected application choice.
    values = [store.get(USER_CHOICE, 'ProgId'), store.get(USER_CHOICE, 'Hash'),
              store.get(USER_CHOICE_LATEST, 'ProgId'), store.get(USER_CHOICE_LATEST, 'Hash'),
              store.get(USER_CHOICE_LATEST + r'\ProgId', 'ProgId')]
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=json_default).encode('utf-8')).hexdigest()


def make_plan(store, executable):
    exe = quoted_executable(executable)
    original = store.get(EXTENSION, '')
    original_type = original['data'] if original and original['type'] == REG_SZ else None
    original_id = str(original_type).lower()
    legacy_handler = store.get(CLASSES + r'\emproj_auto_file\shell\open\command', '')
    owned = original is None or original_id in {'', PROGID.lower()} or (
        original_id == 'emproj_auto_file' and is_emusician_handler(legacy_handler))
    owned_application = is_emusician_handler(store.get(APPLICATION_KEY + r'\shell\open\command', ''))
    values = [
        (TYPE_KEY, '', string_value('E-musician project')),
        (TYPE_KEY + r'\DefaultIcon', '', string_value(exe + ',0')),
        (TYPE_KEY + r'\shell\open', '', string_value('Open with E-musician')),
        (TYPE_KEY + r'\shell\open\command', '', string_value(exe + ' --agent --open-project "%1"')),
        (EXTENSION + r'\OpenWithProgids', PROGID, {"data": b'', "type": REG_NONE}),
    ]
    if owned:
        values.append((EXTENSION, '', string_value(PROGID)))
    if owned_application:
        values.extend([
            (APPLICATION_KEY + r'\DefaultIcon', '', string_value(exe + ',0')),
            (APPLICATION_KEY + r'\shell\open\command', '', string_value(exe + ' --agent --open-project "%1"')),
        ])
    keys = {key for item in values for key in parent_keys(item[0])}
    return {
        'schema': 1,
        'created_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
        'executable': str(PureWindowsPath(str(executable))),
        'foreign_default_preserved': not owned,
        'foreign_application_handler_preserved': not owned_application,
        'user_choice_before': store.get(USER_CHOICE, 'ProgId'),
        'protected_choice_digest_before': protected_choice_digest(store),
        'keys': [{'key': k, 'existed': store.exists(k)} for k in sorted(keys)],
        'values': [{'key': k, 'name': name, 'before': store.get(k, name), 'after': value}
                   for k, name, value in values],
    }


def restore_plan(store, plan):
    validate_plan(plan)
    conflicts = [entry['key'] + ' / ' + entry['name'] for entry in plan['values']
                 if store.get(entry['key'], entry['name']) not in (entry['before'], entry['after'])]
    if conflicts:
        raise RuntimeError('Association changed after registration; restore made no changes: ' + ', '.join(conflicts))
    for entry in reversed(plan['values']):
        if store.get(entry['key'], entry['name']) == entry['before']:
            continue
        if entry['before'] is None:
            store.delete(entry['key'], entry['name'])
        else:
            store.set(entry['key'], entry['name'], entry['before'])
    for item in sorted(plan['keys'], key=lambda k: k['key'].count('\\'), reverse=True):
        if not item['existed']:
            store.delete_if_empty(item['key'])


def validate_plan(plan):
    if plan.get('schema') != 1:
        raise ValueError('Unsupported association backup schema.')
    allowed_values = {(TYPE_KEY, ''), (TYPE_KEY + r'\DefaultIcon', ''),
                      (TYPE_KEY + r'\shell\open', ''), (TYPE_KEY + r'\shell\open\command', ''),
                      (EXTENSION + r'\OpenWithProgids', PROGID), (EXTENSION, ''),
                      (APPLICATION_KEY + r'\DefaultIcon', ''), (APPLICATION_KEY + r'\shell\open\command', '')}
    allowed_keys = {key for path, _ in allowed_values for key in parent_keys(path)}
    seen = set()
    for item in plan['values']:
        pair = item['key'], item['name']
        if pair not in allowed_values or pair in seen:
            raise ValueError('Backup contains an unexpected or repeated registry value.')
        seen.add(pair)
    if any(item['key'] not in allowed_keys for item in plan['keys']):
        raise ValueError('Backup contains an unexpected registry key.')


def apply_plan(store, plan):
    validate_plan(plan)
    if any(store.get(e['key'], e['name']) != e['before'] for e in plan['values']):
        raise RuntimeError('Association changed while preparing registration; no changes made.')
    try:
        for entry in plan['values']:
            store.set(entry['key'], entry['name'], entry['after'])
    except Exception:
        restore_plan(store, plan)
        raise


def json_default(value):
    if isinstance(value, bytes):
        return {'base64_bytes': base64.b64encode(value).decode('ascii')}
    raise TypeError(type(value).__name__)


def json_hook(value):
    if set(value) == {'base64_bytes'}:
        return base64.b64decode(value['base64_bytes'], validate=True)
    return value


class WindowsRegistry:
    def __init__(self):
        import winreg
        self.reg = winreg

    def exists(self, path):
        try:
            with self.reg.OpenKey(self.reg.HKEY_CURRENT_USER, path):
                return True
        except FileNotFoundError:
            return False

    def get(self, path, name):
        try:
            with self.reg.OpenKey(self.reg.HKEY_CURRENT_USER, path) as key:
                data, kind = self.reg.QueryValueEx(key, name)
                # CPython represents an empty REG_NONE as None even though
                # SetValueEx accepts b''. Canonicalize before conflict checks
                # and backup comparison so our own empty OpenWith value can
                # always be safely restored.
                if kind == REG_NONE and data is None:
                    data = b''
                return {'data': data, 'type': kind}
        except FileNotFoundError:
            return None

    def set(self, path, name, value):
        with self.reg.CreateKeyEx(self.reg.HKEY_CURRENT_USER, path, 0, self.reg.KEY_SET_VALUE) as key:
            self.reg.SetValueEx(key, name, 0, value['type'], value['data'])

    def delete(self, path, name):
        try:
            with self.reg.OpenKey(self.reg.HKEY_CURRENT_USER, path, 0, self.reg.KEY_SET_VALUE) as key:
                self.reg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    def delete_if_empty(self, path):
        try:
            with self.reg.OpenKey(self.reg.HKEY_CURRENT_USER, path) as key:
                subkeys, values, _ = self.reg.QueryInfoKey(key)
            if not subkeys and not values:
                self.reg.DeleteKey(self.reg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass


def notify_shell():
    shell = ctypes.WinDLL('shell32', use_last_error=True)
    shell.SHChangeNotify.argtypes = [wintypes.LONG, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
    shell.SHChangeNotify.restype = None
    shell.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED / SHCNF_IDLIST


def effective_association(kind):
    api = ctypes.WinDLL('shlwapi', use_last_error=True)
    api.AssocQueryStringW.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.AssocQueryStringW.restype = ctypes.c_long
    length = wintypes.DWORD(32768)
    result = ctypes.create_unicode_buffer(length.value)
    status = api.AssocQueryStringW(0, kind, '.emproj', 'open' if kind in (1, 2) else None, result, ctypes.byref(length))
    return result.value if status == 0 else None


def status(store, executable=None):
    report = {'extension_default': store.get(EXTENSION, ''),
              'user_choice': store.get(USER_CHOICE, 'ProgId'),
              'user_choice_latest': store.get(USER_CHOICE_LATEST + r'\ProgId', 'ProgId'),
              'registered_icon': store.get(TYPE_KEY + r'\DefaultIcon', ''),
              'registered_command': store.get(TYPE_KEY + r'\shell\open\command', ''),
              'application_icon': store.get(APPLICATION_KEY + r'\DefaultIcon', ''),
              'application_command': store.get(APPLICATION_KEY + r'\shell\open\command', ''),
              'effective_command': effective_association(1),
              'effective_executable': effective_association(2),
              'effective_icon': effective_association(15)}
    if executable:
        shell = ctypes.WinDLL('shell32', use_last_error=True)
        shell.ExtractIconExW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        shell.ExtractIconExW.restype = wintypes.UINT
        report['executable_icon_groups'] = shell.ExtractIconExW(str(executable), -1, None, None, 0)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'apply', 'restore'))
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Registration is Windows-only.')
    store = WindowsRegistry()
    if args.action == 'apply':
        if args.exe is None or args.backup is None:
            parser.error('apply requires --exe and a new --backup path.')
        executable = args.exe.resolve(strict=True)
        plan = make_plan(store, executable)
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with args.backup.open('x', encoding='utf-8') as handle:
            json.dump(plan, handle, ensure_ascii=False, indent=2, default=json_default)
        apply_plan(store, plan)
        notify_shell()
        result = status(store, executable)
        result.update({'backup': str(args.backup.resolve()),
                       'foreign_default_preserved': plan['foreign_default_preserved'],
                       'foreign_application_handler_preserved': plan['foreign_application_handler_preserved'],
                       'user_choice_unchanged': protected_choice_digest(store) == plan['protected_choice_digest_before']})
    elif args.action == 'restore':
        if args.backup is None:
            parser.error('restore requires --backup.')
        plan = json.loads(args.backup.read_text(encoding='utf-8'), object_hook=json_hook)
        restore_plan(store, plan)
        notify_shell()
        result = status(store)
        result['restored_from'] = str(args.backup.resolve())
    else:
        result = status(store, args.exe)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=json_default))


if __name__ == '__main__':
    main()
