# Safety

This project is public-market-data research software.

Hard defaults:

```env
LIVE_TRADING_ENABLED=false
PRIVATE_API_ENABLED=false
REQUIRE_MANUAL_APPROVAL=true
NOTIFICATIONS_ENABLED=false
TELEGRAM_ENABLED=false
DISCORD_WEBHOOK_ENABLED=false
```

Unsafe modes fail closed during config validation. There is no live trading code path in the MVP.

The exchange safety guard uses explicit allowlists. Unknown endpoints are rejected by default.
Private, account, execution, funding, deposit, and withdrawal paths are not part of the client
interfaces.

Secrets:

- No private exchange keys are needed.
- Telegram tokens and Discord webhook URLs are treated as secrets.
- `.env` is ignored.
- Logging redacts Telegram and Discord secrets.

Research wording:

- Outputs use candidate, watchlist, score, drivers, and risk flags.
- Outputs must not claim certainty or profit prediction.
- Alerts include: `Research alert only. Not financial advice. No order was placed.`

Repository governance:

- Configure GitHub branch protection or a ruleset for `main`.
- Require the `test` GitHub Actions job.
- Require pull requests and at least one review.
- Disable force pushes and branch deletions.
- Apply the rule to administrators when practical.
- Consider signed commits if this repository is shared beyond a private research workflow.
