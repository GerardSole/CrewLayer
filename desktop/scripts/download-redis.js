#!/usr/bin/env node
/**
 * Downloads Redis 7 static binaries for all supported platforms.
 * Saves them to desktop/resources/redis/{platform}/redis-server[.exe]
 *
 * Sources:
 *   Mac arm64/x64 — https://github.com/redis/redis (compiled static)
 *   Linux x64     — official Redis releases
 *   Windows x64   — https://github.com/tporadowski/redis/releases
 *
 * Run: node scripts/download-redis.js [--platform mac-arm64|mac-x64|linux-x64|win-x64]
 */

'use strict';

const fs    = require('fs');
const path  = require('path');
const https = require('https');
const { execSync } = require('child_process');

const OUT_DIR = path.join(__dirname, '..', 'resources', 'redis');

// Redis 7 static binary URLs — update these when releasing a new version
const SOURCES = {
  'mac-arm64': {
    url: 'https://github.com/redis/redis/releases/download/7.2.4/redis-7.2.4-macos-arm64.tar.gz',
    archive: 'redis.tar.gz',
    binPath: 'redis-7.2.4/src/redis-server',
    outName: 'redis-server',
  },
  'mac-x64': {
    url: 'https://github.com/redis/redis/releases/download/7.2.4/redis-7.2.4-macos-x86_64.tar.gz',
    archive: 'redis.tar.gz',
    binPath: 'redis-7.2.4/src/redis-server',
    outName: 'redis-server',
  },
  'linux-x64': {
    url: 'https://github.com/redis/redis/releases/download/7.2.4/redis-7.2.4.tar.gz',
    archive: 'redis.tar.gz',
    binPath: 'redis-7.2.4/src/redis-server',
    outName: 'redis-server',
    buildFromSource: true,
  },
  'win-x64': {
    url: 'https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip',
    archive: 'redis.zip',
    binPath: 'redis-server.exe',
    outName: 'redis-server.exe',
  },
};

const args = process.argv.slice(2);
const targetFlag = args.find(a => a.startsWith('--platform='));
const selectedPlatforms = targetFlag
  ? [targetFlag.split('=')[1]]
  : Object.keys(SOURCES);

// ── Helpers ────────────────────────────────────────────────────────────────

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    function get(u) {
      https.get(u, res => {
        if (res.statusCode === 301 || res.statusCode === 302) {
          return get(res.headers.location);
        }
        if (res.statusCode !== 200) {
          return reject(new Error(`HTTP ${res.statusCode} for ${u}`));
        }
        res.pipe(file);
        file.on('finish', () => { file.close(); resolve(); });
      }).on('error', reject);
    }
    get(url);
  });
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

async function downloadPlatform(platform) {
  const src = SOURCES[platform];
  if (!src) { console.error(`Unknown platform: ${platform}`); return; }

  const platformDir = path.join(OUT_DIR, platform);
  const outFile     = path.join(platformDir, src.outName);

  if (fs.existsSync(outFile)) {
    console.log(`[${platform}] Already exists — skipping (delete to re-download)`);
    return;
  }

  console.log(`[${platform}] Downloading Redis…`);
  ensureDir(platformDir);

  const tmpDir  = path.join(platformDir, '_tmp');
  ensureDir(tmpDir);
  const archive = path.join(tmpDir, src.archive);

  await download(src.url, archive);
  console.log(`[${platform}] Extracting…`);

  if (src.archive.endsWith('.tar.gz')) {
    if (src.buildFromSource) {
      // For Linux, we build from source in CI instead — just extract the archive
      execSync(`tar -xzf "${archive}" -C "${tmpDir}"`, { stdio: 'pipe' });
      const builtBin = path.join(tmpDir, src.binPath);
      if (fs.existsSync(builtBin)) {
        fs.copyFileSync(builtBin, outFile);
        fs.chmodSync(outFile, 0o755);
      } else {
        console.warn(`[${platform}] Binary not found after extraction: ${builtBin}`);
        console.warn(`[${platform}] For Linux, build Redis from source and copy the binary manually.`);
      }
    } else {
      execSync(`tar -xzf "${archive}" -C "${tmpDir}"`, { stdio: 'pipe' });
      const bin = path.join(tmpDir, src.binPath);
      fs.copyFileSync(bin, outFile);
      fs.chmodSync(outFile, 0o755);
    }
  } else if (src.archive.endsWith('.zip')) {
    if (process.platform === 'win32') {
      execSync(
        `powershell -NoProfile -Command "Expand-Archive -LiteralPath '${archive}' -DestinationPath '${tmpDir}' -Force"`,
        { stdio: 'pipe' },
      );
    } else {
      execSync(`unzip -o "${archive}" -d "${tmpDir}"`, { stdio: 'pipe' });
    }
    const bin = path.join(tmpDir, src.binPath);
    fs.copyFileSync(bin, outFile);
  }

  // Clean up tmp
  fs.rmSync(tmpDir, { recursive: true, force: true });
  console.log(`[${platform}] ✓  ${outFile}`);
}

// ── Main ───────────────────────────────────────────────────────────────────

(async () => {
  console.log(`Downloading Redis binaries for: ${selectedPlatforms.join(', ')}\n`);
  for (const p of selectedPlatforms) {
    try {
      await downloadPlatform(p);
    } catch (err) {
      console.error(`[${p}] Error: ${err.message}`);
    }
  }
  console.log('\nDone. Binaries saved to resources/redis/');
})();
