"""Install/remove the user's local launchd service; no system-wide changes."""
import os
import plistlib
import subprocess
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
label='com.stock-kb.local'
path=Path.home()/'Library/LaunchAgents'/f'{label}.plist'
domain=f'gui/{os.getuid()}'
if len(sys.argv)>1 and sys.argv[1]=='remove':
    subprocess.run(['launchctl','bootout',f'{domain}/{label}'],check=False)
    path.unlink(missing_ok=True)
else:
    logs=root/'kb-data/logs'
    logs.mkdir(parents=True,exist_ok=True)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(plistlib.dumps({'Label':label,'ProgramArguments':[str(root/'.venv/bin/python'),'-m','uvicorn','app.web.app:app','--host','127.0.0.1','--port','8001','--log-level','warning','--no-access-log'],'WorkingDirectory':str(root),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'StandardOutPath':str(logs/'service.log'),'StandardErrorPath':str(logs/'service-error.log')}))
    subprocess.run(['launchctl','bootstrap',domain,str(path)],check=True)
    print('Installed:',path)
