'use strict';
// Edit-only menus. The application menu is never shown (the window is frameless); it exists so the
// Edit accelerators (Ctrl+Z, Ctrl+Y, Ctrl+X, Ctrl+C, Ctrl+V, Ctrl+A) are always registered.
// The right-click menu is for editable fields and for selected text.

function editMenuTemplate() {
  return [{
    label: 'Edit',
    submenu: [
      { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
      { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
    ],
  }];
}

// params comes from webContents 'context-menu'. Returns null when there is nothing to offer.
function contextTemplate(params) {
  const f = params.editFlags || {};
  if (params.isEditable) {
    return [
      { role: 'undo', enabled: f.canUndo !== false }, { role: 'redo', enabled: f.canRedo !== false }, { type: 'separator' },
      { role: 'cut', enabled: !!f.canCut }, { role: 'copy', enabled: !!f.canCopy }, { role: 'paste', enabled: !!f.canPaste },
      { type: 'separator' }, { role: 'selectAll', enabled: !!f.canSelectAll },
    ];
  }
  if (params.selectionText) return [{ role: 'copy' }, { type: 'separator' }, { role: 'selectAll' }];
  return null;
}

module.exports = { editMenuTemplate, contextTemplate };
