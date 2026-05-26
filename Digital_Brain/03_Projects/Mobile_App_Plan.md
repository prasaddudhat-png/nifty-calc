# 📱 Mobile App Integration Plan

**Status:** Draft
**Target:** React Native / Expo application linking to our FastAPI backend.

## Overview
We have a `/nifty-mobile-app/` folder containing a basic `App.js` with a WebView. The goal is to create a fully native dashboard for tracking live arbitrage boxes on the go.

## Current State
- `App.js` currently wraps the web dashboard in a WebView.
- Styling is dark mode by default (`#1E1E1E`).
- Floating Action Button exists for actions.

## Next Steps
- [ ] Implement native WebSockets for faster data streaming than polling.
- [ ] Connect the native UI to the `scanner_backend.py` API endpoints directly (bypass WebView).
- [ ] Implement Push Notifications using Expo Notifications for the Cross-Target Alert system.

## References
- [[AI_BRAIN]]
- [[API_Integration_Template]]
