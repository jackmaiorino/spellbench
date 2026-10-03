# Local Pages publication

When a hosted Pages job cannot obtain a runner, the repository owner can dispatch
`pages-local.yml` from reviewed `main`. It validates saved runs and builds the
static site, then uploads and deploys in the same job. It plays zero games and
uses the same Python, uv and action pins as the hosted workflow.

Register a temporary Windows x64 runner with only the custom label
`spellbench-pages-local`, using `--no-default-labels --ephemeral`. Run it in its
own scratch directory, without a persistent service or model credentials in its
environment. Put Git for Windows Bash and GNU tar on its PATH for the Pages
artifact action. Verify the runner archive against the SHA-256 returned by
GitHub's authenticated runner-downloads API.

Dispatch the manual workflow only after its change has been reviewed and merged.
Cancel the superseded owned hosted Pages job if it holds the shared `pages`
concurrency group. The fallback admits only the repository owner's dispatch on
`main`; pull requests and ordinary CI do not target its label. The job times out
after 20 minutes. GitHub automatically unregisters an ephemeral runner after its
one job; verify that its listener has exited and its registration is gone.

After deployment, verify the live leaderboard and canonical run-file hashes.
A successful workflow alone does not confirm those contents. Preserve runner
diagnostics and small publication receipts; never put runner credentials in Git.
