# Termux fork — upstream sync procedure

This repository is the Termux/Android port of
[deepseek-ai/deepseek-harness](https://github.com/deepseek-ai/deepseek-harness).
It is **not** a GitHub fork: there is no shared object store and no
"Sync fork" button. The port is a set of named patchers in
[`scripts/patch_termux.py`](scripts/patch_termux.py) that rewrite upstream files,
so a sync is a replay of those patchers over a new upstream tree, not a merge
GitHub can perform for you.

```
upstream tree + patch_termux.py --apply = this repository
```

That relationship is the whole maintenance model. The tree here is upstream
plus the patched result, and the patcher is the only thing that carries the
Android changes forward.

## Two repositories, two roles

| Remote     | Repository                            | Role                                      |
| ---------- | ------------------------------------- | ----------------------------------------- |
| `upstream` | `deepseek-ai/deepseek-harness`        | merge source only — never pushed to        |
| `origin`   | `salmanbappi/deepseek-harness`        | the only published artifact and release source |

Devices never contact `upstream`. `scripts/install-termux.sh` resolves the
release, the tarball, and its own self-refetch from `origin` only, and no `dsh`
subcommand or timer performs an update check. A device changes version only
when `origin` publishes a new release.

## Publishing a new upstream version

[`scripts/dsh-update.sh`](scripts/dsh-update.sh) automates the whole sequence.
Run it from a checkout of this repository:

```sh
./scripts/dsh-update.sh              # merge upstream/master, re-patch, push, wait for CI
./scripts/dsh-update.sh --dry-run     # show incoming commits, change nothing
./scripts/dsh-update.sh --ref v1.2.3  # sync to a specific tag instead of master
./scripts/dsh-update.sh --reapply     # re-apply the patch suite without merging
./scripts/dsh-update.sh --force       # rebuild and release even when up to date
```

In order it: fetches `upstream`, merges into `master`, runs the patcher,
pushes to `origin`, dispatches the `Build & Release Termux Prebuilt Bundle`
workflow, waits for it, then downloads and verifies the release.

Push to `origin` is the publish step. Nothing reaches a device before it.

### The build is dispatched, not push-triggered

`build-termux.yml` declares a `push` trigger on `master`, but a push event has
never produced a run in this repository — every build has come from
`workflow_dispatch`. Do not wait on a push to start a build. `dsh-update.sh`
calls `gh workflow run build-termux.yml` explicitly and fails if no run appears,
because the alternative is waiting out the timeout and quietly deploying the
previous release.

To start a build by hand:

```sh
gh workflow run build-termux.yml --repo salmanbappi/deepseek-harness --ref master
```

## When a patcher stops matching

Each patcher edits upstream text by anchor, so an upstream rewrite can move the
text out from under it. A patcher whose anchor no longer matches prints a line
and does nothing — it does not fail the run. Treat these as the signal to act:

```
[!] Android sandbox default: unrecognised approval policy in ...
[!] HMR Android gate: 'hmr' entry not found in the base overlay
```

A missed patcher ships a tree that boots differently from the one tested here,
which is how a silent regression reaches a release. After any sync, check that
the run reports no `[!]` lines:

```sh
python3 scripts/patch_termux.py --apply
python3 scripts/patch_termux.py --check   # exits non-zero when an invariant is unmet
```

## Verifying a sync before publishing

The patcher is the contract, so the check is that it re-derives the current
tree from a clean upstream tree and changes nothing further:

1. `python3 scripts/patch_termux.py --apply` on a synced tree.
2. `python3 scripts/patch_termux.py --check` must exit 0.
3. `git status` must show no diff beyond the version bump and the regenerated
   `patches/*.patch` exports.
4. `./scripts/dsh-update.sh --dry-run` must report a clean state.

## Overlays are patched files too

The three profile bundles under `packages/bundle/` and
`packages/experimental/cua-mcp/` restate sandbox and reloader settings. The
patcher edits those overlays in place, because a bundle that states its own
value overrides the base one. Two rules follow:

- The sandbox `mode` and the `policy` that derives from it resolve as a pair.
  Patching one without the other composes a mode and an approval policy that
  name no preset, and the profile fails to boot.
- A conditional expression in an overlay must be a quoted scalar. Include parses
  entries under `JSON_SCHEMA`, which has no implicit-key resolution, so a bare
  `: ` inside a plain scalar opens a nested mapping and the overlay fails to
  parse.
