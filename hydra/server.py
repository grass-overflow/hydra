import logging
import time
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from container_metrics import CgroupCpuCollector, CgroupMemoryCollector
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from prometheus_client import REGISTRY, Histogram, make_asgi_app

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("hydra")

# Silence noisy third-party loggers that would otherwise flood DEBUG output
logging.getLogger("yfinance").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("peewee").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = FastAPI(title="Hydra Service")
templates = Jinja2Templates(directory="templates")

HTTP_REQUEST_LATENCY = Histogram(
    "hydra_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0],
)

REGISTRY.register(CgroupCpuCollector())
REGISTRY.register(CgroupMemoryCollector())

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# ---------------------------------------------------------------------------
# Function to properly format response
# ---------------------------------------------------------------------------
def get_candle_data(symbol: str, period: str = "1d", interval: str = "60m") -> dict:
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=interval)

    if df.empty:
        raise ValueError(f"No data returned for {symbol}")

    # ── Indicators ────────────────────────────────────────────────────────────
    sma_20, sma_50, volatility_ewm = [], [], []

    if len(df) >= 20:
        sma = df["Close"].rolling(20).mean()
        sma_20 = [
            {"time": int(ts.timestamp()), "value": round(v, 4)}
            for ts, v in zip(df.index, sma)
            if not np.isnan(v)
        ]

    if len(df) >= 50:
        sma = df["Close"].rolling(50).mean()
        sma_50 = [
            {"time": int(ts.timestamp()), "value": round(v, 4)}
            for ts, v in zip(df.index, sma)
            if not np.isnan(v)
        ]

    if len(df) >= 2:
        ewm_vol = df["Close"].pct_change().ewm(span=20).std() * np.sqrt(252)
        volatility_ewm = [
            {"time": int(ts.timestamp()), "value": round(v, 6)}
            for ts, v in zip(df.index, ewm_vol)
            if not np.isnan(v)
        ]

    # ── Candles & Volume ──────────────────────────────────────────────────────
    candles, volume = [], []

    for ts, row in df.iterrows():
        t = int(ts.timestamp())
        is_green = row["Close"] >= row["Open"]
        color = "rgba(15, 118, 110, 0.45)" if is_green else "rgba(190, 24, 93, 0.45)"

        candles.append(
            {
                "time": t,
                "open": round(row["Open"], 4),
                "high": round(row["High"], 4),
                "low": round(row["Low"], 4),
                "close": round(row["Close"], 4),
            }
        )

        volume.append(
            {
                "time": t,
                "value": row["Volume"],
                "color": color,
            }
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    last_close = round(df["Close"].iloc[-1], 4)
    first_close = round(df["Close"].iloc[0], 4)
    abs_change = round(last_close - first_close, 4)
    pct_change = round((abs_change / first_close) * 100, 4) if first_close else None

    summary = {
        "lastClose": last_close,
        "absoluteChange": abs_change,
        "percentChange": pct_change,
        "sma20": sma_20[-1]["value"] if sma_20 else None,
        "sma50": sma_50[-1]["value"] if sma_50 else None,
        "volatilityEwmAnnualized": volatility_ewm[-1]["value"]
        if volatility_ewm
        else None,
        "latestTimestamp": candles[-1]["time"],
    }

    return {
        "symbol": symbol.upper(),
        "period": period,
        "interval": interval,
        "points": len(candles),
        "candles": candles,
        "volume": volume,
        "indicators": {
            "sma_20": sma_20,
            "sma_50": sma_50,
            "volatility_ewm": volatility_ewm,
        },
        "summary": summary,
        "meta": {
            "cached": False,
            "stale": False,
            "sourceError": None,
            "requestedInterval": interval,
            "sourceInterval": interval,
            "derived": False,
        },
    }


# ---------------------------------------------------------------------------
# Request / response logging middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()

    logger.info(
        "Incoming request | id=%s method=%s path=%s query=%s client=%s",
        request_id,
        request.method,
        request.url.path,
        str(request.query_params) or "-",
        request.client.host if request.client else "unknown",
    )
    logger.debug("Headers | id=%s headers=%s", request_id, dict(request.headers))

    response: Response = await call_next(request)

    elapsed_ms = (time.perf_counter() - start) * 1000
    log_fn = logger.warning if response.status_code >= 400 else logger.info
    log_fn(
        "Completed request | id=%s method=%s path=%s status=%d duration=%.2fms",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    HTTP_REQUEST_LATENCY.labels(
        method=request.method, endpoint=request.url.path
    ).observe(elapsed_ms)

    # Attach request-id to response headers for traceability
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    logger.debug("Health check requested")
    try:
        ticker = yf.Ticker("AAPL")
        _ = ticker.fast_info
        logger.debug("Health check: Success")
        return {"status": "OK"}
    except Exception:
        logger.error("Health check: Failed. Yahoo Finance Unreachable")
        raise HTTPException(status_code=503, detail="Yahoo Finance Unreachable")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    logger.debug("Serving index page")
    return templates.TemplateResponse(name="index.html", request=request)


@app.get("/data")
# @HTTP_REQUEST_LATENCY.labels(method="GET", endpoint="/data").time()
def get_stock_data(
    ticker: str = Query(default="GOOGL"),
    period: str = Query(default="1d"),
    interval: str = Query(default="60m"),
):
    logger.info(
        "Fetching stock data | ticker=%s, period=%s, interval=%s",
        ticker,
        period,
        interval,
    )

    try:
        payload = get_candle_data(ticker, period, interval)
        logger.debug("Full payload | ticker=%s payload=%s", ticker, payload)
        return payload

    except HTTPException:
        raise  # already logged above
    except Exception as e:
        logger.exception(
            "Unhandled error fetching stock data | ticker=%s error=%s", ticker, e
        )
        raise HTTPException(
            status_code=503, detail=f"Failed to fetch data from Yahoo Finance: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=80, log_level="info")
