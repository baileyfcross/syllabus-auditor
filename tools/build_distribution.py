"""Builds source archive or complete platform-specific offline delivery.
Complete mode downloads model at BUILD time, builds Python wheels and then zips.
An offline recipient runs tools/install_offline.py to install wheels without internet.
"""
import argparse,subprocess,zipfile,sys,os,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def build(dest,complete):
    if complete:
        subprocess.check_call([sys.executable,str(ROOT/'tools'/'prepare_model.py')])
        wheels=ROOT/'vendor'/'wheels';wheels.mkdir(parents=True,exist_ok=True)
        subprocess.check_call([sys.executable,'-m','pip','wheel','-r',str(ROOT/'requirements-ai.txt'),'-w',str(wheels)])
    dest=Path(dest).resolve();dest.parent.mkdir(parents=True,exist_ok=True)
    skip={'.venv','__pycache__','.git','.pytest_cache','data'}
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as z:
        for item in ROOT.rglob('*'):
            if not item.is_file() or item.resolve()==dest or set(item.relative_to(ROOT).parts)&skip:continue
            if item.suffix=='.gguf' and not complete:continue
            if item.parts and 'vendor' in item.parts and not complete:continue
            z.write(item,str(item.relative_to(ROOT)))
    print(('COMPLETE OFFLINE' if complete else 'SOURCE')+' PACKAGE:',dest)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--complete',action='store_true');p.add_argument('--output',default='syllabus-auditor.zip');a=p.parse_args();build(a.output,a.complete)
