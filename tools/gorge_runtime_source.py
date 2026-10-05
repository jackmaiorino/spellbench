"""Bind compiled gorge source while requiring current reference requalification."""
import ast
import hashlib
from pathlib import Path
import subprocess

REFERENCE = 'engines/gorge/scripts/reference_matrix.py'
LAUNCHER_FUNCTIONS = {'main', 'audited_qualification'}


def _frozen_reference(tree):
    # The matrix selection, receipt joining, mapping gate, imports and globals
    # retain their exact syntax. Only the local execution/finalization wrapper
    # may differ; its actual current-source reference run is still required.
    tree.body = [node for node in tree.body if not
                 (isinstance(node, ast.FunctionDef) and node.name in LAUNCHER_FUNCTIONS)]
    return ast.dump(tree, include_attributes=False)


def verify_runtime_source(source, runtime_commit, current='HEAD'):
    source = Path(source).resolve()
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=source)
    changes = git('diff', '--name-only', runtime_commit, current, '--', 'engines/gorge').decode().splitlines()
    if set(changes) - {REFERENCE}:
        raise RuntimeError('Compiled gorge source differs from the audited production runtime')
    record = dict(runtime_source_commit=runtime_commit, compiled_gorge_source_identical=True,
        reference_launcher_source_changes=changes, current_reference_requalification_required=True)
    if changes:
        previous = git('show', runtime_commit + ':' + REFERENCE)
        current_source = git('show', current + ':' + REFERENCE)
        if _frozen_reference(ast.parse(previous)) != _frozen_reference(ast.parse(current_source)):
            raise RuntimeError('Frozen reference selection, receipt rules or mapping gate changed')
        record.update(reference_launcher_sha256=hashlib.sha256(current_source).hexdigest(),
            original_reference_sha256=hashlib.sha256(previous).hexdigest(), frozen_reference_helpers_identical=True)
    # Also refuse uncommitted changes: the executed launcher and source must
    # be the checked revision rather than an unrecorded working copy.
    if git('diff', current, '--', 'engines/gorge'):
        raise RuntimeError('Executed gorge source differs from the checked revision')
    return record
