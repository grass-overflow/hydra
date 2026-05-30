import { useEffect, useRef } from 'react';
import { createChart } from 'lightweight-charts';

const baseChartOptions = {
  layout: {
    textColor: '#172554',
    fontFamily: '"Space Grotesk", "Segoe UI", sans-serif',
  },
  grid: {
    vertLines: { color: 'rgba(23, 37, 84, 0.08)' },
    horzLines: { color: 'rgba(23, 37, 84, 0.08)' },
  },
  crosshair: {
    vertLine: { color: 'rgba(14, 116, 144, 0.35)' },
    horzLine: { color: 'rgba(14, 116, 144, 0.35)' },
  },
  rightPriceScale: {
    borderColor: 'rgba(23, 37, 84, 0.15)',
  },
  timeScale: {
    borderColor: 'rgba(23, 37, 84, 0.15)',
    timeVisible: true,
    secondsVisible: false,
  },
};

function makeChartOptions(backgroundColor) {
  return {
    ...baseChartOptions,
    layout: {
      ...baseChartOptions.layout,
      background: { color: backgroundColor },
    },
  };
}

const priceChartOptions = makeChartOptions('#fffdf8');
const movingAverageChartOptions = makeChartOptions('#f8fafc');
const volumeChartOptions = makeChartOptions('#f0fdfa');
const indicatorChartOptions = makeChartOptions('#fff7ed');

function syncVisibleRange(sourceChart, targetCharts) {
  let isSyncing = false;

  sourceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    if (isSyncing || range === null) {
      return;
    }

    isSyncing = true;
    targetCharts.forEach((chart) => {
      chart.timeScale().setVisibleLogicalRange(range);
    });
    isSyncing = false;
  });
}

export default function StockChart({ data }) {
  const priceContainerRef = useRef(null);
  const movingAverageContainerRef = useRef(null);
  const volumeContainerRef = useRef(null);
  const indicatorContainerRef = useRef(null);

  useEffect(() => {
    if (
      !data ||
      !priceContainerRef.current ||
      !movingAverageContainerRef.current ||
      !volumeContainerRef.current ||
      !indicatorContainerRef.current
    ) {
      return undefined;
    }

    const priceChart = createChart(priceContainerRef.current, {
      ...priceChartOptions,
      width: priceContainerRef.current.clientWidth,
      height: 320,
    });

    const movingAverageChart = createChart(movingAverageContainerRef.current, {
      ...movingAverageChartOptions,
      width: movingAverageContainerRef.current.clientWidth,
      height: 180,
    });

    const volumeChart = createChart(volumeContainerRef.current, {
      ...volumeChartOptions,
      width: volumeContainerRef.current.clientWidth,
      height: 140,
    });

    const indicatorChart = createChart(indicatorContainerRef.current, {
      ...indicatorChartOptions,
      width: indicatorContainerRef.current.clientWidth,
      height: 180,
    });

    const allCharts = [priceChart, movingAverageChart, volumeChart, indicatorChart];

    const candleSeries = priceChart.addCandlestickSeries({
      upColor: '#0f766e',
      downColor: '#be185d',
      borderUpColor: '#0f766e',
      borderDownColor: '#be185d',
      wickUpColor: '#0f766e',
      wickDownColor: '#be185d',
    });
    candleSeries.setData(data.candles);

    const sma20Series = movingAverageChart.addLineSeries({
      color: '#0284c7',
      lineWidth: 2,
      title: 'SMA 20',
    });
    sma20Series.setData(data.indicators.sma_20);

    const sma50Series = movingAverageChart.addLineSeries({
      color: '#f97316',
      lineWidth: 2,
      title: 'SMA 50',
    });
    sma50Series.setData(data.indicators.sma_50);

    const volumeSeries = volumeChart.addHistogramSeries({
      priceFormat: { type: 'volume' },
    });
    volumeSeries.setData(data.volume);

    const volatilitySeries = indicatorChart.addLineSeries({
      color: '#7c3aed',
      lineWidth: 2,
      title: 'EWM Volatility',
    });
    volatilitySeries.setData(data.indicators.volatility_ewm);

    syncVisibleRange(priceChart, [movingAverageChart, volumeChart, indicatorChart]);
    syncVisibleRange(movingAverageChart, [priceChart, volumeChart, indicatorChart]);
    syncVisibleRange(volumeChart, [priceChart, movingAverageChart, indicatorChart]);
    syncVisibleRange(indicatorChart, [priceChart, movingAverageChart, volumeChart]);

    allCharts.forEach((chart) => chart.timeScale().fitContent());

    const resizeObserver = new ResizeObserver(() => {
      if (
        !priceContainerRef.current ||
        !movingAverageContainerRef.current ||
        !volumeContainerRef.current ||
        !indicatorContainerRef.current
      ) {
        return;
      }

      priceChart.applyOptions({ width: priceContainerRef.current.clientWidth });
      movingAverageChart.applyOptions({ width: movingAverageContainerRef.current.clientWidth });
      volumeChart.applyOptions({ width: volumeContainerRef.current.clientWidth });
      indicatorChart.applyOptions({ width: indicatorContainerRef.current.clientWidth });
    });

    resizeObserver.observe(priceContainerRef.current);
    resizeObserver.observe(movingAverageContainerRef.current);
    resizeObserver.observe(volumeContainerRef.current);
    resizeObserver.observe(indicatorContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      allCharts.forEach((chart) => chart.remove());
    };
  }, [data]);

  return (
    <div className="chart-shell">
      <section className="chart-card">
        <header className="chart-card-header">Candlesticks</header>
        <div ref={priceContainerRef} className="chart-panel price-panel" />
      </section>
      <section className="chart-card">
        <header className="chart-card-header">Simple Moving Averages</header>
        <div ref={movingAverageContainerRef} className="chart-panel moving-average-panel" />
      </section>
      <section className="chart-card">
        <header className="chart-card-header">Volume Bars</header>
        <div ref={volumeContainerRef} className="chart-panel volume-panel" />
      </section>
      <section className="chart-card">
        <header className="chart-card-header">Exponential Volatility</header>
        <div ref={indicatorContainerRef} className="chart-panel indicator-panel" />
      </section>
    </div>
  );
}
