"""Native Windows Terminal clipboard / console-record / Codex draft comparison."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

CASES = ['A©B', 'A€B', 'A✓B', 'A✅B', 'A中B', 'A𠀀B', 'A😀B', 'A🔵B']
ROOT = Path(os.environ['RUNNER_TEMP']) / 'paste-37578'
SCRIPT = Path(__file__).resolve()
TITLE = "Unicode clipboard comparison"
VT_INPUT = 0x200
LINE_INPUT = 2
CTRL, SHIFT = 0x11, 0x10
U = c.WinDLL("user32", use_last_error=True)
K = c.WinDLL("kernel32", use_last_error=True)


def bind(lib, name, result, *params):
    fn = getattr(lib, name)
    fn.restype = result
    fn.argtypes = params
    return fn


def check(ok):
    if not ok:
        raise c.WinError(c.get_last_error())
    return ok


class KeyRecord(c.Structure):
    _fields_ = [
        ('event_type', w.WORD), ('pad', w.WORD), ('down', w.BOOL),
        ('repeat', w.WORD), ('vk', w.WORD), ('scan', w.WORD),
        ('unit', w.WORD), ('state', w.DWORD),
    ]


class Keyboard(c.Structure):
    _fields_ = [
        ('vk', w.WORD), ('scan', w.WORD), ('flags', w.DWORD),
        ('time', w.DWORD), ('extra_info', c.c_size_t),
    ]


class Input(c.Structure):
    _fields_ = [('type', w.DWORD), ('key', Keyboard), ('tail', c.c_byte * 8)]


assert c.sizeof(KeyRecord) == 20 and c.sizeof(Input) == 40
Ptr = c.c_void_p
GetStdHandle = bind(K, "GetStdHandle", w.HANDLE, w.DWORD)
GetConsoleMode = bind(K, "GetConsoleMode", w.BOOL, w.HANDLE, Ptr)
SetConsoleMode = bind(K, "SetConsoleMode", w.BOOL, w.HANDLE, w.DWORD)
GetCount = bind(K, "GetNumberOfConsoleInputEvents", w.BOOL, w.HANDLE, Ptr)
ReadInput = bind(K, "ReadConsoleInputW", w.BOOL, w.HANDLE, Ptr, w.DWORD, Ptr)
WriteInput = bind(K, "WriteConsoleInputW", w.BOOL, w.HANDLE, Ptr, w.DWORD, Ptr)
ReadOutput = bind(K, "ReadConsoleOutputCharacterW", w.BOOL, w.HANDLE, Ptr, w.DWORD, w.DWORD, Ptr)
CreateFile = bind(K, "CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD, Ptr, w.DWORD, w.DWORD, Ptr)
Close = bind(K, "CloseHandle", w.BOOL, w.HANDLE)
Allocate = bind(K, "GlobalAlloc", w.HGLOBAL, w.UINT, c.c_size_t)
Lock = bind(K, "GlobalLock", Ptr, w.HGLOBAL)
Unlock = bind(K, "GlobalUnlock", w.BOOL, w.HGLOBAL)
OpenClipboard = bind(U, "OpenClipboard", w.BOOL, w.HWND)
SetClipboardData = bind(U, "SetClipboardData", w.HANDLE, w.UINT, w.HANDLE)
GetClipboardData = bind(U, "GetClipboardData", w.HANDLE, w.UINT)
GetForeground = bind(U, "GetForegroundWindow", w.HWND)
GetTitle = bind(U, "GetWindowTextW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
GetClass = bind(U, "GetClassNameW", c.c_int, w.HWND, w.LPWSTR, c.c_int)
SetForeground = bind(U, "SetForegroundWindow", w.BOOL, w.HWND)
FindWindow = bind(U, "FindWindowW", w.HWND, w.LPCWSTR, w.LPCWSTR)
SendInput = bind(U, "SendInput", w.UINT, w.UINT, Ptr, c.c_int)
stdin = GetStdHandle(-10)


def mode():
    result = w.DWORD()
    check(GetConsoleMode(stdin, c.byref(result)))
    return result.value


def log(*values):
    with (ROOT / 'progress.txt').open('a', encoding='utf-8') as f:
        print(*values, file=f)


def wait_for(what, predicate, seconds=15, process=None):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if result := predicate():
            return result
        if process and process.poll() is not None:
            raise RuntimeError(f'{what}: Codex exited with {process.returncode}')
        time.sleep(0.06)
    raise RuntimeError(f'Timed out waiting for {what}')


def foreground():
    window = GetForeground()
    title, name = c.create_unicode_buffer(512), c.create_unicode_buffer(128)
    GetTitle(window, title, len(title))
    GetClass(window, name, len(name))
    return window, title.value, name.value


def terminal_window():
    window, title, name = foreground()
    if name == 'CASCADIA_HOSTING_WINDOW_CLASS' and TITLE in title:
        return window
    target = FindWindow('CASCADIA_HOSTING_WINDOW_CLASS', TITLE)
    if target:
        SetForeground(target)


def shortcut(*keys):
    wait_for('Windows Terminal foreground', terminal_window)
    events = [Input(1, Keyboard(vk, 0, 0)) for vk in keys]
    events.extend(Input(1, Keyboard(vk, 0, 2)) for vk in reversed(keys))
    batch = (Input * len(events))(*events)
    check(SendInput(len(batch), batch, c.sizeof(Input)) == len(batch))


def paste(text):
    hwnd = wait_for('Windows Terminal foreground', terminal_window)
    data = (text + '\0').encode('utf-16-le')
    handle = check(Allocate(2, len(data)))
    buf = check(Lock(handle))
    c.memmove(buf, data, len(data))
    Unlock(handle)
    wait_for('clipboard', lambda: OpenClipboard(hwnd))
    try:
        check(U.EmptyClipboard())
        check(SetClipboardData(13, handle))  # CF_UNICODETEXT
        copied = check(GetClipboardData(13))
        ptr = check(Lock(copied))
        assert c.string_at(ptr, len(data)) == data
        Unlock(copied)
    finally:
        U.CloseClipboard()
    shortcut(CTRL, SHIFT, ord('V'))


def read_available():
    n = w.DWORD()
    check(GetCount(stdin, c.byref(n)))
    if not n.value:
        return []
    records = (KeyRecord * n.value)()
    check(ReadInput(stdin, records, n.value, c.byref(n)))
    return [r for r in records[:n.value] if r.event_type == 1]


def describe(records):
    return [
        dict(unit=f'{r.unit:04X}', down=bool(r.down), vk=r.vk, scan=r.scan, state=r.state, repeat=r.repeat)
        for r in records
    ]


def raw_probe():
    previous = mode()
    check(SetConsoleMode(stdin, previous & ~(VT_INPUT | 7)))
    captures = {}
    try:
        for text in CASES:
            read_available()
            paste(text)
            records = []

            def received():
                records.extend(read_available())
                return any(r.unit == ord('B') for r in records)

            try:
                wait_for('last pasted record B', received)
            finally:
                time.sleep(0.15)
                records.extend(read_available())
                captures[text] = describe(records)
                log('clipboard records', ascii(text), ' '.join(
                    f"{r.unit:04X}{'d' if r.down else 'u'}" for r in records if r.unit >= 0x20
                ))
    finally:
        check(SetConsoleMode(stdin, previous))
    return captures


def record(unit, down, vk=0, scan=0, state=0):
    return KeyRecord(1, 0, int(down), 1, vk, scan, unit, state)


def records_for(text, releases):
    data = text.encode('utf-16-le')
    records = []
    for i in range(0, len(data), 2):
        unit = int.from_bytes(data[i:i+2], 'little')
        records.append(record(unit, True))
        if releases:
            records.append(record(unit, False))
    return records


def injected_cases():
    a = records_for('A', True)
    b = records_for('B', True)
    text = 'A𠀀😀🔵B'
    yield 'interleaved releases', text, records_for(text, True)
    yield 'presses only', text, records_for(text, False)
    yield 'surrogate Alt-code releases', 'A🔵B', a + [
        record(0xD83D, False, vk=0x12, scan=56),
        record(0xDD35, False, vk=0x12, scan=56)
    ] + b
    numpad = []
    for digit in [0, 1, 2, 6]:
        numpad.extend(record(0, down, vk=0x60+digit, state=0x22) for down in [True, False])
    yield 'BMP Alt-code release', 'A~B', a + numpad + [record(ord('~'), False, vk=0x12, scan=56, state=0x20)] + b


def inject(records):
    n = w.DWORD()
    batch = (KeyRecord * len(records))(*records)
    check(WriteInput(stdin, batch, len(batch), c.byref(n)))
    assert n.value == len(batch)


def screen():
    # Read the active console buffer only for readiness and timeout diagnostics.
    handle = CreateFile('CONOUT$', 0x80000000, 3, None, 3, 0, None)
    buf, n = c.create_unicode_buffer(16001), w.DWORD()
    try:
        check(ReadOutput(handle, buf, 16000, 0, c.byref(n)))
        return ' '.join(buf[:n.value].replace('\0', ' ').split())
    finally:
        Close(handle)


def export_draft(path):
    # Codex seeds this file with the actual composer text before invoking VISUAL.
    data = path.read_bytes()
    tmp = ROOT / 'capturing'
    tmp.write_bytes(data)
    path.write_bytes(b'')  # Start the next case with an empty composer.
    tmp.replace(ROOT / 'draft.utf8')


def points(text):
    return [f'U+{ord(ch):04X}' for ch in text]


def test_codex(label, exe):
    home = ROOT / ('config-' + label)
    project = ROOT / ('project-' + label)
    home.mkdir()
    project.mkdir()
    config = f"""
