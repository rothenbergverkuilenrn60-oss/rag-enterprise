# v1.4 release ceremony — user-runnable command list

*Plan 19-08 prepares the artifacts (release notes, tag annotation). The user runs the commands below LOCALLY after the v1.4 milestone PR merges to `master`.*

*Per CONTEXT.md D-12: no CI auto-tag in v1.4 — manual tag from master keeps the release ceremonial. The release-cutter reviews the merged code one more time before tagging.*

## Prerequisites

- [ ] v1.4 milestone PR merged to `master` (Phase 16 + 17 + 18 + 19 all in)
- [ ] Local clone has `master` checked out (or you'll fetch it)
- [ ] `gh` CLI authenticated (`gh auth status` shows authenticated)
- [ ] Canonical repo URL known (the GitHub `<owner>/<repo>` to substitute throughout)

## Step 1 — Substitute the repo URL placeholder

Several artifacts use `<owner>/<repo>` placeholders. Identify your canonical repo URL (e.g. `acme-org/rag-enterprise`) and substitute throughout. Files to update:

```bash
REPO="<owner>/<repo>"  # ← REPLACE with your canonical repo (e.g. "acme-org/rag-enterprise")

# CHANGELOG.md compare-link footer:
sed -i "s|<owner>/<repo>|${REPO}|g" CHANGELOG.md

# release-notes-v1.4.md cross-links:
sed -i "s|<owner>/<repo>|${REPO}|g" .planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md
```

Verify (must return 0):

```bash
grep -c "<owner>/<repo>" CHANGELOG.md .planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md
```

Commit the substitution:

```bash
git add CHANGELOG.md .planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md
git commit -m "docs: substitute canonical repo URL in CHANGELOG + v1.4 release notes"
git push origin master
```

## Step 2 — Pull the latest master

```bash
git checkout master
git pull --ff-only origin master
git log --oneline -5
```

Confirm the v1.4 milestone PR's merge commit is `HEAD` (or near it). If not, STOP and figure out why — do not proceed.

## Step 3 — Cut the annotated tag

Extract the tag annotation from `release-notes-v1.4.md` Section A (the fenced code block under `## Tag annotation`):

```bash
TAG_MSG="$(awk '/^## Tag annotation/{flag=1; next} /^---$/{flag=0} flag' .planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md | sed -n '/^```$/,/^```$/p' | sed '1d;$d')"
echo "${TAG_MSG}" | head -10
```

Verify the message looks correct (6 lines of content: 1 headline + 4 phase bullets + 1 thesis paragraph, plus 2 separator blank lines). Then tag:

```bash
git tag -a v1.4.0 master -m "${TAG_MSG}"
git tag -v v1.4.0 | head -5
```

Verify the tag annotation message is exactly what `release-notes-v1.4.md` prescribes.

## Step 4 — Push the tag

```bash
git push origin v1.4.0
```

Verify on GitHub: `https://github.com/${REPO}/releases/tag/v1.4.0` should show the tag with the annotation visible.

## Step 5 — Publish the GitHub release

Use the gh CLI with the prepared release notes file. The `--notes-file` flag reads the FULL prose from Section B of `release-notes-v1.4.md`:

```bash
# Extract Section B (everything after the first horizontal-rule separator):
awk '/^## GitHub release notes/{flag=1; next} flag' .planning/phases/19-agent-first-docs-demo-release/release-notes-v1.4.md > /tmp/v1.4.0-release-notes.md

# Verify it looks right:
head -10 /tmp/v1.4.0-release-notes.md
wc -l /tmp/v1.4.0-release-notes.md   # expect 100..300

# Publish:
gh release create v1.4.0 \
    --title "v1.4.0 — Agent-First Architecture Inversion" \
    --notes-file /tmp/v1.4.0-release-notes.md \
    --verify-tag
```

Optional: attach `docs/demo.cast` as a release asset:

```bash
gh release upload v1.4.0 docs/demo.cast --clobber 2>/dev/null || true
```

## Step 6 — Verify the release publishes correctly

- [ ] Visit `https://github.com/${REPO}/releases/tag/v1.4.0`
- [ ] Release title: "v1.4.0 — Agent-First Architecture Inversion"
- [ ] Body renders the markdown cleanly (headings, tables, code blocks)
- [ ] All four phase SUMMARY links resolve (clicking lands on the rendered SUMMARY at the v1.4.0 tag)
- [ ] The asciinema cast link resolves to the in-repo file at the v1.4.0 tag
- [ ] Compare-link at the bottom resolves to a valid `compare/v1.3.0...v1.4.0` GitHub diff page

## Step 7 — Update STATE.md

Mark v1.4 as shipped in `.planning/STATE.md`:

```bash
# Edit STATE.md frontmatter: change `status: executing` to `status: shipped`
# Update `last_updated` to today's date
# Update `last_activity` to "2026-05-09 — v1.4 milestone shipped (tag v1.4.0)"
```

Commit:

```bash
git add .planning/STATE.md
git commit -m "docs(state): mark v1.4 milestone shipped"
git push origin master
```

## Rollback (if Step 6 reveals a problem)

```bash
# Delete remote tag:
git push --delete origin v1.4.0
# Delete local tag:
git tag -d v1.4.0
# Delete GitHub release:
gh release delete v1.4.0 --yes
```

Then fix the underlying issue, push the docs fix on master, and re-run Steps 3-6.
