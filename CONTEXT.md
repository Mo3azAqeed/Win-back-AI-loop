# Win-back AI loop

An email loop that wins back users of our store-cloning Shopify app who stalled before paying. Claude writes email variants, the loop picks which ones to send, and every outcome feeds back so the next choices get better.

## Lifecycle

**Trial**:
The free period that starts when a user publishes their cloned store, not when they sign up or start cloning.
_Avoid_: Trial at signup

**Paid conversion**:
A user moving from trial to a paid plan. Tracked for every email, whatever its goal action.
_Avoid_: Conversion (on its own, ambiguous)

**Holdout**:
A random 8% of each segment that never receives a win-back email, kept so lift can be measured.
_Avoid_: Control group (fine in conversation, but use one word)

**Baseline**:
The rate at which a segment reaches its goal action without win-back emails, measured on the holdout.

## Emails

**Goal action**:
The next lifecycle step an email aims to get a user to take; each segment has its own. It is what the loop rewards.
_Avoid_: Conversion, success

**Timing**:
How long after the trigger event an email is sent. Chosen per email by the loop from a fixed set of options, not hard-coded per segment.
_Avoid_: Trigger (when meaning the delay)

**Variant**:
One candidate for a single part of an email (subject, body or timing) that the loop can choose between. Claude writes subject and body variants; the loop decides which one each user gets.

## Milestones

**Simulation**:
A run of the loop against made-up users and made-up email outcomes, using placeholder baselines. No real email is sent.
