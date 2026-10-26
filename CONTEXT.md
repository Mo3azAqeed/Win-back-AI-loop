# Win-back AI loop

An email loop that wins back merchants using our store-cloning Shopify app who stalled before paying. An LLM writes email variants, the loop picks which ones to send, and every outcome feeds back so the next choices get better.

## Lifecycle

**Merchant**:
A person who has signed up to our app with their email address.
_Avoid_: User, customer, shop owner

**Existing merchant**:
A merchant who signed up before the simulation starts. Those who already pay are counted but not simulated.
_Avoid_: Backlog, old user

**New signup**:
A merchant who signs up during the simulation; every new signup starts in Idle.
_Avoid_: New user, lead

**Publish**:
The step in our app where a merchant makes their cloned store live. Publishing always starts the trial.
_Avoid_: Launch, go live

**Trial**:
The 7-day free period that starts when a merchant publishes their cloned store, not when they sign up or start cloning.
_Avoid_: Trial at signup

**Paid conversion**:
A merchant moving from trial to a paid plan. Tracked for every merchant over 30 days from entering each segment (its paid window), whatever segment it was in.
_Avoid_: Conversion (on its own, ambiguous)

**First-month revenue**:
What paying Trialists bring in their first month: the plan's $40 for each payment, or $20 for a payment at 50% off (see ADR 0003). Reported per approach so a win that brings in less money is visible.
_Avoid_: Sales, income

**Holdout**:
A random 8% of merchants, chosen once and kept for life, who never receive a win-back email in any segment. Kept so lift can be measured with real data.
_Avoid_: Control group (fine in conversation, but use one word)

**Baseline**:
The rate at which a segment reaches its goal action without win-back emails, measured on the holdout.

**Pushed merchant**:
A merchant in Drafter or Trialist who is there only because an earlier email moved them on; with no email they would not have reached that segment during the weeks of signups. Reported on their own line, with no true lift: their arrival is the earlier email's win.
_Avoid_: Extra, new arrival

**Organic action**:
A goal action a merchant takes with no email involved. The simulation's placeholder organic rates are what the baseline would measure.
_Avoid_: Natural conversion

**Segment**:
The stage a stalled merchant is in, set by the last lifecycle step they reached. A merchant is in at most one segment at a time.
_Avoid_: Group, cohort

**Idle**:
The segment of merchants who signed up but never started a draft. Goal action: start a draft.

**Drafter**:
The segment of merchants who saved a draft but never published. Goal action: publish.

**Trialist**:
The segment of merchants who published, so are in their trial, but have not paid. Goal action: paid conversion.

**Trigger event**:
The lifecycle event that starts the clock for a segment's email: signup, the most recent draft save, or publish.

## Emails

**Goal action**:
The next lifecycle step an email aims to get a merchant to take; each segment has its own. Results are judged on it, and timing and offers learn from it directly.
_Avoid_: Conversion, success

**Timing**:
How long after the trigger event an email is sent. Chosen per email by the loop from a fixed set of options, not hard-coded per segment.
_Avoid_: Trigger (when meaning the delay)

**Horizon**:
The fixed number of days from a merchant's trigger event over which true lift is counted and timing is judged: 8 days for Idle, 12 for Drafter, 14 for Trialist. Unlike the miss window, it does not depend on when the email went out.

**Miss window**:
How long after an email the loop waits for the goal action before scoring the email a miss: 3 days for Idle and 7 days for Drafter, counted from the email; for Trialist, 14 days after publishing for everyone, so a trial extension is judged on the same terms as no offer. An email followed by the goal action inside its window is a hit. Until the window closes the email is pending, neither hit nor miss.

**Ghost send**:
A send time picked for a holdout merchant exactly as it would be for a real email, but with nothing sent, so the holdout is measured over the same days as emailed merchants.

**First draft**:
The founder's approved hand-written email for a segment. It is what the hand-written approach sends and where the AI loop starts, and it is the reference for hidden quality (100). Not a merchant's store draft.
_Avoid_: Template, baseline email

**Carry-over**:
The share (0 to 1) of an Idle change's edge over the Idle first draft that a Drafter or Trialist version borrowing it is given in the simulation. Drafters and Trialists always send their own words; at 0, the default, a borrowed change gets no simulated boost, so any AI loop win there is earned in that segment. The real effect waits for the judge rating the new words (see ADR 0005, #36).
_Avoid_: Transfer, spillover

**Variant**:
One candidate for a single part of an email (subject, body, timing or offer) that the loop can choose between. The body includes the call to action. The writer writes subject and body variants; in Idle they come together as versions.

