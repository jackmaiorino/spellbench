"""Compile/source binding permits launcher repair but refuses frozen changes."""
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from gorge_runtime_source import REFERENCE, verify_runtime_source


def git(root, *args):
    return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()


@pytest.fixture
def source(tmp_path):
    git(tmp_path, 'init', '-b', 'fixture')
    git(tmp_path, 'config', 'user.name', 'Fixture')
    git(tmp_path, 'config', 'user.email', 'fixture@example.invalid')
    path = tmp_path/REFERENCE
    path.parent.mkdir(parents=True)
    path.write_text('CONST=140\ndef select_matrix(rows):\n return rows\ndef main():\n return 0\n')
    (tmp_path/'engines/gorge/native.go').write_text('package fixture\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'Fixture runtime')
    return tmp_path, git(tmp_path, 'rev-parse', 'HEAD')


def test_launcher_finalization_change_keeps_compiled_source_and_frozen_helpers(source):
    root, pin = source
    assert verify_runtime_source(root, pin)['compiled_gorge_source_identical']
    path = root/REFERENCE
    path.write_text(path.read_text().replace('return 0', 'return 1') + '\ndef audited_qualification(play):\n return play\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'Fixture launcher repair')
    binding = verify_runtime_source(root, pin)
    assert binding['frozen_reference_helpers_identical'] and binding['current_reference_requalification_required']
    assert binding['reference_launcher_source_changes'] == [REFERENCE]


@pytest.mark.parametrize('change', ['go', 'selector', 'constant', 'dirty'])
def test_source_or_frozen_reference_change_cannot_reuse_native_runtime(source, change):
    root, pin = source
    if change == 'go':
        (root/'engines/gorge/native.go').write_text('package different\n')
    else:
        path = root/REFERENCE
        text = path.read_text()
        path.write_text(text.replace('return rows', 'return rows[1:]') if change == 'selector' else
                        text.replace('140', '139') if change == 'constant' else text.replace('return 0', 'return 1'))
    if change != 'dirty':
        git(root, 'add', '.')
        git(root, 'commit', '-m', 'Fixture incompatible change')
    with pytest.raises(RuntimeError):
        verify_runtime_source(root, pin)
