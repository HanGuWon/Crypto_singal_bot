# GCP Free-Tier Deployment Profile

This is a conservative deployment note for the public-data research screener. It is not financial
advice, it does not add trading, and it does not require private exchange keys.

The profile in `configs/gcp_free_tier.yaml` is disabled by default and is intended as an operations
reference, not as runtime configuration automatically loaded by the app.

## Current Free-Tier Facts Checked

As of June 10, 2026, Google Cloud's Free Tier documentation lists Compute Engine Always Free usage
for one non-preemptible `e2-micro` VM per month in these regions only:

- `us-west1`
- `us-central1`
- `us-east1`

The same page lists 30 GB-months standard persistent disk and 1 GB outbound transfer from North
America to most destinations. It does not list Seoul (`asia-northeast3`) as an Always Free Compute
Engine region.

Relevant official pages:

- [Google Cloud Free Tier](https://docs.cloud.google.com/free/docs/free-cloud-features)
- [Cloud Scheduler pricing](https://cloud.google.com/scheduler/pricing)
- [Cloud Run pricing](https://cloud.google.com/run/pricing)
- [Secret Manager pricing](https://cloud.google.com/secret-manager/pricing)

Always check current billing pages before creating resources.

## Recommended MVP Shape

Use a small VM first:

```text
Compute Engine e2-micro
Region: us-central1, us-west1, or us-east1
Disk: 30 GB pd-standard
OS: Debian 12
Storage: SQLite on persistent disk
Scheduler: systemd timers
Notifications: disabled by default
```

Keep the workload small:

- REST polling only.
- No WebSocket process.
- No dashboard.
- Maximum 60 symbols per exchange.
- Maximum 10 orderbook symbols.
- Orderbook polling no more frequent than 300 seconds.
- 1m/3m candles only for a small confirmation universe.
- Backtests run manually, not on every timer.

## VM Install Sketch

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin crypto-signal-bot
sudo mkdir -p /opt/crypto_signal_bot
sudo chown crypto-signal-bot:crypto-signal-bot /opt/crypto_signal_bot
```

Clone the repository under `/opt/crypto_signal_bot`, create a virtual environment, and install:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp .env.example .env
chmod 600 .env
```

Keep these defaults unless you intentionally review cost and safety:

```env
LIVE_TRADING_ENABLED=false
PRIVATE_API_ENABLED=false
NOTIFICATIONS_ENABLED=false
EXIT_GUARD_ENABLED=false
EXIT_GUARD_PRIVATE_READ_ENABLED=false
EXIT_GUARD_LIVE_EXIT_ENABLED=false
```

## Systemd Examples

Example files are in `scripts/systemd/`:

- `crypto-signal-bot-collect.service`
- `crypto-signal-bot-collect.timer`
- `crypto-signal-bot-rank.service`
- `crypto-signal-bot-rank.timer`
- `crypto-signal-bot-db-backup.service`
- `crypto-signal-bot-db-backup.timer`

Install examples:

```bash
sudo cp scripts/systemd/crypto-signal-bot-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-signal-bot-collect.timer
sudo systemctl enable --now crypto-signal-bot-rank.timer
sudo systemctl enable --now crypto-signal-bot-db-backup.timer
```

## Backups And Logs

The backup helper at `scripts/sqlite_backup.sh` writes compressed SQLite backups and removes old
backup files after `BACKUP_KEEP_DAYS`.

The logrotate example at `scripts/logrotate/crypto_signal_bot` assumes file logs under
`/opt/crypto_signal_bot/logs/*.log`. If you rely only on journald, logrotate is optional.

## Cloud Run Note

Cloud Run Jobs can fit small scheduled workloads, and Google publishes examples where modest hourly
jobs remain inside free allocations. This repository currently uses a local SQLite file, so a Cloud
Run deployment should first move persistence to a durable external storage design. The VM profile is
the simpler first deployment.

## Secret Manager Note

Secret Manager has free monthly limits, but frequent scheduled reads can consume access operations.
For the VM profile, a `chmod 600 .env` file is the simplest disabled-notification setup. If
Telegram or Discord is enabled later, use billing alerts and keep webhook/token values out of logs.
