# CrewLayer Desktop

Native desktop app that bundles the entire CrewLayer stack — FastAPI backend, PostgreSQL, Redis, and the web dashboard — into a single installable app. No Docker, no terminal.

## Architecture

```
Electron main process
├── embedded-postgres  →  PostgreSQL 16 on port 5433
├── Redis binary       →  Redis 7 on port 6380
└── PyInstaller binary →  FastAPI on port 8000
                              └── BrowserView → /dashboard
```

All data is stored in the platform userData directory:
- **Mac:** `~/Library/Application Support/CrewLayer/data/`
- **Windows:** `%APPDATA%\CrewLayer\data\`
- **Linux:** `~/.config/CrewLayer/data/`

## Building from source

### 1. Install Node.js dependencies

```bash
cd desktop
npm install
```

### 2. Build the FastAPI backend

Run from the repo root (requires Python 3.12+ and the project installed):

```bash
pip install -e ".[dev]"
bash desktop/scripts/build-backend.sh
```

The script uses PyInstaller to create a single-file executable at `desktop/resources/backend/crewlayer-backend`.

> **Note:** Build the backend on each target OS — PyInstaller binaries are not cross-platform.

### 3. Download Redis binaries

```bash
cd desktop
npm run download-redis
```

Downloads Redis 7 static binaries for all platforms into `resources/redis/`:

```
resources/
└── redis/
    ├── mac-arm64/redis-server
    ├── mac-x64/redis-server
    ├── linux-x64/redis-server
    └── win-x64/redis-server.exe
```

To download for a single platform only:

```bash
node scripts/download-redis.js --platform=mac-arm64
```

> **Linux note:** Redis doesn't provide pre-built static binaries for Linux. Build from source on the target machine and copy the binary to `resources/redis/linux-x64/redis-server`.

### 4. Run in development mode

```bash
cd desktop
npm start
```

In dev mode, the app skips looking for Redis/backend binaries and assumes services are already running (e.g., via `docker compose up -d`).

### 5. Build distributable packages

```bash
# Current platform
npm run build

# Specific platform (must be on that OS or use CI)
npm run build:mac
npm run build:win
npm run build:linux
```

Output files go to `desktop/dist/`:
- **Mac:** `CrewLayer-universal.dmg`, `CrewLayer-universal-mac.zip`
- **Windows:** `CrewLayer-Setup-x64.exe`, `CrewLayer-Portable-x64.exe`
- **Linux:** `CrewLayer-x86_64.AppImage`, `CrewLayer-amd64.deb`

## Code signing

### macOS

Set these environment variables before building:

```bash
export CSC_LINK=/path/to/certificate.p12
export CSC_KEY_PASSWORD=your-password
# For notarization:
export APPLE_ID=your@apple.id
export APPLE_APP_SPECIFIC_PASSWORD=xxxx-xxxx-xxxx-xxxx
export APPLE_TEAM_ID=XXXXXXXXXX
```

Then build — electron-builder handles signing and notarization automatically.

### Windows

```bash
export CSC_LINK=/path/to/certificate.pfx
export CSC_KEY_PASSWORD=your-password
```

## Publishing a release (auto-update)

Auto-update reads from GitHub Releases. To publish:

1. Bump the version in `desktop/package.json`
2. Tag the commit: `git tag desktop-v1.0.1`
3. Build and publish: `npm run release`

This uploads the built artifacts to the GitHub Release for the tag. The auto-updater in running apps will detect the new release and notify users.

The `publish.provider: github` in `electron-builder.yml` points to `GerardSole/CrewLayer`.

## Required assets

Before building, add these icon files to `desktop/assets/`:

| File | Size | Used for |
|------|------|----------|
| `icon.icns` | macOS standard | Mac .app icon |
| `icon.ico`  | Windows standard | Windows installer icon |
| `icon.png`  | 512×512 px | Linux icon |
| `tray-icon.png` | 16×16 px (or `@2x` 32×32) | Menu bar / system tray |

For macOS, `tray-icon.png` should be a template image (black icon on transparent background) so it inverts correctly in dark mode.

## Icon

Generate platform icons from a single source PNG with:

```bash
# Install icon generator
npm install -g electron-icon-builder

# Generate all formats from a 1024×1024 source PNG
electron-icon-builder --input=source-icon.png --output=desktop/assets/
```

## Ports used

| Service | Port | Configurable |
|---------|------|-------------|
| FastAPI | 8000 | Yes — Settings panel |
| PostgreSQL | 5433 | No |
| Redis | 6380 | No |

Ports 5433 and 6380 are non-standard to avoid conflicts with existing local services.
