# 🧠 Nifty Live Arbitrage & Dashboard - AI Digital Brain

> **To any AI Model reading this file:** 
> This is the central context document (Digital Brain) for this project. Read this to immediately understand the project architecture, tech stack, business logic, and coding conventions without needing to scan all the code.

## 📌 Project Overview
This project is an advanced **Live Arbitrage Tracking Dashboard & Options Scanner** tailored for the Indian Stock Market (NSE/BSE/NFO). It uses the Angel One API to fetch real-time and historical options data. 
The core objective is to identify trading opportunities by comparing the **Synthetic Future** price with the actual **Spot/Future** price, calculating the **Premium or Discount (P/D)**.

### Core Mathematical Logic:
- **Synthetic Future** = `ATM Strike + Call Premium - Put Premium`
- **Premium/Discount (P/D)** = `Synthetic Future - Underlying Spot Price`
  - If P/D > 0: Trading at a Premium (Call side is expensive).
  - If P/D < 0: Trading at a Discount (Put side is expensive).

---

## 🛠 Tech Stack
- **Backend:** Python (FastAPI, Requests, asyncio).
- **Frontend:** Vanilla HTML, CSS, JavaScript (No heavy frameworks like React/Vue).
- **Styling:** Custom Vanilla CSS (Dark mode, glassmorphism, dynamic colors).
- **Data Persistence:** `localStorage` for the frontend (Trade book, history), static JSON caching (`instruments.json`).
- **Charts:** Chart.js (used extensively for time-series and scatter plots).

---

## 🏗 Architecture & Key Files

### 1. Backend (`/nifty-calc-backend/`)
- **`main.py`**: The primary FastAPI server running on port `8000`. Handles Angel One API login, caching the instrument master list (`instruments.json`), and serves API endpoints for synthetic calculations.
- **`scanner_backend.py`**: A dedicated, optimized high-speed scanner API running on port `8001`. Used specifically to quickly scan large batches of stocks to find P/D differences and IVs without blocking the main calc server.
- **`calc.py`**: A robust fallback/utility backend script containing caching layers, rate-limit handlers, and batch quote logic.

### 2. Frontend Dashboards
- **`index.html` (Live Calc / Dashboard):**
  - Tracks up to 3 instruments concurrently in "boxes".
  - Continuously polls the backend for live data every ~3 seconds.
  - Maintains a **Live Trade Logger** (stored in `localStorage` under `tradeBook`), calculating real-time PnL.
  - Includes an **Alert System** that triggers a sound/notification when the P/D *crosses* a specific target from its starting value.
- **`scanner.html` (Market Scanner):**
  - Scans multiple custom stock symbols to quickly highlight Premium/Discount opportunities.
  - Has an auto-scan feature (every 30 mins) with CSV export.
  - Clicking a row opens a "Detail Panel" with live P/D tracking chart.
- **`historical_pd.html` & `historical.html`:**
  - Used for historical market analysis over past days.
  - Features gapless categorical X-axes (filtering out non-market hours) for TradingView-style charts.
- **`position_calculator.html`:**
  - A standalone simulated PnL calculator to analyze entry/exit scenarios based on Spot, CE, and PE.
- **`analyzer.html`:**
  - Scatter plots and advanced analytics for IV and P/D spreads.

---

## ⚙️ Key System Rules & Constraints

1. **Market Hours Enforcement:**
   - Indian standard trading hours are **09:15:00 to 15:30:00**.
   - Data gathering functions (pushing data to charts and `localStorage` in `index.html` and `scanner.html`) are strictly hardcoded to only run between `09:14:50` and `15:30:30`.
   - Time validation is usually done using seconds since midnight (`timeInSec >= 33290 && timeInSec <= 55830`).

2. **API Rate Limiting:**
   - Angel One API rate limits are extremely strict.
   - We utilize a persistent `requests.Session()`, Thread Locks (`api_lock`), and mandatory delays (e.g., waiting 0.35s - 0.5s between calls) to avoid HTTP 429 (Too Many Requests) errors. 
   - Batch fetching (`mode: FULL` or `LTP` with up to 25-30 tokens) is used wherever possible.

3. **Trade Logging Math:**
   - If going **LONG**: 
     - Spot PnL = `(Entry Spot - Current Spot) * Qty`
     - Call PnL = `(Current Call - Entry Call) * Qty`
     - Put PnL = `(Entry Put - Current Put) * Qty`
   - If going **SHORT**:
     - Reversed respectively.

4. **Alert System Logic (`index.html`):**
   - Alerts do not trigger immediately just because the value is currently beyond the threshold. 
   - It captures the `initial` difference when the alert is set, and waits for the live value to **cross** the target.

---

## 🚀 How to Help Me (To the AI)
When working on this project:
1. **Don't break the CSS:** The UI design relies heavily on carefully crafted vanilla CSS (flexbox, grid, glassmorphism). Keep the aesthetic premium.
2. **Handle API Rate Limits:** If you are adding backend fetch logic, ensure it routes through batched functions or respects the global lock/rate-limiter.
3. **Respect Market Hours:** Any new historical arrays or chart updates should respect the `09:15-15:30` window.
4. **Assume `localStorage`:** We rely on `localStorage` to save state. Always handle `JSON.parse` errors gracefully and provide fallback data arrays.

---

## 📝 Developer Notes & Roadmap
*(Add any personal thoughts, tasks, or features you plan to build here)*
- [ ] Explore WebSockets for Angel One to replace the HTTP polling loop for real-time data.
- [ ] Refine the Mobile App counterpart (`/nifty-mobile-app/`).
- [ ] Add advanced Greeks (Delta, Theta, Gamma) to `scanner.html`.

---

## 📚 Recent AI Conversation History & Milestones
*This section provides context on what has recently been implemented in this repository.*

- **Tracking Daily Trade Performance:** Implemented seamless workflow for trade analysis by adding a "Calculate" button to closed trades in the daily trade list. This opens `position_calculator.html` in a new tab, auto-populating entry and exit data for immediate performance review.
- **Building A Mobile Application (Nifty Live Arbitrage Tracker):** Enhanced live arbitrage monitoring with concurrent trade support, real-time P/L updates in trade history, and visible P/D tracking at entry. Updated UI to display persistent entry parameters and dynamic P/L calculations.
- **Integrating Trade Logs Dashboard:** Integrated a daily trade logging system displaying active and closed trades below P/D charts. Appended these trade details to CSV exports for comprehensive records.
- **Building Position P&L Calculator:** Created a comprehensive Trade Logger system recording timestamps, symbols, strike prices, and P/L data. Added local storage persistence and CSV export functionality.
- **Adding Spot-Future Difference Tooltips:** Calculated and displayed the difference (spread) between Spot price and Real Future price within the `historical.html` chart hover tooltips.
- **Comparing Synthetic And Real Futures (P/D Chart Analytics):** Developed `historical_pd.html` page to compare Synthetic and Real Future P/D data. Added custom ATM strike overrides, spot price data in tooltips, and gapless time-series data rendering.
- **Creating Historical Expiry Chart:** Optimized historical intraday charting (`historical.html`) with gapless categorical X-axis, TradingView-style ticks, strict market-hour filtering (09:15-15:30), and CSV export for multi-day analysis.
- **Restricting Data Gathering Times:** Locked automated chart/history data gathering across the app to strictly trigger only between `09:14:50` and `15:30:30`.
- **Cross-Trigger Alert Logic:** Fixed P/D alerting so it checks the initial difference on creation and only fires an alert when the value *crosses* the target threshold.
