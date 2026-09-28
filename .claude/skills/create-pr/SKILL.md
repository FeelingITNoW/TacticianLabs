---
name: create-pr
description: Opens or updates a GitHub pull request for the current branch using the gh CLI, with a written Summary/Test plan body reflecting what was actually done in the conversation. Use this whenever the user asks to open, create, submit, put up, or update a PR/pull request for their changes — including phrasing like "put this up for review", "ship this branch", or "PR this". Do not use it for reviewing someone else's PR, or for just committing/pushing without opening a PR.
---

# Create a pull request

Turns the current branch's changes into a GitHub PR (or updates the existing one), with a body that accurately describes what changed and what was actually verified — not a generic "various fixes" summary and not invented test coverage.

## Why this shape

A PR description is the first thing a reviewer reads, and it's often the only record of *why* a change was made once the diff itself is old news. Pulling the "what" and "why" from the conversation (not re-deriving it from the diff alone) keeps the description honest: it says what was actually checked, not what would ideally have been checked.

## Steps

1. **Check the working tree and branch.**
   ```sh
   git status --short --branch
   ```
   - If there are uncommitted changes, point them out to the user rather than silently committing or excluding them — ask whether they should be committed first, unless the user already told you what to do with them.
   - Note the current branch and whether it has an upstream (`## branch...origin/branch` vs just `## branch`).
   - Determine the base branch. Default to `main` unless the repo's default branch is something else (`git remote show origin | grep 'HEAD branch'`) or the user says otherwise.

2. **See what actually changed.**
   ```sh
   git log --oneline <base>..HEAD
   git diff --stat <base>...HEAD
   ```
   Skim the diff for anything that changes the *shape* of the summary you're about to write (new files, deleted files, renames) — don't just trust your memory of the conversation, since a branch can carry more or older commits than what you personally did in this session.

3. **Write the PR body to a scratch file, not inline in a shell command.** Inline `--body "..."` strings are fragile with quoting/newlines/backticks. Use a real Markdown file (your scratchpad directory, or a repo-ignored temp path) with:
   - `## Summary` — grouped by concern/feature, not by file. Explain *why* each change was made, pulling from what the conversation actually discussed (bug reports, design decisions, user corrections), not just restating the diff.
   - `## Test plan` — a checklist of what was *actually* verified: tests run (and their result), manual checks, builds, live smoke tests. Use `[ ]` for anything planned but not yet done, `[x]` only for things genuinely verified in this conversation. Never invent coverage that didn't happen — an unchecked or omitted item is more useful to a reviewer than a false checkmark.

4. **Add the attribution footer, if one applies.** Check the conversation for a system reminder or instruction about PR/commit attribution (it typically specifies exact lines to append, e.g. a "🤖 Generated with ..." line). Append it verbatim to the body file. Don't hardcode a specific footer in this skill — attribution text varies by session and user config, and using a stale one is worse than checking.

5. **Make sure the branch is on the remote.**
   ```sh
   git push -u origin HEAD   # first push / no upstream
   git push                  # already tracked
   ```

6. **Check whether a PR already exists for this branch**, so you update instead of duplicating:
   ```sh
   gh pr list --head <branch> --state all
   ```
   - **No PR exists:** create one.
     ```sh
     gh pr create --title "<title>" --body-file <scratch-file> --base <base> --head <branch>
     ```
   - **PR already exists:** update its body instead.
     ```sh
     gh pr edit <number> --body-file <scratch-file>
     ```
     `gh pr edit` can fail on some repos with an unrelated error about "Projects (classic)" being deprecated — this comes from `gh` fetching project-card data it doesn't need for a body edit, not from anything wrong with your body file. If you hit that, fall back to the REST API directly, since `-f body=@file` does **not** read the file (it was observed setting the literal string `@/path/to/file` as the body) — build real JSON and pipe it in:
     ```sh
     python3 -c "
     import json
     print(json.dumps({'body': open('<scratch-file>').read()}))
     " | gh api repos/<owner>/<repo>/pulls/<number> -X PATCH --input -
     ```

7. **Verify and report.** Re-read the body back (`gh pr view <number> --json body -q .body`) to confirm it actually took — especially after a fallback edit — then give the user the PR URL. Don't just trust a command's exit code for an edit that's known to sometimes silently no-op.

## Title

Keep it a single, specific line describing the overall change (not a restatement of the branch name), in the style of a good commit subject — e.g. "Fix Riot ingest correctness, move B2→GCS, deploy as a Cloud Run Job", not "Update files" or the branch name verbatim.