**Version**:
A whole email: a subject and a body with its button. In Idle, version 0 (v0) is the founder's first draft; each later version is numbered in the order the writer brought it, changes one part of the champion it was tested against, and carries a hypothesis. Drafters and Trialists have versions too: v0 is their first draft, and each later one is a borrowed version. Send time is not part of a version (ADR 0007).
_Avoid_: Variation, draft (a draft is the merchant's store)

**Champion**:
The Idle version the AI loop currently sends as its best. v0 is the first champion; a challenger that wins its test is crowned and becomes the champion.

**Challenger**:
The Idle version being tested against the champion. It gets a third of Idle's emails until the test ends.

**Hypothesis**:
What a challenger changes and why, written with it: "Names store cloning in the subject, because it is what sets the app apart." Every challenger has one.

**Test**:
One champion against one challenger. It always ends, in one of four ways: the challenger won (crowned), the champion won (the challenger is sunset, including when it won clicks but clearly lost goal actions), the same (within 1 click point), or too close to call (at 2 weeks or 1,000 emails per version; the version ahead on clicks stays, kept but not proven). Verdicts on clicks are taken at week ends (ADR 0007).
_Avoid_: Experiment, round

**Borrowed version**:
A Drafter or Trialist email that takes the change a won Idle test proved, written by the writer in that segment's own words. It replaces the segment's email on the day of the verdict, with no test of its own (about 40 emails a week is too few), and records the Idle test it came from. Versions kept at a test's limit (not proven) are not borrowed (#36).
_Avoid_: Copied, inherited

**Sunset**:
A version that lost a test, or that was the champion when a challenger was crowned. It is no longer sent, and keeps its record.
_Avoid_: Retired, killed

**Playbook**:
The record of every test: the two versions, the hypothesis, each one's sends, clicks and goal actions in the test, how sure the verdict is, how the test ended, and a one-line conclusion. Losers keep their entry, saying why they lost. It is the loop's lessons, with the evidence.
_Avoid_: Log, history

**Follow-through**:
Hidden in the simulation: how likely a merchant who clicks an email is to act, against the founder's first draft (100). It lets a test plant an email that wins clicks it doesn't keep.

**Offer**:
An incentive in a Trialist's email: none, a 7-day trial extension, or the first month at 50% off. Only the AI loop's Trialist emails carry one; it adds one line to the Trialist first draft. An extension lets the merchant pay until day 14, including a merchant who would have paid on its own just after day 7. The discount only works through the email's link: a merchant who clicked it before paying pays half, even one who would have paid anyway; one who didn't click pays in full.
_Avoid_: Promo, deal

**Would have paid anyway**:
A merchant who paid with the discount but, with no email at all, would have paid the full price at some point. Known only in a simulation, by looking at the same merchant in the no-email run; it is what a discount costs.

**Lesson**:
A written finding about what works for a segment, stored with the evidence behind it. Lessons from one segment can seed the others.
_Avoid_: Insight, learning, memory

**Writer**:
The LLM that writes subject and body variants, reading the fact sheet, the first drafts and the playbook. Until a run asks for it, the stand-in writer stands in.

**Stand-in writer**:
The prewritten list of subjects and bodies, each with a hypothesis and a placeholder hidden quality, used in order. The free, repeatable default.

**Fact sheet**:
The only facts an email may state (`fact_sheet.toml`): the plan and price, the trial, the features, and the Trialist offers, with the banned phrases. Every figure must appear exactly as written there.

**Copywriter**:
Where the AI loop gets each challenger's new part: the stand-in writer, or the writer and judge with the checks in front of them.
_Avoid_: Connector (the code's older name for it)

**Judge**:
The LLM that rates how appealing a variant is to a segment during a simulation. It stands in for real merchants and is a different model from the writer.

## Milestones

**Simulation**:
A run of the loop against made-up merchants and made-up email outcomes, using placeholder baselines. No real email is sent.

**Replay**:
One run of the same 13 weeks with different luck. A full report replays 200 times from each starting size, so one lucky run can't decide the answer; the first replay uses the seed itself and is shown in full.
_Avoid_: Iteration, trial (a trial is the 7-day free period)

**Middle 90%**:
Where 90% of replays land, leaving out the luckiest and unluckiest 5% on each side: the range the report gives next to each average.
_Avoid_: Confidence interval

**True lift**:
How many more merchants in a segment reached the goal action within the horizon than in the same simulated world with no email at all, in percentage points. Each segment is judged on the same merchants in every approach: the emailed ones who would be in that segment with no email. Merchants an earlier email pushed into a later segment are that earlier email's win; they are reported on their own line, with no lift. Known exactly because the simulation made up every merchant; only exists in a simulation.
_Avoid_: Measured lift (what real data could show; not reported)
