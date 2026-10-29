// Handle the toolbar gesture explicitly: Chrome grants activeTab when this
// action is invoked. Opening the panel from its menu alone is not that gesture.
chrome.action.onClicked.addListener((tab) => {
  if (typeof tab.windowId !== "number") return;
  chrome.sidePanel.open({ windowId: tab.windowId }).catch(console.error);
});

// Also resets the setting persisted by earlier VozForm versions.
chrome.sidePanel
  .setPanelBehavior({ openPanelOnActionClick: false })
  .catch(console.error);
