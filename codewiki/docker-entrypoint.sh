#!/bin/sh
# CodeWiki container entrypoint.
#
# Its one job beyond starting the app: if a GitHub token was provided, teach
# git to use it for every https://github.com/... clone the engine runs, so
# private repositories can be documented. Without a token the container
# behaves exactly as before — public repos only.
#
# Why a git-level rewrite instead of patching the clone code: CodeWiki shells
# out to `git clone` from more than one place (fe/github_processor.py and
# be/dependency_analyzer/analysis/cloning.py). A single
# `url.<base>.insteadOf` rule in the container's git config covers all of
# them, and any future ones, without touching Python. git also prints the
# ORIGINAL url (without the token) in its progress/error output when the
# rewrite is used, so the secret does not leak into logs the way an inline
# https://TOKEN@github.com/ URL built in code would.
#
# The token lands only in this container's writable layer (/root/.gitconfig),
# never in the image. It is still visible to anyone who can exec into the
# container or read `docker inspect` — treat it as you would any deployment
# secret and scope the PAT to read-only repo access.

set -e

TOKEN="${GITHUB_TOKEN:-${GH_TOKEN:-}}"

if [ -n "$TOKEN" ]; then
    # x-access-token: is the username form GitHub documents for both
    # classic and fine-grained PATs and for App installation tokens.
    git config --global \
        "url.https://x-access-token:${TOKEN}@github.com/.insteadOf" \
        "https://github.com/"
    # Never sit waiting on a credential prompt: a missing/expired/underscoped
    # token then fails fast with a clear git error instead of hanging until
    # the clone timeout.
    export GIT_TERMINAL_PROMPT=0
    echo "codewiki-entrypoint: GitHub token detected — private repository cloning enabled."
else
    echo "codewiki-entrypoint: no GITHUB_TOKEN set — public repositories only."
fi

exec "$@"
