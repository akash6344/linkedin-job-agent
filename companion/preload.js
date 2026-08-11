const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("companion", {
  getState: () => ipcRenderer.invoke("get-state"),
  login: (email, password) => ipcRenderer.invoke("login", { email, password }),
  connectLinkedIn: () => ipcRenderer.invoke("connect-linkedin"),
  search: () => ipcRenderer.invoke("search"),
  openDashboard: () => ipcRenderer.invoke("open-dashboard"),
  openHelp: () => ipcRenderer.invoke("open-download-help"),
});
