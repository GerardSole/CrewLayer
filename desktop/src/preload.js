'use strict';

const { contextBridge, ipcRenderer } = require('electron');

const invoke = (ch, ...args) => ipcRenderer.invoke(ch, ...args);

const listen = (ch, cb) => {
  const handler = (_, data) => cb(data);
  ipcRenderer.on(ch, handler);
  return () => ipcRenderer.removeListener(ch, handler);
};

contextBridge.exposeInMainWorld('cl', {
  // ── Settings ──────────────────────────────────────────────────────────
  getSettings:    ()      => invoke('get-settings'),
  saveSettings:   (patch) => invoke('save-settings', patch),

  // ── Clipboard ─────────────────────────────────────────────────────────
  copy: (text) => invoke('copy-text', text),

  // ── Navigation / windows ─────────────────────────────────────────────
  openExternal:    (url) => invoke('open-external', url),
  openSettings:    ()    => invoke('open-settings'),
  openDashboard:   ()    => invoke('open-dashboard'),
  reloadDashboard: ()    => invoke('reload-dashboard'),
  minimizeToTray:  ()    => invoke('minimize-to-tray'),
  closeWindow:     ()    => invoke('close-window'),

  // ── Services ──────────────────────────────────────────────────────────
  getStatus:       ()    => invoke('service-status'),
  restartServices: ()    => invoke('restart-services'),
  resetData:       ()    => invoke('reset-data'),

  // ── Updates ───────────────────────────────────────────────────────────
  checkUpdates: () => invoke('check-updates'),

  // ── Events ────────────────────────────────────────────────────────────
  onProgress: (cb) => listen('startup-progress', cb),
  onStatus:   (cb) => listen('service-status', cb),
  onUpdate:   (cb) => listen('update-available', cb),
});
