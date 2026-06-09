# macOS LaunchAgent

This folder contains scripts for running the FastAPI backend automatically when
the macOS user session starts.

Install:

```bash
.venv/bin/python backend/scripts/deploy/install_macos_launch_agent.py
```

Check status:

```bash
launchctl print gui/$(id -u)/com.stockcollect.backend
```

Stop and remove:

```bash
.venv/bin/python backend/scripts/deploy/uninstall_macos_launch_agent.py
```

Backend application logs rotate daily at `logs/backend/backend.log`. LaunchAgent
stdout/stderr are discarded to avoid unbounded log growth.
