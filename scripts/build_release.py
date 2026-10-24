#!/usr/bin/env python3
"""Build a reviewed source-only distribution; never copy local research data."""
from __future__ import annotations
import argparse
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FILES={'.gitignore','.gitattributes','README.md','README.en.md','LICENSE','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md','THIRD_PARTY_NOTICES.md','requirements.txt','requirements-dev.txt','config.example.yaml','run.sh','tools/background_service.py'}
TREES=('app','tests','scripts','docs/open-source','examples','.github')
SUFFIXES={'.py','.md','.json','.jsonl','.yaml','.yml','.txt','.html','.css','.js','.svg'}
PATTERNS={
 'api-key':re.compile(r'\bsk-[A-Za-z0-9_-]{16,}'),
 'private-home':re.compile(r'(?:/Users/|/home/)[A-Za-z0-9_.-]+/'),
 'private-key':re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
 'literal-bearer':re.compile(r'Bearer\s+[A-Za-z0-9_.-]{24,}'),
}


def selected(root=ROOT):
    result=[]
    for name in sorted(FILES):
        path=root/name
        if not path.is_file() or path.is_symlink():raise ValueError('Missing or unsafe release file: '+name)
        result.append(path)
    for tree in TREES:
        base=root/tree
        if base.is_symlink():raise ValueError('Symlink tree: '+tree)
        for path in sorted(base.rglob('*')):
            relative=path.relative_to(root)
            if any(part=='__pycache__' or part=='.DS_Store' for part in relative.parts):continue
            if path.is_symlink():raise ValueError('Symlink in release tree: '+str(relative))
            if not path.is_file():continue
            if path.suffix not in SUFFIXES:raise ValueError('Unreviewed file type: '+str(relative))
            result.append(path)
    return sorted(set(result))


def private_markers(root):
    # Read only local identifiers for comparison; never copy or print their values.
    result=set()
    for path in (root/'kb-data/catalog/sources').glob('*.json'):
        try:
            value=json.loads(path.read_text()).get('group_id')
            if value:result.add(str(value))
        except (ValueError,OSError):pass
    for path in (root/'kb-data/catalog/youdao').glob('*.json'):
        key=path.stem.removesuffix('-error')
        if re.fullmatch('[a-f0-9]{32}',key):result.add(key)
    return result


def audit(paths,root=ROOT):
    markers=private_markers(root)
    issues=[]
    for path in paths:
        try:text=path.read_text(encoding='utf-8')
        except (UnicodeError,OSError):
            issues.append((str(path.relative_to(root)),'non-text-file'));continue
        for rule,pattern in PATTERNS.items():
            if pattern.search(text):issues.append((str(path.relative_to(root)),rule))
        if any(value in text for value in markers):issues.append((str(path.relative_to(root)),'local-source-identifier'))
    return issues


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    paths=selected();issues=audit(paths)
    if issues:
        for path,rule in issues:print(f'FAIL {path}: {rule}')
        raise SystemExit('Release audit failed. Values are intentionally hidden.')
    print(f'PASS: {len(paths)} reviewed source files; no configured sensitive pattern found.')
    if args.check:return
    dist=ROOT/'dist';dist.mkdir(exist_ok=True)
    destination=dist/'researchdock';archive=dist/'researchdock-source.zip'
    if destination.exists() or archive.exists():raise SystemExit('Release output already exists. Move it aside before building again.')
    with tempfile.TemporaryDirectory(prefix='release-',dir=dist) as temporary:
        stage=Path(temporary)/'researchdock';stage.mkdir()
        for source in paths:
            target=stage/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        copied=selected(stage)
        findings=audit(copied,stage)
        if findings:raise SystemExit('Staged release failed verification.')
        # A manifest records only public relative paths, never local absolute paths.
        (stage/'RELEASE_MANIFEST.txt').write_text('\n'.join(str(p.relative_to(ROOT)) for p in paths)+'\n',encoding='utf-8')
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as zipped:
            for file in sorted(stage.rglob('*')):
                if file.is_file():zipped.write(file,Path('researchdock')/file.relative_to(stage))
        shutil.move(str(stage),destination)
    print('Source tree: dist/researchdock/')
    print('Source ZIP: dist/researchdock-source.zip')


if __name__=='__main__':main()
