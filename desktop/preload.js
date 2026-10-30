'use strict';
// The only things the page can reach. No Node, no file reads: paths come from the dropped File objects.
const { contextBridge, ipcRenderer, webUtils } = require('electron');

contextBridge.exposeInMainWorld('lip', {
  // Test hook only: the smoke test can run its mock on another port while the real backend owns 8780.
  api: 'http://127.0.0.1:' + (/^\d{4,5}$/.test(process.env.LIP_TEST_PORT || '') ? process.env.LIP_TEST_PORT : '8780'),
  token: process.env.LIPSERVICE_TOKEN || '',
  pathFor: (file) => webUtils.getPathForFile(file),
  windowControl: (action) => ipcRenderer.invoke('lip:window', action),
});
