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

**Variant**:
One candidate for a single part of an email (subject, body, timing or offer) that the loop can choose between. The body includes the call to action. The writer writes subject and body variants; the loop decides which one each merchant gets.

**Offer**:
An incentive in a Trialist's email: none, a 7-day trial extension, or the first month at 50% off. Only Trialists receive offers.
_Avoid_: Promo, deal

**Lesson**:
A written finding about what works for a segment, stored with the evidence behind it. Lessons from one segment can seed the others.
_Avoid_: Insight, learning, memory

**Writer**:
The LLM that writes subject and body variants, reading the current lessons.

**Judge**:
The LLM that rates how appealing a variant is to a segment during a simulation. It stands in for real merchants and is a different model from the writer.

## Milestones

**Simulation**:
A run of the loop against made-up merchants and made-up email outcomes, using placeholder baselines. No real email is sent.

**True lift**:
How many more merchants in a segment reached the goal action within the horizon than in the same simulated world with no email at all, in percentage points. Each segment is judged on the same merchants in every approach: the emailed ones who would be in that segment with no email. Merchants an earlier email pushed into a later segment are that earlier email's win; they are reported on their own line, with no lift. Known exactly because the simulation made up every merchant; only exists in a simulation.
_Avoid_: Measured lift (what real data could show; not reported)