model_provider = "local"
model = "gpt-5.2"
sandbox_mode = "read-only"
check_for_update_on_startup = false
log_dir = '{home / "logs"}'
[model_providers.local]
name = "Draft test"
wire_api = "responses"
requires_openai_auth = false
base_url = "http://127.0.0.1:9/v1"
[projects.'{project}']
trust_level = "trusted"
[tui]
animations = false
"""
    (home / 'config.toml').write_text(config, encoding='utf-8')
    env = {
        **os.environ, 'CODEX_HOME': str(home), 'RUST_LOG': 'trace',
        'VISUAL': subprocess.list2cmdline([sys.executable, str(SCRIPT), 'export'])
    }
    result = {
        'variant': label,
        'version': subprocess.check_output([exe, '--version'], env=env, text=True).strip(),
        'binary_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
        'cases': []
    }
    log('starting', label, result['version'], result['binary_sha256'])
    original = mode()
    process = subprocess.Popen([exe, '--no-daemon'], cwd=project, env=env)
    draft = ROOT / 'draft.utf8'
    try:
        def ready():
            return not mode() & (VT_INPUT | LINE_INPUT) and '›' in screen()

        wait_for('Codex composer', ready, seconds=45, process=process)
        log('composer ready, input mode', hex(mode()))
        cases = [('clipboard', text, None) for text in CASES] + list(injected_cases())
        for index, (kind, text, records) in enumerate(cases):
            wait_for('Codex input mode', ready, process=process)
            time.sleep(0.35)
            log('trying', label, kind, ascii(text))
            console_mode = mode()
            assert not console_mode & (VT_INPUT | LINE_INPUT)
            assert not draft.exists()
            if records is None:
                paste(text)
            else:
                inject(records)
            time.sleep(0.55)
            shortcut(CTRL, ord('G'))
            wait_for('composer draft from VISUAL', draft.exists, process=process)
            data = draft.read_bytes()
            draft.rename(ROOT / f'{label}-{index:02d}.utf8')
            actual = data.decode('utf-8', errors='strict')
            row = dict(
                method=kind, mode=hex(console_mode), input=text, draft=actual,
                expected_points=points(text), actual_points=points(actual),
                utf8_hex=data.hex(), exact=data == text.encode('utf-8')
            )
            log('result', json.dumps(row))
            result['cases'].append(row)
    except Exception:
        log('console', ascii(screen()), 'mode', hex(mode()), 'foreground', ascii(foreground()))
        raise
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        check(SetConsoleMode(stdin, original))
    return result


def inside(variants):
    log('Windows', platform.platform(), 'WT_SESSION', bool(os.getenv('WT_SESSION')), 'foreground', ascii(foreground()))
    assert os.getenv('WT_SESSION')
    wait_for('Windows Terminal', terminal_window)
    result = dict(os=platform.platform(), terminal=os.environ['WT_VERSION'], records=raw_probe(), builds=[])
    for variant in variants:
        directory = Path(os.environ['RUNNER_TEMP']) / variant
        log('executable directory', directory)
        exe, = directory.rglob('codex.exe')
        result['builds'].append(test_codex(variant, exe))
    (ROOT / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


def outside(wt, variants):
    ROOT.mkdir()
    (wt.parent / '.portable').touch()
    print('Terminal', str(wt), 'foreground', ascii(foreground()), flush=True)
    args = [str(wt), '-w', 'new', 'new-tab', '--title', TITLE, '--suppressApplicationTitle',
            '--startingDirectory', str(ROOT), sys.executable, str(SCRIPT), 'inside', *variants]
    terminal = subprocess.Popen(args)
    try:
        wait_for('Windows Terminal child', (ROOT / 'progress.txt').exists, seconds=50)
        wait_for('Windows Terminal results', (ROOT / 'done').exists, seconds=210)
    finally:
        progress = ROOT / 'progress.txt'
        if progress.exists():
            print(progress.read_text(encoding='utf-8'))
        print('Terminal exit', terminal.poll(), 'foreground', ascii(foreground()))
    if (ROOT / 'error').exists():
        raise RuntimeError((ROOT / 'error').read_text(encoding='utf-8'))
    report = json.loads((ROOT / 'results.json').read_text())
    assert [v['variant'] for v in report['builds']] == variants
    for build in report['builds']:
        assert len(build['cases']) == 12
        for row in build['cases']:
            expected = row['input']
            if row['method'] == 'BMP Alt-code release':
                expected = 'AB'
            elif build['variant'] in ('before', 'release') and row['method'] in ('clipboard', 'interleaved releases'):
                expected = ''.join(ch for ch in expected if ord(ch) < 0x10000)
            assert row['draft'] == expected, row


if __name__ == '__main__':
    if sys.argv[1] == 'export':
        export_draft(Path(sys.argv[2]))
    elif sys.argv[1] == 'inside':
        try:
            inside(sys.argv[2:])
        except BaseException:
            (ROOT / 'error').write_text(traceback.format_exc(), encoding='utf-8')
        finally:
            (ROOT / 'done').touch()
    else:
        outside(Path(sys.argv[1]), sys.argv[2:])

