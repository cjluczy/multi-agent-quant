# Real Data And Realtime Skeleton

This project now supports two practical market-data entry paths:

1. `csv_replay`: import real market data exported from your vendor or broker
2. `tushare_realtime`: poll realtime quotes from Tushare and drive the event loop

## What Is Already Real

- market feed can come from real CSV rows
- market feed can come from Tushare realtime polling
- runtime loop, portfolio allocation, risk, paper execution, NAV, deweighting, and dashboard outputs are shared with the simulation path

## What Is Still Skeleton

- fundamental feed is still static
- sentiment feed is still static
- execution is still paper trading, not broker routing

That means the system is now suitable for:

- realtime paper trading
- intraday research and monitoring
- live NAV / deweight / ablation observation after a run

It is not yet suitable for:

- unattended real-money execution

## Path A: Import Real CSV Data

Prepare a CSV file with at least these columns:

```csv
symbol,price,volume
510300.SH,3.86,100000
510300.SH,3.88,120000
600519.SH,1490.20,3200
```

Then point the market feed config at that file:

```yaml
feeds:
  market:
    type: csv_replay
    path: data/real_market_ticks.csv
    symbol_field: symbol
    price_field: price
    volume_field: volume
```

Run it with:

```powershell
python scripts\run_simulation.py --config configs\system.csv-replay.example.yaml
```

## Path B: Tushare Realtime

Install dependency:

```powershell
pip install tushare
```

Set token:

```powershell
$env:TUSHARE_TOKEN="your-token"
```

Run realtime mode:

```powershell
python scripts\run_realtime.py --config configs\system.tushare.local.yaml
```

Recommended local config:

- `configs/system.tushare.local.yaml`

The console now distinguishes three Tushare states:

1. `直连可用`: Tushare package + token are both ready
2. `回退可用`: direct Tushare path is incomplete, but runtime can fall back to EasyQuotation
3. `未就绪`: neither direct Tushare nor fallback path is ready

## Path C: Free Realtime With EasyQuotation

This path does not require a Tushare token.

Check environment:

```powershell
python scripts\check_realtime_env.py --config configs\system.easyquotation.example.yaml
```

Probe a few normalized ticks before running the whole system:

```powershell
python scripts\probe_market_feed.py --config configs\system.easyquotation.example.yaml --count 3
```

Run realtime mode:

```powershell
python scripts\run_realtime.py --config configs\system.easyquotation.example.yaml
```

## Recommended First Production Step

For a real usable V1, start with this sequence:

1. export real market data to CSV and verify strategy/risk behavior
2. switch market feed to `tushare_realtime`
3. keep execution in paper mode
4. add alerting and operator confirmation before any broker integration
