import { startTransition, useEffect, useState } from 'react';
import StockChart from './StockChart';

const INTERVAL_OPTIONS = ['10s', '30s', '1m', '5m', '10m', '30m', '60m', '2hrs'];
const PERIOD_OPTIONS_BY_INTERVAL = {
  '10s': ['1d', '5d'],
  '30s': ['1d', '5d'],
  '1m': ['1d', '5d'],
  '5m': ['1d', '5d', '1mo'],
  '10m': ['1d', '5d', '1mo'],
  '30m': ['1d', '5d', '1mo', '3mo'],
  '60m': ['1d', '5d', '1mo', '3mo', '6mo', '1y'],
  '2hrs': ['1d', '5d', '1mo', '3mo', '6mo', '1y'],
};
const REFRESH_INTERVAL_MS = 20_000;

function formatMetric(value, suffix = '') {
  if (value === null || value === undefined) {
    return 'Not enough data';
  }
  return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`;
}

function formatPercent(value) {
  if (value === null || value === undefined) {
    return 'Not enough data';
  }
  const sign = value >= 0 ? '+' : '';
  return `${sign}${Number(value).toFixed(2)}%`;
}

export default function App() {
  const [symbolInput, setSymbolInput] = useState('AAPL');
  const [symbol, setSymbol] = useState('AAPL');
  const [interval, setInterval] = useState('1m');
  const [period, setPeriod] = useState('1d');
  const [marketData, setMarketData] = useState(null);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(true);

  const periodOptions = PERIOD_OPTIONS_BY_INTERVAL[interval] ?? ['1d', '5d'];

  useEffect(() => {
    if (!periodOptions.includes(period)) {
      setPeriod(periodOptions[0]);
    }
  }, [interval, period, periodOptions]);

  useEffect(() => {
    let isActive = true;

    const load = async () => {
      setIsLoading(true);
      setError('');

      try {
        const response = await fetch(
          `/data?ticker=${encodeURIComponent(symbol)}&period=${period}&interval=${interval}`,
        );
        const payload = await response.json();
        console.log(payload);

        if (!response.ok) {
          throw new Error(payload.error || 'Unable to load stock data.');
        }

        if (isActive) {
          startTransition(() => {
            setMarketData(payload);
            setIsLoading(false);
          });
        }
      } catch (fetchError) {
        if (isActive) {
          startTransition(() => {
            setError(fetchError.message);
            setIsLoading(false);
          });
        }
      }
    };

    load();
    const pollingId = window.setInterval(load, REFRESH_INTERVAL_MS);

    return () => {
      isActive = false;
      window.clearInterval(pollingId);
    };
  }, [symbol, period, interval]);

  const summaryCards = !marketData?.summary
    ? []
    : [
        {
          label: 'Last Close',
          value: formatMetric(marketData.summary.lastClose),
        },
        {
          label: 'Session Change',
          value: `${formatMetric(marketData.summary.absoluteChange)} (${formatPercent(
            marketData.summary.percentChange,
          )})`,
        },
        {
          label: 'SMA 20',
          value: formatMetric(marketData.summary.sma20),
        },
        {
          label: 'SMA 50',
          value: formatMetric(marketData.summary.sma50),
        },
        {
          label: 'Exp. Volatility',
          value: formatMetric(marketData.summary.volatilityEwmAnnualized, '%'),
        },
      ];

  const handleSubmit = (event) => {
    event.preventDefault();
    setSymbol(symbolInput.trim().toUpperCase() || 'AAPL');
  };

  return (
    <main className="app-shell">
      <section className="hero">
        <div>
          <p className="eyebrow">IEEE NITK 2026</p>
          <h1>Project Hydra:<br></br>Live Stock Monitoring</h1>
          <p className="lede">
            Integrated a k8s backend with a React frontend, along with a trained RL agent to automatically recover from server failures.
          </p>
        </div>

        <form className="controls" onSubmit={handleSubmit}>
          <label>
            Symbol
            <input
              value={symbolInput}
              onChange={(event) => setSymbolInput(event.target.value.toUpperCase())}
              placeholder="AAPL"
            />
          </label>

          <label>
            Period
            <select value={period} onChange={(event) => setPeriod(event.target.value)}>
              {periodOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label>
            Interval
            <select value={interval} onChange={(event) => setInterval(event.target.value)}>
              {INTERVAL_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <button type="submit">Refresh Symbol</button>
        </form>
      </section>

      {error ? <section className="message error">{error}</section> : null}
      {marketData?.meta?.stale ? (
        <section className="message warning">
          Showing the most recent cached payload because Yahoo Finance throttled the latest request.
        </section>
      ) : null}
      {marketData?.meta?.derived ? (
        <section className="message warning">
          {marketData.interval} is being built from Yahoo Finance&apos;s{' '}
          {marketData.meta.sourceInterval} source feed.
        </section>
      ) : null}
      {isLoading ? <section className="message">Loading live market data...</section> : null}

      {marketData ? (
        <>
          <section className="summary-grid">
            {summaryCards.map((card) => (
              <article key={card.label} className="summary-card">
                <span>{card.label}</span>
                <strong>{card.value}</strong>
              </article>
            ))}
          </section>

          <section className="chart-section">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Ticker</p>
                <h2>
                  {marketData.symbol} · {marketData.period} / {marketData.interval}
                </h2>
              </div>
              <p>{marketData.points} datapoints from the backend RTSM feed</p>
            </div>
            <StockChart data={marketData} />
          </section>
        </>
      ) : null}
    </main>
  );
}
