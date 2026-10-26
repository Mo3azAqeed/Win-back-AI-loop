# Win-back AI loop: four open decisions

**Purpose:** four decisions are holding up the next tickets. Your answers set what the simulation measures next, what goes into the next report, and when the latest fixes go live on AWS.

**From:** Claude (engineering), **To:** Moaz (founder and TPM), **How your answers will be used:** each answer becomes a ticket, a pull request, or a line in `docs/technical-product-manager-discussion.md`. Nothing changes until you answer.

## Context

Milestone 1 simulates three stuck groups of merchants: Idle (signed up, no draft), Drafter (draft saved, not published) and Trialist (published, not paying). It compares four approaches: no email, your hand-written first draft, the AI loop, and an 8% holdout who are never emailed. The AI loop is live on AWS and runs every Monday.

The last ticket, #19, fixed how Drafter and Trialist results are measured: each approach is now judged on the same merchants. It's built and tested, but not yet on `main`, so AWS still runs the older version. Two questions came out of that work, and two are housekeeping.

## How to answer

About 10 minutes. Write under each `>` line. A one-word answer is enough where options are given; add a sentence if you want something different from all of them. "Not sure" is a fine answer: I'll come back with a smaller question.

## What the simulation measures

### How much of Idle's winning edge should carry over to Drafter and Trialist emails?

Today the AI loop sends Drafters and Trialists whichever Idle subject and body are winning, and the simulation assumes the email is exactly as good for them as it was for Idle. That causes two problems:

- **The words are wrong.** A Drafter can get "you signed up but haven't started a store yet", even though they already have a draft.
- **The quality is assumed, not learned.** Most of the AI loop's Trialist edge (+2.3 points against +0.5 for the hand-written email, at seed 1) comes from this assumption, not from anything the loop tested.

Whichever you choose, each segment would get its own words, starting from its own first draft. The choice is how much of Idle's quality edge the simulation lets carry over:

- **0 (my recommendation):** none carries over. The AI loop can only beat the hand-written email in Drafter and Trialist through timing, and offers once #8 lands. Any win the report shows there is earned. Real carry-over arrives honestly in #9, where lessons from Idle feed the writer.
- **0.5:** half of Idle's edge carries over. A middle guess.
- **1:** all of it carries over, as now. The most generous to the AI loop, and the least honest.

All three stay available as settings, so the others can still be run as what-if scenarios. This only picks the default the report uses.

_Why this matters: it decides whether the report's Drafter and Trialist results are something the loop earned or something the simulation assumed._

> **0** (answered 2026-10-26). Ticket [#22](https://github.com/Mo3azAqeed/Win-back-AI-loop/issues/22).

### Should I open a ticket for an "action report": measured lift, how sure each finding is, and what to do next?

You asked for an internal feedback loop whose results can be acted on. Today the report gives **true lift**, which only a simulation can know. Real data can only show **measured lift**: the AI loop's goal rate minus the holdout's. The spec kept measured lift out of scope, so adding it is a scope change. The ticket would add:

- measured lift against the holdout, week by week, next to true lift, so we can see whether real data could be trusted at your volume;
- how sure each finding is, for example "+1 hour is 63% likely to be Idle's best timing";
- one line per segment: **keep**, **retire** or **wait for more data**.

It would sit next to #11 (200 replays and the full report), as its own ticket so #11 doesn't grow too big.

- **Yes:** I open it now and place it in the build order.
- **Yes, but fold it into #11:** one bigger ticket instead of two.
- **Not yet:** revisit after #11.

_Why this matters: it's the difference between a report that says what happened and one that says what to do next._

> **Yes, its own ticket** (answered 2026-10-26). Ticket [#23](https://github.com/Mo3azAqeed/Win-back-AI-loop/issues/23).

## Shipping

### Should I open a pull request for #19 and merge it once CI is green?

#19's three commits are reviewed, and the tests catch 75 of 77 planted bugs. Merging puts them on `main`, and the next AWS deploy then reports the corrected Drafter and Trialist lift. The weekly Monday run would use it from the next run on.

- **Yes:** open it and merge it once CI is green.
- **Yes, but I'll merge it myself:** open it and leave the merge to me.
- **Hold:** wait until another ticket is done and ship them together.

> **Yes, merge when CI is green** (answered 2026-10-26).

## Documentation

### Should the shared doc be filled from your notes file, or deleted?

I started a shared doc, "Win-back AI loop: milestone 1 so far", before you asked for the notes file. The notes file (`docs/technical-product-manager-discussion.md`) now covers the same story, the ticket breakdown, the AWS choices and the interview stories, and it's kept up to date after every ticket. The doc still has empty sections.

- **Fill it from the notes:** a shareable, nicely laid out version for people who won't open GitHub. It would need refreshing by hand when the notes change.
- **Delete it:** the notes file is the single source.
- **Leave it for now:** decide later.

> **Delete it** (answered 2026-10-26).

## Anything else?

Anything I didn't ask that I should know, or a decision you'd rather make differently from all the options above?

> Nothing else.
