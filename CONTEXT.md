# Win-back AI loop

An email loop that wins back merchants using our store-cloning Shopify app who stalled before paying. An LLM writes email variants, the loop picks which ones to send, and every outcome feeds back so the next choices get better.

## Lifecycle

**Merchant**:
A person who has signed up to our app with their email address.
_Avoid_: User, customer, shop owner

**Publish**:
The step in our app where a merchant makes their cloned store live. Publishing always starts the trial.
_Avoid_: Launch, go live

**Trial**:
The 7-day free period that starts when a merchant publishes their cloned store, not when they sign up or start cloning.
_Avoid_: Trial at signup

**Paid conversion**:
A merchant moving from trial to a paid plan. Tracked for every email, whatever its goal action.
_Avoid_: Conversion (on its own, ambiguous)

**Holdout**:
A random 8% of each segment that never receives a win-back email, kept so lift can be measured.
_Avoid_: Control group (fine in conversation, but use one word)

**Baseline**:
The rate at which a segment reaches its goal action without win-back emails, measured on the holdout.

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
The next lifecycle step an email aims to get a merchant to take; each segment has its own. It is what the loop rewards.
_Avoid_: Conversion, success

**Timing**:
How long after the trigger event an email is sent. Chosen per email by the loop from a fixed set of options, not hard-coded per segment.
_Avoid_: Trigger (when meaning the delay)

**Miss window**:
How long after an email the loop waits for the goal action before scoring the email a miss: 3 days for Idle, 7 days for Drafter, and until the trial ends for Trialist.

**Ghost send**:
A send time picked for a holdout merchant exactly as it would be for a real email, but with nothing sent, so the holdout is measured over the same days as emailed merchants.

**Variant**:
One candidate for a single part of an email (subject, body, timing or offer) that the loop can choose between. The writer writes subject and body variants; the loop decides which one each merchant gets.

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
How much the loop really raised a segment's goal-action rate over the holdout, known exactly because the simulation made up every merchant. Only exists in a simulation.
_Avoid_: Measured lift (what real data could show; not reported)
