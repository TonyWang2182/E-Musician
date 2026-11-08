"""Retain one raw isolated scanner reply for exact identity diagnostics."""
import argparse
import json
from pathlib import Path

from InstalledPluginAudit import bounded_run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path,required=True)
    parser.add_argument('--module',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=False)
    output=args.out/'worker.json'
    command=[str(args.exe),'--plugin-scan-worker','VST' if args.module.suffix.lower()=='.dll' else 'VST3',str(args.module),str(output)]
    process=bounded_run(command,args.out/'worker.log',35)
    (args.out/'process.json').write_text(json.dumps(process,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(process))
    if output.exists():print(output.read_text(encoding='utf-8-sig'))
    return 0 if process['exit_code']==0 and output.exists() else 1


if __name__=='__main__':raise SystemExit(main())
