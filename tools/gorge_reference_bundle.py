"""Pack the exact positive native proof and production inputs for reference CI.

This creates no secret, release, lease or evaluation. Failed/unsealed native
attempts are refused before a new destination is created.
"""
import json
from pathlib import Path
import shutil
import zipfile

from gorge_ci_exchange import extract_pinned, sha
from gorge_native_gate import NativeAuditGateError, evidence_layout, verify_native_audit
from gorge_reference_pool import portable_native_verdict
from gorge_reference_worker import write_new

RESERVE = 60*2**30
STAGE_CAP = 2**30
ARCHIVE_CAP = 256*2**20
EXTRACTED_CAP = 512*2**20


def _pin(base, index, name):
    path = base/name
    if (not path.resolve().is_relative_to(base) or path.is_symlink() or path.is_junction() or
            name not in index['files']):
        raise NativeAuditGateError('Bundle input is absent or escapes its declared seal: '+name)
    value = index['files'][name]
    if path.stat().st_size!=value['bytes'] or sha(path)!=value['sha256']:
        raise NativeAuditGateError('Bundle input differs from its declared seal: '+name)
    return path


def selected_inputs(native, runtime):
    native, runtime = Path(native).resolve(), Path(runtime).resolve()
    native_seal=json.loads((native/'SEAL.json').read_bytes())
    runtime_seal=json.loads((runtime/'SEAL.json').read_bytes())
    layout=evidence_layout(native)
    prefix=layout['prefix']
    audit=json.loads((native/(prefix+'NATIVE-AUDIT.json')).read_bytes())
    callback=prefix+audit['full_report_path'].replace('\\','/').split('/')[-2]+'/'
    native_names=['RECOVERY.json',layout['terminal'],prefix+'NATIVE-AUDIT.json',
        prefix+'MANIFEST.json',layout['parent'],prefix+'ALLOCATION.json',
        callback+'report.json',callback+'RECEIPT.json',callback+'primary.jsonl']
    if layout['kind']=='local-windows-amd64':
        native_names.extend(['HOST-RELEASE.json','CLOSURE.json'])
    # Preserve the tested qualifier. Linux reference engine/agent binaries
    # still need their own actual reference qualification on the target host.
    runtime_names=['BUILD.json','REGISTRY.json','registry.gob.gz',layout['qualifier'],
        'spellbench-gorge-env-linux-amd64','spellbench-gorge-agent-linux-amd64']
    sources={'native/'+name:_pin(native,native_seal,name) for name in native_names}
    sources.update({'runtime/'+name:_pin(runtime,runtime_seal,name) for name in runtime_names})
    # The seal files and separately pinned cleanup receipt are not entries in
    # their own seals. verify_native_audit checks their declared external hashes.
    sources.update({'native/SEAL.json':native/'SEAL.json',
        'native/'+layout['cleanup']:native/layout['cleanup'],'runtime/SEAL.json':runtime/'SEAL.json'})
    return sources


def pack_bundle(*, native, native_recovery, runtime, runtime_recovery,
                native_seal_sha256, runtime_seal_sha256, cleanup_sha256, destination, recovery):
    arguments=dict(seal_sha256=native_seal_sha256,runtime_seal_sha256=runtime_seal_sha256,
                   cleanup_sha256=cleanup_sha256)
    verdict=verify_native_audit(native,runtime,**arguments)
    copied_verdict=verify_native_audit(native_recovery,runtime_recovery,**arguments)
    if portable_native_verdict(verdict)!=portable_native_verdict(copied_verdict):
        raise NativeAuditGateError('Independent native/runtime recovery has a different positive proof')
    sources=selected_inputs(native,runtime)
    recovery_sources=selected_inputs(native_recovery,runtime_recovery)
    inventory={name:dict(bytes=path.stat().st_size,sha256=sha(path)) for name,path in sources.items()}
    if set(inventory)!=set(recovery_sources) or any(sha(recovery_sources[name])!=pin['sha256'] for name,pin in inventory.items()):
        raise NativeAuditGateError('Independent bundle inputs differ')
    extracted_bytes=sum(value['bytes'] for value in inventory.values())
    if extracted_bytes>EXTRACTED_CAP:
        raise RuntimeError('Exact reference input bundle exceeds its extraction budget')
    destination,recovery=Path(destination).resolve(),Path(recovery).resolve()
    if destination==recovery or destination.exists() or recovery.exists():
        raise RuntimeError('Reference bundling requires two new independently owned roots')
    projected=extracted_bytes+ARCHIVE_CAP+2*2**20
    if projected>STAGE_CAP or any(shutil.disk_usage(path.parent).free<RESERVE+projected for path in (destination,recovery)):
        raise RuntimeError('Reference bundling cannot preserve its storage cap and reserve')
    destination.mkdir(parents=True)
    recovery.mkdir(parents=True)
    archive=destination/'reference-inputs.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as zipped:
        for name,path in sources.items():
            zipped.write(path,name)
    if archive.stat().st_size>ARCHIVE_CAP:
        raise RuntimeError('Exact reference archive exceeds its upload budget')
    shutil.copyfile(archive,recovery/archive.name)
    if sha(archive)!=sha(recovery/archive.name):
        raise RuntimeError('Independent reference archive recovery differs')
    # Verify extraction in both roots before publishing any dispatch control.
    for base in (destination,recovery):
        extract_pinned(base/archive.name,base/'input',cap_bytes=extracted_bytes)
        for name,pin in inventory.items():
            path=base/'input'/name
            if path.stat().st_size!=pin['bytes'] or sha(path)!=pin['sha256']:
                raise RuntimeError('Reference archive did not recover its exact input inventory')
        check=verify_native_audit(base/'input/native',base/'input/runtime',**arguments)
        if portable_native_verdict(check)!=portable_native_verdict(verdict):
            raise NativeAuditGateError('Extracted bundle changed the positive native proof')
    record=dict(schema='spellbench-gorge-reference-input-bundle/v1',
        scope='reference qualification only',native_verdict=portable_native_verdict(verdict),
        archive_name=archive.name,archive_bytes=archive.stat().st_size,archive_sha256=sha(archive),
        extracted_bytes=extracted_bytes,files=inventory,native_seal_sha256=native_seal_sha256,
        runtime_seal_sha256=runtime_seal_sha256,cleanup_sha256=cleanup_sha256,
        source_of_record=str(destination),recovery_root=str(recovery),
        independent_recovery_verified=True,stage_cap_bytes=STAGE_CAP,reserve_bytes=RESERVE,
        private_secret_created=False,release_created=False,evaluation_started=False,rated_games=0)
    for base in (destination,recovery):
        write_new(base/'BUNDLE.json',record)
    files={path.relative_to(destination).as_posix():dict(bytes=path.stat().st_size,sha256=sha(path))
           for path in destination.rglob('*') if path.is_file()}
    if any(sha(recovery/name)!=pin['sha256'] for name,pin in files.items()):
        raise RuntimeError('Independent complete reference staging differs')
    seal=dict(files=files,source_of_record=str(destination),recovery_root=str(recovery),
              bytes=sum(pin['bytes'] for pin in files.values()),independent_recovery_verified=True)
    for base in (destination,recovery):
        write_new(base/'SEAL.json',seal)
    return record
