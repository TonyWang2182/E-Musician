"""Record the actual cloud inference environment and a real BF16 CUDA operation."""
import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
import torch

ROOT = Path('/root/autodl-tmp/emusician')


def main():
    if torch.__version__ != '2.10.0+cu128' or torch.version.cuda != '12.8':
        raise RuntimeError('Actual Torch/CUDA differs from the pinned ACE environment')
    x = torch.randn(32,32,device='cuda',dtype=torch.bfloat16)
    y = x @ x
    torch.cuda.synchronize()
    finite = bool(torch.isfinite(y).all())
    if not finite or torch.cuda.get_device_capability() != (12,0):
        raise RuntimeError('The expected Blackwell BF16 probe failed')
    record = {'utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'python':sys.version,'platform':platform.platform(),
              'torch':str(torch.__version__),'cuda_runtime':torch.version.cuda,'gpu':torch.cuda.get_device_name(),
              'compute_capability':list(torch.cuda.get_device_capability()),'gpu_memory_bytes':torch.cuda.get_device_properties(0).total_memory,
              'bf16_matmul_finite':finite,'driver':subprocess.check_output(['nvidia-smi','--query-gpu=driver_version','--format=csv,noheader'],text=True).strip(),
              'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}}
    for path in ['/sys/fs/cgroup/memory.max','/sys/fs/cgroup/cpu.max','/sys/fs/cgroup/memory/memory.limit_in_bytes']:
        if Path(path).is_file():
            record[path] = Path(path).read_text().strip()
    ROOT.joinpath('manifests/ace-cuda-probe.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in record.items() if k!='packages'}),flush=True)


if __name__ == '__main__':
    main()
