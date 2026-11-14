# Submission checklist

Hard deadline: <day date HH:MM TZ as the platform shows it> (= <local>). Internal target: <day HH:MM local>. Run `scripts/now "<deadline ISO>"` before every status.
Form and video freeze at the deadline. After it: freeze the repo and server until judging ends (<date>).

## Required by the rules (quote each, with its line in drafts/rules/)
- [ ] Repo: <public + OSS licence | private, shared with <accounts>>. Invites sent on submission day; re-invite check on <date + 6 days>.
- [ ] Video: under <N> min (hard), <language>, public on <host>, shows <device wording>, no third-party music or logos. Plan: `docs/DEMO.md`.
- [ ] Description fields: drafted in `drafts/form.md`, each field decided or marked "needs <user>".
- [ ] Product feedback for every tool: `docs/PRODUCT_FEEDBACK.md`.
- [ ] Prior work explained: `docs/WHAT_CHANGED.md`.
- [ ] Testing instructions: zero-install path first; access code in <the private field | the private repo's judges section>.
- [ ] (Optional) Friction log: `docs/FRICTION_LOG.md` (<N> entries, <M> reported upstream).
- [ ] (Optional) <mini-challenge>: <eligibility, quoted>. Never block on it.

## Before submitting
- [ ] `docs/CLAIMS.md` reconciled: every public claim has evidence; numbers regenerated from source; device claims match recorded runs; nothing names unmerged work.
- [ ] Public text diffed against the copy <user> approved.
- [ ] One full run on the demo device, on the current build, today.
- [ ] Repo audit: secrets, access codes, infrastructure IDs, personal handles, home paths, forbidden assets, in the tree and the history.
- [ ] Every precondition set earlier is checked (for example: rotate the team code before inviting judges).
- [ ] After pasting into the form: reload and read the stored text.
- [ ] Tag the submitted commit at the freeze: `git tag submitted-<date>`; SHA: <...>.

## Keep live until judging ends (<date>)
- [ ] <Service>: balance <$X> on <date>; floor <$Y>; top up by <date> (owner: <name>).
- [ ] Hosting: no scheduled shutdown; static address; billing alarms below the credits.
- [ ] Access codes: judges <cap/day>, public <cap/day>; codes shown publicly checked against their caps.
- [ ] Monitoring: <command or notification>, tested on a real past run.
