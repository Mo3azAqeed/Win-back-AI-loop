# Idle tests whole versions, champion against challenger, and every test ends in a recorded verdict

Until now the loop raced Idle subjects and bodies separately, with Thompson sampling, and kept no record of why a variant lost. The founder wants to see the story: their email is version 0, each AI version is tested against the current best, and by week 13 there is the best email and a playbook of what worked, what didn't and why (#32).

So in Idle a **version** is a whole email (subject and body with its button). The **champion** (at first version 0, the founder's email) and one **challenger** (the champion with one part changed, carrying a hypothesis) share Idle's emails: the challenger gets a third, the champion the rest. A test ends one of four ways, and always ends:

1. **The challenger won:** at a week's end the loop is 90% sure its click rate is higher (after 120 sends each) and its goal-action rate is not clearly lower (90% sure it is lower). It is crowned.
2. **The champion won:** 90% sure the challenger's click rate is lower, or the challenger won on clicks but not on goal actions (clickbait). The challenger is sunset.
3. **The same:** 90% sure the two click rates are within 1 point.
4. **Too close to call:** 2 weeks, or 1,000 emails for either version, whichever comes first. The version ahead on clicks stays, unless its goal actions are clearly worse; the playbook says it was kept, not proven.

Then the writer brings the next challenger at once, so nothing waits. Every test writes a playbook entry with both versions' evidence from the test itself, how sure the verdict is, and a one-line conclusion.

Decisions inside that design:

- **Clicks decide, goal actions guard** (founder's choice). Clicks are known at once and only the email can cause them (ADR 0003). Goal actions are slow and mixed with merchants who would act anyway, so they only veto a challenger that is clearly worse at them.
- **Verdicts on clicks are taken at week ends, not after every email.** Checking after every email would declare many false winners when versions are secretly the same. With every version secretly identical, 5 of 140 tests over 20 seeds (4%) claimed a winner, all at the 90% level asked for; the rest ended as too close to call. The 2-week and 1,000-email limits are also checked at every email, so a test started mid-week never runs past them.
- **Send time is not part of a version.** Each segment still learns timing from every merchant assigned it (ADR 0003): judged by clicks, an earlier send would look better only because fewer merchants have acted on their own by then.
- **A hidden follow-through** for each subject and body (100 = your first draft) lets the simulation plant an email that wins clicks it doesn't keep. All the stand-in writer's versions have 100; only tests plant other values.
- **No test starts after the last signup.** No new Idle merchant arrives after week 13, so a test started then would have no emails.

Considered and rejected: testing Drafter and Trialist versions too (about 40 emails a week each is too few; they borrow Idle's playbook in #36).

Tuning, for consistent wins (founder: "do whatever's needed to have consistent wins"). As first built (half each, and the champion always staying at the limit) the loop was easy to explain but won less than the old race: in Idle at 1,000 merchants the AI loop led the hand-written email in 26 of 40 replays (+1.64 against +1.53 points), where the old loop led in 37. At about 125 emails per version a week, two weeks can only tell apart differences of several click points, so most tests ended too close to call and a better challenger was thrown away. Over the same 40 replays:

| Idle, 1,000 merchants | AI loop lift (pts) | Ahead of the hand-written email | Lowest 5% of replays |
|---|---|---|---|
| Half each, champion stays at the limit | +1.64 | 26 of 40 | +1.15 |
| Thompson sampling between the two | +1.63 | 25 of 40 | +0.97 |
| The version ahead stays at the limit | +1.74 | 33 of 40 | +1.30 |
| ...and the challenger gets a third (chosen) | +1.76 | 34 of 40 | +1.32 |
| ...or 1-week tests instead | +1.81 | 33 of 40 | +1.19 |
| ...or 3-week tests | +1.69 | 28 of 40 | +1.09 |

The chosen setting held on 40 fresh replays: ahead in 34 of 40 at 1,000 merchants (+1.86 against +1.57) and 37 of 40 at 1,500, with the highest floor. With every version secretly identical none of these settings gains anything, as it should. The verdicts themselves are unchanged: "kept, not proven" is a decision to stop testing, not a claim of a winner, and the playbook says so. This supersedes ADR 0004 for Idle's words.

Update (2026-10-27, after #36): each test is now judged once, at a planned size. Drafters and Trialists borrow only a crowned challenger, so a crowning has to mean something, and the founder asked for the playbook to feed them. Measured first:

- Judged every week, as above, the loop rarely crowned anyone at 1,000 merchants (8 of 40 runs), and making tests longer to crown more mostly crowned luck: with every version secretly identical, 28% of tests named a winner. At 1,500 merchants the old rules already crowned a fake challenger in 8% of such tests. Each weekly check is another chance for luck to cross the bar.
- Judged once, the bar alone sets the fake rate: at 90% sure about 1 test in 10 between equal emails crowns the challenger, at 95% about 1 in 20.

So a test now gives the challenger half of Idle's emails and is judged once, when both versions have 250 emails or after 3 weeks, whichever comes first, at 95% sure. On the same 40 replays:

| | 1,000 merchants: runs with a crowning / AI ahead / fake crownings | 1,500 merchants: same |
|---|---|---|
| Weekly checks, a third, 2 weeks, 90% (before) | 8 / 38 of 40 / 2% | 25 / 36 of 40 / 8% |
| One verdict, half, 250 emails or 3 weeks, 95% (chosen) | 15 / 37 of 40 / 3.7% | 18 / 35 of 40 / 4.5% |

At our volume real crownings double; at 1,500 the fake ones halve. Tests at 1,000 merchants usually reach 3 weeks before 250 emails each, so the size matters more as volume grows. The 90% bar was the founder's; 95% replaces it because, judged once, 90% would crown a fake challenger in 1 test in 10. min_sends and the 1,000-email limit are gone: the planned size replaces both.
