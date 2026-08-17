# OpenMontage

**MANDATORY: Read `AGENT_GUIDE.md` before responding to ANY user message.**

Do not act on the user's request until you have read AGENT_GUIDE.md.
It contains routing rules that determine your first action based on what the user asked.
Skipping it WILL cause you to take the wrong action.

Fork-specific facts for this checkout — secrets, CI, branches — are below.

## This checkout is a fork, not upstream

`origin` is `fiorelorenzo/OpenMontage`, `upstream` is `calesthio/OpenMontage`. `main`
tracks `upstream/main` exactly and carries no local change: never push it there,
`upstream` is read-only. Lorenzo's own work lives on `feat/*` branches pushed to
`origin` (`feat/replicate-image-provider`, `feat/youtube-publisher`), merged locally
into `local/working` for day-to-day use — that branch is not pushed anywhere, so
don't expect to find it on GitHub.

There is no CI (`.github/` has no workflow, only `CODEOWNERS` and
`copilot-instructions.md`, both upstream's). `make lint` only `py_compile`s four
files under `tools/`; `make test` and `make test-contracts` run pytest but nothing
triggers them automatically. Treat any check as unrun until you run it yourself.

## Secrets a pipeline needs

`.env` and `.secrets/` are both gitignored and real in this checkout: `.env` holds
live API keys for the eighteen providers in `.env.example` (video, image, TTS,
music), and `.secrets/youtube/` holds an OAuth client (`client_secret.json`) plus a
refresh token per channel (`informatizzato.json`, `deepinbusiness.json`), minted by
`scripts/youtube_auth.py` and consumed by `tools/publishers/youtube_upload.py`. `make
setup` copies `.env.example` to `.env` if missing, but it does not and cannot create
`.secrets/youtube/` — that needs a real Google Cloud OAuth client and a manual
consent flow per channel. A fresh worktree therefore starts with no working
providers and no YouTube publish path; don't assume either works, and never commit
anything under `.secrets/` or `.env` itself.

`config.yaml`'s `budget.mode` is `warn`, not `cap`: exceeding `budget.total_usd`
logs rather than blocks (`tools/cost_tracker.py`, `BudgetMode.CAP` is the only mode
that raises `BudgetExceededError`). The per-action and first-paid-tool approval
gates still raise in `warn` mode. Don't run a real pipeline against paid providers
expecting the total to be hard-capped at `$10.00`.
