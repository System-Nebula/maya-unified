---
title: Launch Entrypoint
tags: [apps, launch]
aliases: [launch.py]
---

# Launch Entrypoint

`launch.py` at the repo root:

```python
from services.paths import setup_paths, VOICE_RUNTIME
setup_paths()
load_env_files(ROOT / ".env", VOICE_RUNTIME / ".env")
from apps.gateway.main import run
run()
```

## Platform wrappers

- **Windows** — `launch.bat`
- **Unix** — `launch.sh`

Warns if not running inside project `.venv` when voice deps are expected.

See [[Architecture/Launch Flow]].

