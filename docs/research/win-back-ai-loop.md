# Win-back AI loop: primary-source research

All sources retrieved **2026-10-21**. Every factual claim links to the source that owns it. Text under **Inference / recommendation** is our reasoning, not a sourced fact. Claims that rest on a secondary source are marked **[unverified]**.

---

## TL;DR

1. **Opens can't tell you whether a subject line is good.** Apple Mail Privacy Protection (MPP) "prevents senders from seeing if you've opened the email" ([Apple](https://support.apple.com/guide/iphone/use-mail-privacy-protection-iphf084865c7/ios)). ESPs record MPP prefetches as opens ([SendGrid](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/understanding-apple-mail-privacy-protection-and-open-events), [Postmark](https://postmarkapp.com/support/article/1257-open-tracking-and-apple-mail)). Opens are also missed for plain-text mail and blocked images ([Postmark](https://postmarkapp.com/developer/user-guide/tracking-opens)). So "no open" is ambiguous, and "open" is often a machine.
2. **Clicks are better but also contaminated**, by security scanners and bots. Customer.io and Amazon SES now flag these clicks ([Customer.io](https://docs.customer.io/messaging/metrics/analytics/), [SES](https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html)). MPP does not cover links ([Apple](https://support.apple.com/guide/iphone/use-mail-privacy-protection-iphf084865c7/ios)).
3. **The reward should be the business outcome** (publish, paid conversion), measured against a **no-email holdout**. Use human clicks only as a leading proxy. Kohavi et al. warn that a good evaluation metric "should not be short-term focused (e.g., clicks)" ([Kohavi 2009](https://doi.org/10.1007/s10618-008-0114-1)).
4. **Shopify constraint: you need the merchant's consent before emailing them.** The Partner Program Agreement says: "Unless Partner has secured the consent of the applicable Merchant … Partner will not email any Merchant … whose email address they have received via Shopify" ([Partner Program Agreement §2.1](https://www.shopify.com/partners/terms)). Separately, Merchant Data must be deleted within 30 days of uninstall ([API Terms §6.2](https://www.shopify.com/legal/api-terms)). Both bound who can be "won back".
5. **Shopify billing:** new public apps default to **Shopify App Pricing**, which **does not send `APP_SUBSCRIPTIONS_UPDATE` webhooks**. Subscription state comes from the Partner API ([shopify.dev](https://shopify.dev/docs/apps/launch/billing/shopify-app-pricing)). The Billing API (`appSubscriptionCreate`, `trialDays`, the webhook) is now "Manual Pricing (legacy)" ([shopify.dev](https://shopify.dev/docs/apps/launch/billing)).
6. **Bandits fit this problem, but keep the number of arms small.** Thompson sampling performs poorly when there are many arms and the horizon is short ([Russo et al. §8.2.3](https://arxiv.org/abs/1707.02038)). An LLM that generates endless new variants creates exactly that situation. Gate new variants into a small active pool.
7. **Sender rules cap how aggressive the loop can be:** spam rate below 0.1% and never 0.3% or higher, RFC 8058 one-click unsubscribe, unsubscribes honored within 48h (Gmail) or 2 days (Yahoo), and a gradual ramp when the email format changes ([Gmail FAQ](https://support.google.com/a/answer/14229414), [Gmail guidelines](https://support.google.com/a/answer/81126), [Yahoo](https://senders.yahooinc.com/best-practices/)).

---

## 1. How trustworthy are opens and clicks?

### Facts

| Source | What it says |
|---|---|
| Apple, iPhone User Guide | MPP "hides your IP address … It also prevents senders from seeing if you've opened the email message they sent you." MPP "does not extend to links or email attachments." ([Apple](https://support.apple.com/guide/iphone/use-mail-privacy-protection-iphf084865c7/ios)) |
| Apple Newsroom (June 2021) | MPP "stops senders from using invisible pixels to collect information about the user … prevent senders from knowing when they open an email" ([Apple Newsroom](https://www.apple.com/newsroom/2021/06/apple-advances-its-privacy-leadership-with-ios-15-ipados-15-macos-monterey-and-watchos-8/)) |
| Twilio SendGrid | MPP pre-fetches and caches messages and images "whether the email has been opened by the intended recipient or not". Senders "cannot differentiate" real Apple Mail opens from prefetches, and repeat opens are not returned. A conventional open by an MPP user is still flagged `sg_machine_open: true`. For opens with `sg_machine_open: false`, opens remain "a reliable engagement measure". Clicks are "a strong measure of engagement" but are far less frequent than opens, "so you will need to calibrate accordingly". ([SendGrid MPP doc](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/understanding-apple-mail-privacy-protection-and-open-events)) |
| Postmark | MPP causes "false-positive opens". Postmark encourages measuring engagement in other ways, such as asking for feedback or inviting replies ([Postmark support](https://postmarkapp.com/support/article/1257-open-tracking-and-apple-mail)). Opens are not tracked for plain-text mail, for clients that block images, or when ad blockers interfere. For Gmail, images are proxied, so opens are detected but geography and OS are not ([Postmark open tracking](https://postmarkapp.com/developer/user-guide/tracking-opens)). |
| Google (Gmail Help) | Gmail scans and proxies images so that "Senders can't use image loading to get information about your computer or location", and "Sometimes, senders may know whether you've opened an email" ([Gmail Help](https://support.google.com/mail/answer/145919?hl=en)). Workspace admin docs: "Gmail uses Google's secure proxy servers to serve images" ([Workspace Admin](https://knowledge.workspace.google.com/admin/gmail/advanced/set-up-an-image-url-proxy-allowlist)). |
| Customer.io | Its "Machine opened" metric includes opens by Apple MPP, "Gmail's prefetching of images", bot user agents, and known scanners firing "within a few seconds of delivery". "Machine clicked" includes "automated security scanners, bot user agents, known proxy services, and repetitive click patterns". It counts **all** Apple Mail opens as non-human unless the recipient also clicks, so human opens are undercounted ([Customer.io metrics](https://docs.customer.io/messaging/metrics/analytics/)). |
| Amazon SES | Open and Click events carry `isBotEvent` = `Likely` or `Unlikely`, which is "the likelihood that the event was generated by an automated system (bot)" ([SES event contents](https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html); announced Aug 7 2026 in [AWS What's New](https://aws.amazon.com/about-aws/whats-new/2026/08/amazon-ses-automated-email-interactions/)). |
| RFC 8058 | One-click unsubscribe uses POST because "mail software sometimes fetches URLs in mail header fields, and thereby accidentally triggers unsubscriptions" ([RFC 8058](https://www.rfc-editor.org/rfc/rfc8058)). Automated URL fetching by mail software is old, documented behaviour. |

Note: "Gmail prefetching of images" is Customer.io's statement. Google's own pages say only that images are proxied and that senders "sometimes" know about opens. **[Gmail prefetch behaviour: unverified from Google]**

### Inference / recommendation
- **"Delivered but not opened" has at least five causes:** the recipient did not read it, it went to spam or a tab, images were blocked, it was read as plain text, or an ad blocker stopped the pixel. Only the first reflects on the subject line. MPP users almost never show as "unopened", so the unopened set is also biased toward non-Apple clients.
- **"Opened" is not evidence that the subject line worked** unless the open is flagged human. Use `sg_machine_open=false`, `isBotEvent=Unlikely`, or Customer.io "human opened", and only for the subset where such a flag exists.
- **Clicks need bot filtering too.** Drop clicks flagged by the ESP. Also apply your own heuristic: a click within N seconds of delivery, every link in the email clicked, or a click with no matching landing-page session. The time-to-click heuristic is consistent with Customer.io's "within a few seconds of delivery" rule. The specific thresholds are ours.
- **The most trustworthy signal is a first-party event in our app:** a landing-page session tied to a signed link token, then draft, publish, or a subscription becoming active. Treat ESP clicks as noisy proxies of that event.

---

## 2. Event plumbing (ESP webhooks)

### Facts

| | **Twilio SendGrid** ([Event Webhook ref](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/event)) | **Postmark** ([webhooks overview](https://postmarkapp.com/developer/webhooks/webhooks-overview)) | **Amazon SES** ([event contents](https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html)) | **Resend** ([event types](https://resend.com/docs/dashboard/webhooks/event-types)) |
|---|---|---|---|---|
| Delivery events | processed, dropped, delivered, deferred, bounce (`type` bounce/blocked, with `bounce_classification`) | Delivery, Bounce | Send, Reject, Delivery, Bounce, DeliveryDelay, Rendering Failure | email.sent, delivered, delivery_delayed, bounced, failed, suppressed, scheduled |
| Engagement events | open, click, spamreport, unsubscribe, group_unsubscribe, group_resubscribe | Open, Click, SpamComplaint, SubscriptionChange | Open, Click, Complaint, Subscription | email.opened, email.clicked, email.complained |
| Message id | `sg_message_id` (missing on async bounces) | `MessageID` | `mail.messageId` | `data.email_id`, `data.message_id` |
| Event dedupe key | `sg_event_id` ("Use this ID for deduplication") | No event id. Docs suggest a compound key (MessageID + Recipient + DeliveredAt) and idempotent handling ([Delivery webhook](https://postmarkapp.com/developer/webhooks/delivery-webhook)) | n/a in fields fetched | `svix-id` header ("Retries keep the same svix-id header, so dedupe on it") |
| Timestamp | `timestamp` (UNIX) | `ReceivedAt` / `DeliveredAt` (ISO 8601) | `timestamp` (ISO 8601) per object | `created_at`; `click.timestamp` |
| Link identity | `url`, `url_offset.index` (unique per duplicate URL) | `OriginalLink`, `ClickLocation` (HTML/Text) | `link`, `linkTags` (set via `ses:tags`) | `click.link` |
| Machine/bot flag | `sg_machine_open` (MPP opens only) | None in documented Open payload. `FirstOpen`, `Platform`, `UserAgent` given ([Open webhook](https://postmarkapp.com/developer/webhooks/open-tracking-webhook)) | `isBotEvent` on Open **and** Click | None in documented payload ([opened](https://resend.com/docs/webhooks/emails/opened), [clicked](https://resend.com/docs/webhooks/emails/clicked)) |
| Your metadata | `unique_args` / `custom_args`, `category` | `Metadata`, `Tag` | message tags | `tags` |
| Retries | Retried at increasing intervals for up to 24h after the event ([getting started](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/getting-started-event-webhook)) | Retried on 5xx/408/429/network failure with escalating back-off. Other 4xx responses are **dropped** ([overview](https://postmarkapp.com/developer/webhooks/webhooks-overview)) | via SNS/Firehose/EventBridge destinations | via Svix |

Customer.io (a marketing-automation platform, not a raw ESP) exposes human and machine open/click metrics "from our APIs, reporting webhooks, and data-out integrations" ([Customer.io](https://docs.customer.io/messaging/metrics/analytics/)). Postmark keeps individual open records for 45 days ([Postmark](https://postmarkapp.com/developer/user-guide/tracking-opens)).

### Inference / recommendation
- **SES and Customer.io are the only providers here that flag bot clicks.** SendGrid flags only MPP opens. For Postmark and Resend, we would need our own heuristics.
- **Always attach our own `send_id`** (as custom args, metadata, or tags) and a signed `send_id` token in every CTA URL. Then attribution never depends on the ESP's click event.
- **Store raw payloads.** Dedupe on the provider's event key. Treat events as at-least-once and possibly out of order.

---

## 3. Shopify side (trial, paid, uninstall, emailing merchants)

### Facts: billing state
- **Two billing paths.** "Shopify App Pricing" is "the default for new public apps". Plans, prices and trials are set in the Partner Dashboard, and apps should not call `appSubscriptionCreate`. "Manual pricing … is the legacy method", using the Billing API ([Billing overview](https://shopify.dev/docs/apps/launch/billing); [Shopify App Pricing](https://shopify.dev/docs/apps/launch/billing/shopify-app-pricing)).
- **Billing API (Manual Pricing):** `appSubscriptionCreate(name, lineItems, returnUrl, trialDays, test, replacementBehavior)` returns a `confirmationUrl` where the merchant approves the charge ([appSubscriptionCreate](https://shopify.dev/docs/api/admin-graphql/latest/mutations/appSubscriptionCreate)). The docs disagree on when the trial starts:
  - The mutation doc says `trialDays` is "beginning on the day that the merchant approves the app charges" ([mutation](https://shopify.dev/docs/api/admin-graphql/latest/mutations/appSubscriptionCreate)).
  - The `AppSubscription` object doc says "starting at the subscription's creation date". The object also has `status`, `createdAt`, and `currentPeriodEnd` (null if not active) ([AppSubscription](https://shopify.dev/docs/api/admin-graphql/latest/objects/AppSubscription)).
- **`AppSubscriptionStatus`:** `PENDING`, `ACTIVE` (approved and billed), `DECLINED` (terminal), `EXPIRED` (not approved within two days, terminal), `FROZEN` (non-payment), `CANCELLED` (terminal, including on uninstall), and `ACCEPTED` (deprecated) ([enum](https://shopify.dev/docs/api/admin-graphql/latest/enums/AppSubscriptionStatus)). There is **no separate "trialing" status**. A subscription in trial is `ACTIVE`, and you derive "in trial" from `trialDays` and dates.
- **Webhooks (Billing API):** subscribe to `APP_SUBSCRIPTIONS_UPDATE` to be notified of status changes ([time-based subscriptions](https://shopify.dev/docs/apps/launch/billing/subscription-billing/create-time-based-subscriptions)). The `app_subscriptions/update` payload carries `admin_graphql_api_id`, `status`, `admin_graphql_api_shop_id`, `created_at`, `updated_at`, `price`, `interval`, `plan_handle`. `app/uninstalled` carries the shop record, including `email` and `customer_email` ([webhook reference](https://shopify.dev/docs/api/webhooks/latest)).
- **Shopify App Pricing:** "doesn't use webhooks to notify your app of subscription changes". Status comes as redirect URL parameters (`plan_handle`, `shop`). For cancellations, freezes and expirations, "query the Partner API". Use `activeSubscription(appId, shopId)` (which includes `trialEndsAt`) and the Partner API `events` query, which has `SUBSCRIPTION_CREATED`, `_UPDATED`, `_CANCELLATION_SCHEDULED`, `_CANCELED`, `_FROZEN`, `_UNFROZEN`, plus installs, uninstalls and charges. That query defaults to the last 30 days, with a maximum range of 365 days ([Shopify App Pricing](https://shopify.dev/docs/apps/launch/billing/shopify-app-pricing)).
- **Trial abuse protection:** with App Pricing, Shopify "tracks trial days over a 180-day period" across reinstalls ([Offer free trials](https://shopify.dev/docs/apps/launch/billing/offer-free-trials)).
- **Draft and publish are our own data.** Shopify exposes no "draft saved" event for our app's concept. If "publish" means publishing a theme in the merchant's store, Shopify does have a `themes/publish` webhook ([webhook reference](https://shopify.dev/docs/api/webhooks/latest)).
- **Uninstall data rules:** `shop/redact` arrives "48 hours after a store owner uninstalls your app" ([privacy compliance](https://shopify.dev/docs/apps/build/compliance/privacy-law-compliance)). The API Terms require deleting Merchant Data "within 30 days when (A) the Merchant uninstalls the Application" ([API License and Terms §6.2](https://www.shopify.com/legal/api-terms)).

### Facts: contacting merchants by email
- **Partner Program Agreement** (shopify.com, last updated Feb 27 2026), §2.1 Marketing Activities: "Unless Partner has secured the consent of the applicable Merchant or Partner first, Partner will not email any Merchant or Partner whose email address they have received via Shopify." Its plain-language summary says: "Do not email a Merchant without their prior consent." Partners also must not "imply that such emails are being sent on behalf of Shopify" ([Partner Program Agreement](https://www.shopify.com/partners/terms)).
- **API Terms:** use Merchant Data only "as necessary to provide the Application services to the Merchant" and as described in your privacy policy ([API Terms](https://www.shopify.com/legal/api-terms)).
- **App Store requirement 1.1.13**, "Duplicate only authorized product information": "Marketing claims like 'import from any store in the world' or 'copy the product information from any website' … are not acceptable" ([App Store requirements](https://shopify.dev/docs/apps/launch/shopify-app-store/app-store-requirements)). This applies directly to a store-cloning app's email copy.
- We found **no shopify.dev rule specifically about lifecycle-email frequency.** The constraints above come from shopify.com legal terms, which are first-party but not on shopify.dev.

### Inference / recommendation
- **Collect an explicit, timestamped email-marketing opt-in inside the app** (and store its source). Segment C ("signed up, did nothing") is otherwise likely un-emailable if the address came from Shopify. Consider letting merchants enter a contact email themselves; an address obtained from the merchant directly is arguably not "received via Shopify". That reading of the terms is ours, so get legal sign-off.
- **Don't target uninstalled merchants with Shopify-sourced addresses** past the deletion window.
- **Segment definitions:**
  - **A:** trial started (subscription `ACTIVE` with a trial, or `activeSubscription.trialEndsAt` set), plus our `published` event, plus no paid period after trial end.
  - **B:** our `draft_saved` event with no `published` event.
  - **C:** installed or signed up, with no draft.
- **Billing source:** if the app is on App Pricing, poll Partner API events (for example every 15 min) instead of waiting for webhooks.

---

## 4. Sending rules that constrain the loop

### Facts
| Rule | Requirement |
|---|---|
| **Gmail** ([guidelines](https://support.google.com/a/answer/81126), [FAQ](https://support.google.com/a/answer/14229414)) | **All senders:** SPF or DKIM, valid forward/reverse DNS, TLS, spam rate in Postmaster Tools below 0.3%. **Bulk** (~5,000+ messages/day to personal Gmail from the same primary domain; "permanently considered bulk senders" once reached) adds SPF **and** DKIM, DMARC (p=none OK), From: alignment, and one-click unsubscribe plus a visible body link for marketing mail. Senders "should keep their spam rate below 0.1% and … prevent spam rates from ever reaching 0.3%". Senders above 0.3% are ineligible for mitigation until they are below it for 7 consecutive days. Unsubscribes should be fulfilled "within 48 hours". Transactional mail is exempt from one-click unsubscribe, and "Message recipients, not Google, determine the nature of the messages". Enforcement ramped up from November 2025, including "temporary and permanent rejections". |
| Gmail content and volume | Subject and headers "shouldn't be misleading", e.g. no "Re:"/"Fwd:" unless real. "If you change the format of your bulk emails, gradually increase the sending volume of messages with the new format". "Avoid sending email in bursts". "Consider unsubscribing recipients who don't open or read your messages." ([guidelines](https://support.google.com/a/answer/81126)) |
| **Yahoo** ([best practices](https://senders.yahooinc.com/best-practices/)) | Bulk senders: SPF, DKIM, and DMARC (p=none minimum, must pass). From: alignment. List-Unsubscribe with one-click ("RFC 8058 … highly recommended"). Visible unsubscribe link. "Honor unsubscribes within 2 days". Spam rate below 0.3%. |
| **RFC 8058** ([RFC](https://www.rfc-editor.org/rfc/rfc8058)) | `List-Unsubscribe` MUST contain one HTTPS URI. `List-Unsubscribe-Post: List-Unsubscribe=One-Click`. A DKIM signature MUST cover both headers. The POST MUST NOT need cookies or auth. The server MUST NOT redirect. |
| **CAN-SPAM** ([FTC guide](https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business)) | Applies to all commercial email, including B2B. No false headers. "Don't use deceptive subject lines." Identify the message as an ad. Include a physical postal address and a clear opt-out. The opt-out must work for 30 days after sending. Honor it within 10 business days. Penalties up to $53,088 per email. Transactional/relationship messages are read "narrowly". If the subject would lead a recipient to think the message is commercial, it is commercial. |
| **EU: ePrivacy Dir. 2002/58/EC Art. 13** ([EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32002L0058)) | Email direct marketing needs prior consent (13(1)). The exception (13(2)) covers contact details obtained "in the context of the sale of a product or a service" and used for "its own similar products or services", with an easy, free objection offered at collection and in every message. Art. 13(5): paragraphs 1 and 3 apply to natural persons. Protection for legal persons is left to member states. |
| **EU: GDPR** ([EUR-Lex](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32016R0679)) | Art. 21(2)–(3): the data subject may object "at any time" to direct-marketing processing, "which includes profiling to the extent that it is related to such direct marketing", and processing must then stop. Recital 47: direct marketing "may be regarded as carried out for a legitimate interest". |

### Inference / recommendation
- **No source sets a hard cap on sends per day or on the number of variants.** The binding constraints are indirect: complaint rate, unsubscribe handling, and Gmail's advice to ramp new formats gradually and avoid bursts.
- **Each new LLM variant is a "format change" in miniature.** Route only a small share of traffic to new variants, and stop a variant automatically if its complaint or unsubscribe rate jumps. Gmail reports spam rate through Postmaster Tools, calculated daily ([Gmail FAQ](https://support.google.com/a/answer/14229414)). Whether Gmail gives per-message complaints is **[unverified]**. Assume per-variant complaint data comes mainly from ESP spam-report events (e.g., Yahoo's [Complaint Feedback Loop](https://senders.yahooinc.com/best-practices/)), and use unsubscribes as the Gmail-side proxy.
- **Win-back mail is commercial** under CAN-SPAM even when it looks like account mail ("your draft is waiting"). Treat it as marketing: one-click unsubscribe, postal address, opt-out.
- **Our frequency recommendation:** at most 3 emails per user per win-back sequence, a global cap (e.g. 1 email per user per 72h across all sequences), and sunsetting after the sequence with no human engagement.
- **For EU recipients, rely on consent captured in-app.** Merchants are often sole traders, i.e. natural persons. Don't count on the Art. 13(2) soft opt-in for users who never bought anything (segments B and C); it is tied to "the sale of a product or a service". Get legal review.

---

## 5. The learning method

### Facts (papers)
- **Thompson sampling:** draw a parameter from each arm's posterior and play the arm that is best under that draw. Beta–Bernoulli is the conjugate case ([Russo, Van Roy, Kazerouni, Osband, Wen 2017, "A Tutorial on Thompson Sampling"](https://arxiv.org/abs/1707.02038)). Points from the tutorial that matter here:
  - §6.3, **non-stationary TS:** inject uncertainty with a decay rate γ so old data counts less.
  - §6.4, **concurrence:** batched or asynchronous updates fit web services that serve many users at once.
  - §8.2.2: if the goal is to *identify* the best arm (A/B-style), a pure-exploration variant can be more appropriate.
  - §8.2.3, **time sensitivity / many arms:** with many arms "TS is likely to sample a new action in each time period", and settling for a satisficing arm can do far better.
- **Randomized probability matching** (= TS) "randomly allocates observations to arms according the Bayesian posterior probability that each arm is optimal" ([Scott 2010, ASMBI](https://doi.org/10.1002/asmb.874)).
- **Contextual bandits / LinUCB:** each arm's reward is modelled as linear in user and arm features, with a UCB on top. The paper reports a "12.5% click lift" over a context-free bandit on 33M Yahoo! events, and "the advantage becomes even greater when data gets more scarce" ([Li, Chu, Langford, Schapire 2010, arXiv:1003.0146](https://arxiv.org/abs/1003.0146); [WWW '10](https://doi.org/10.1145/1772690.1772758)). The linear-payoff TS counterpart is [Agrawal & Goyal, arXiv:1209.3352](https://arxiv.org/abs/1209.3352).
- **Offline evaluation:** the *replay* method gives "provably unbiased evaluations" from logged data collected under a uniformly random policy. The authors note that simulators introduce "modeling bias" ([Li, Chu, Langford, Wang 2011, arXiv:1003.5956](https://arxiv.org/abs/1003.5956); [WSDM '11](https://doi.org/10.1145/1935826.1935878)). Doubly robust estimators reduce variance when the logging propensities are known ([Dudík, Langford, Li 2011, arXiv:1103.4601](https://arxiv.org/abs/1103.4601)).
- **Delayed rewards:** "the reward that is immediately available is most often only a proxy … conversion", with stochastic delay and censoring of late conversions ([Vernade, Cappé, Perchet 2017, arXiv:1706.09186](https://arxiv.org/abs/1706.09186), building on [Chapelle, KDD '14](https://doi.org/10.1145/2623330.2623634)).
- **Non-stationarity:** discounted and sliding-window UCB for rewards that change over time ([Garivier & Moulines, arXiv:0805.3415](https://arxiv.org/abs/0805.3415)).
- **A/B testing pitfalls:** repeatedly checking a fixed-horizon test inflates false positives; always-valid p-values fix this ([Johari, Pekelis, Walsh, arXiv:1512.04922](https://arxiv.org/abs/1512.04922)). Kohavi et al. recommend a single Overall Evaluation Criterion that is "not … short-term focused (e.g., clicks)" ([Kohavi et al. 2009](https://doi.org/10.1007/s10618-008-0114-1)).

### Bandit vs A/B (inference)
| | A/B test | Bandit (TS) |
|---|---|---|
| Goal | Learn which arm is best, with a defensible estimate | Maximize conversions while learning |
| Traffic to losers | Fixed (50/50) | Shrinks automatically |
| Effect-size estimate | Clean | Biased by adaptive allocation. Needs logged propensities plus IPS/replay. |
| Our fit | Use for **big structural questions** (sequence length, holdout lift, offer vs no offer) | Use for **subject, copy and timing choice** inside a segment |

### Credit assignment across the funnel (inference)

| Stage observed | Trustworthy? | Primarily informs | Caveat |
|---|---|---|---|
| Bounce / deferral | Yes | List hygiene, authentication. **Not** content. | Exclude from content rewards |
| Complaint / unsubscribe | Yes (complaints come via FBL, not from Gmail per message) | Subject + body + frequency | Use as a **guardrail cost**, not a reward |
| Human open (flagged non-machine) | Partial, for the non-MPP subset only | Subject + sender name + timing + inbox placement | Spam-foldering and a bad subject look the same |
| Human click / delivered | Medium | Subject × body jointly | Bot clicks; small numbers |
| Human click / human open | Medium, non-MPP subset | Body/CTA | Selection bias (only non-Apple, image-loading clients) |
| Conversion / click | High | Offer, landing page, product state | Delayed; small n |
| Conversion / delivered vs **holdout** | Highest | The whole email's incremental effect | Needs a no-email control |

**Practical design.** Don't hand-attribute funnel stages to slots. Model each send as a combination arm `(timing, subject, body)` and fit a Bayesian logistic model with **additive slot effects** per segment:

`P(conv | delivered) = σ(α_seg + τ_timing + s_subject + b_body)`

Then run Thompson sampling over that posterior (a linear/logistic TS in the spirit of Agrawal & Goyal). This handles credit assignment statistically. Use the funnel stages as **auxiliary likelihoods** (e.g., human click as a second outcome that shares `s_subject`, `b_body`) to borrow strength while conversions are scarce.

### What a small team should implement first (inference)
1. **Per segment, independent Beta–Bernoulli TS per slot.** Reward = conversion within a fixed window (e.g. 7 days) from the trigger event. Proxy reward = human click, used only until conversions accrue. Batch posterior updates daily (concurrent TS).
2. **Pending conversions are censored, not failures.** Update a send only once its window has matured, or use a delay-aware model (Vernade et al.).
3. **Mild discounting** (γ or a sliding window of N weeks) to handle drift and novelty decay.
4. **Keep 3–4 active arms per slot per segment** (Russo §8.2.3). A new LLM challenger enters only when an arm is retired. It starts with a skeptical prior centred on the segment mean and gets a small, capped traffic share.
5. **Log the selection probability (propensity) for every send.** Keep a small uniform-random exploration slice (e.g. 5–10%) so that Li et al. replay / IPS can evaluate new policies offline later.
6. **Keep a permanent 5–10% no-email holdout per segment** to measure incremental lift.
7. **Move to a contextual model** (LinUCB or linear TS with features such as shop age, plan, locale, draft completeness) only after the non-contextual version has thousands of matured sends per segment.

---

## 6. LLM-generated variants with a memory of wins and failures

### Facts (Anthropic docs)
- **Current models** ([Models overview](https://platform.claude.com/docs/en/about-claude/models/overview)):

  | Model | API ID | Price (input / output per MTok) |
  |---|---|---|
  | Claude Fable 5.1 | `claude-fable-5-1` | $10 / $50 |
  | Claude Opus 5.5 | `claude-opus-5-5` | $4 / $20 |
  | Claude Sonnet 5.5 | `claude-sonnet-5-5` | $2 / $10 |
  | Claude Haiku 5.5 | `claude-haiku-5-5` | from $0.10 / $0.50 |

  All four have a 1M-token context and 128K max output. The docs recommend starting with Opus 5.5 for most workloads.
- **Structured outputs** ([docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)):
  - Pass `output_config.format` with `type: "json_schema"`. It guarantees schema-compliant responses through constrained decoding.
  - Strict tool use (`strict: true`) validates tool inputs ([strict tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/strict-tool-use)).
  - **Not supported:** numerical constraints and **string `minLength`/`maxLength`**. The SDK moves these into field descriptions, so they are not enforced by decoding.
  - **Output can still break the schema** on `stop_reason: "refusal"` or `"max_tokens"`, and enum capitalization isn't guaranteed.
  - The first use of a schema adds grammar-compile latency. Compiled grammars are cached 24h.
  - Changing `output_config.format` invalidates the prompt cache.
- **Prompt caching** ([docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)):
  - The prefix is cached in the order tools → system → messages, up to `cache_control`. Default TTL is 5 min, or 1h at 2× write cost. 5-min writes cost 1.25× input.
  - Reads cost 0.1× input, or 0.05× on Opus 5.5 and Sonnet 5.5.
  - The minimum cacheable prompt is 512 tokens on current models.
  - Changing any block at or before the breakpoint changes the hash and misses the cache.
  - On current models you can append a `{"role":"system"}` message mid-conversation without invalidating the cache.
- **Message Batches:** 50% cheaper, most batches finish within 1h, and batches expire after 24h ([docs](https://platform.claude.com/docs/en/build-with-claude/batch-processing)).
- **Memory tool:** client-side. Claude requests file operations under `/memories`, and your app maps them onto storage you control ([docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)).
- **Reducing hallucinations:** let the model say "I don't know", restrict it to provided documents, require supporting quotes and retract unsupported claims, and compare several outputs (best-of-N) ([docs](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations)).

### Risks and mitigations (inference)
| Risk | Why it matters here | Mitigation |
|---|---|---|
| **Invented claims** (fake discounts, features, "import from any store") | CAN-SPAM deceptive subjects, Shopify req 1.1.13, Gmail "not misleading" | Give the model a **product fact sheet** (trial length, prices, real features, allowed offers) as the only source. Require each variant to list the `fact_ids` it relies on. Deterministic validator: any number or price in the text must match a fact. Banned-phrase list (e.g. "any store", "Re:", "Fwd:", Shopify branding implying endorsement). |
| **Tone drift** across generations | Lessons compound and copy gets pushier or spammier | Fixed brand/tone rubric in the cached system prompt. Haiku-based classifier scores each variant on tone and spamminess. Hard reject over threshold. Human approval of every *new* variant until trust is built. |
| **Overfitting to noise** | "Subject X won 3 vs 1 clicks" becomes a lesson | Only promote a lesson when the bandit posterior says P(arm better) ≥ 0.95 **and** each arm has ≥ N matured sends. Store the evidence (n, effect, interval) with the lesson. Record refuted and expired lessons too. Lessons expire after K weeks. |
| **Length limits not enforced by decoding** | Subject lines get truncated in inboxes | Validate length in code and regenerate on failure. |
| **Cache misses as lessons grow** | Cost | Put static system prompt + fact sheet + tone rubric first (cached), then the **lessons block, versioned and updated at most daily**, then per-request inputs. Run generation as a daily batch (Batch API, 50% off). |

---

## 7. Simulation

### Inference / recommendation: generative model per segment
For user *u* in segment *s*, receiving arm *(timing t, subject j, body k)*:

```
delivered       ~ Bern(1 - bounce_s)
is_mpp          ~ Bern(mpp_share_s)                  # Apple MPP user (fixed per user)
machine_open    = delivered & is_mpp                 # fires at delivery regardless of reading
inbox           ~ Bern(placement_s)                  # vs spam/tab; unobserved by the agent
read            ~ Bern(σ(a_s + q_subj[j] + f_s(t) + z_u^open - fatigue_u))   if inbox
human_open_obs  = read & !is_mpp & images_on_u       # what an open pixel can actually see
scanner_click   ~ Bern(scan_s)                       # time-to-click < few s, independent of read
human_click     ~ Bern(σ(b_s + q_body[k] + z_u^click)) if read
convert         ~ Bern(σ(c_s + g_s(t) + z_u^conv)) via click, plus organic hazard h_s regardless of email
conv_delay      ~ LogNormal(μ_s, σ_s); censor at window W
unsub/complaint ~ Bern(σ(d_s + spamminess[j,k] + freq_u))
```

- **Calibrate baselines.** Each segment's baseline conversion (A, B, C) is the **organic** rate `h_s` (no-email). Email lift sits on top of it. Without this split, the simulator will credit emails for conversions that would have happened anyway.
- **Arm quality.** True `q_subj`, `q_body` are drawn from a prior. An LLM-generated challenger's quality is drawn from that prior **plus an optional "lessons help" shift δ**. Run with δ = 0 as the null, so we check whether the loop beats baseline even when the LLM's lessons don't help.
- **Non-stationarity.** Random-walk `a_s`, novelty decay on each arm's q, and a seasonality term.
- **Noise sources to switch on and off:** MPP share, image blocking, scanner clicks, spam placement, delayed and censored conversions. This shows how much each one corrupts a naive "open = good subject" policy.
- **Policies to compare:**
  1. Fixed baseline (one hand-written email per segment).
  2. Uniform-random A/B.
  3. TS on raw opens (the naive design).
  4. TS on human clicks.
  5. TS on matured conversions.
  6. Factorized logistic TS.

### Facts: how to measure
- **Regret:** per period, `regret_t = max_k θ_t,k − θ_t,x_t` ([Russo et al. §6.3](https://arxiv.org/abs/1707.02038)). In simulation we know θ, so report **cumulative regret** against the oracle best arm.
- **Sample size:** `n = 16σ²/Δ²` per variant gives 95% confidence and 80% power (use 21 instead of 16 for 90% power). For a Bernoulli outcome, σ² = p(1−p) ([Kohavi et al. 2009](https://doi.org/10.1007/s10618-008-0114-1)).
- **Proportion intervals:** Wilson / Agresti–Coull confidence intervals ([NIST e-Handbook 7.2.4.1](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)). Two-proportion comparison ([NIST 7.3.3](https://www.itl.nist.gov/div898/handbook/prc/section3/prc33.htm)).
- **Sequential checking:** use always-valid inference if you look at results continuously ([Johari et al.](https://arxiv.org/abs/1512.04922)).

**Worked sample sizes (Kohavi formula; our arithmetic):**

| Metric | Baseline p | Detect Δ (abs) | n per arm |
|---|---|---|---|
| Conversion | 2% | +0.4 pp (20% rel.) | ≈ 19,600 |
| Conversion | 5% | +1 pp | ≈ 7,600 |
| Human click | 3% | +1 pp | ≈ 4,660 |
| Human click | 10% | +2 pp | ≈ 3,600 |

### Inference / recommendation: evaluation protocol
- **Many seeds.** Run ≥ 200 seeds per scenario. Report mean cumulative regret and conversion lift vs fixed baseline, each with 95% bootstrap intervals across seeds.
- **A/A runs.** Two identical arms must show no "lesson" promoted more than 5% of the time.
- **Sensitivity checks.** Vary daily volume per segment. The key output is: **at our real volume, how many weeks until the learner beats baseline?** If the answer is "never" at conversion-level rewards, use human clicks as the proxy and validate them against conversions periodically.
- **Simulator bias.** Treat simulator results as directional only. Li et al. 2011 specifically warn about simulator "modeling bias". Once real sends exist, re-evaluate policies with replay/IPS on logged data with propensities.

---

## What this means for our design

### The user's assumptions, checked

| Assumption | Holds? | Why (sources above) | Change |
|---|---|---|---|
| "Delivered but not opened → weak subject or bad timing" | **No** | MPP users register opens regardless of reading, so they're rarely "unopened". Plain text, blocked images, ad blockers and spam placement all produce "no open" for reasons unrelated to the subject ([Postmark](https://postmarkapp.com/developer/user-guide/tracking-opens), [SendGrid](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/understanding-apple-mail-privacy-protection-and-open-events)). | Never score a subject on open/no-open. Score subject and timing on **human click / delivered and on conversion**, jointly with the body via the factorized model. Use human-flagged opens only as a weak auxiliary signal on the non-MPP subset. |
| "Opened but no CTA click → subject fine, copy weak" | **Partly** | Only meaningful when the open is human (non-MPP, non-bot) *and* the ESP flags it ([SendGrid](https://www.twilio.com/docs/sendgrid/for-developers/tracking-events/event), [SES](https://docs.aws.amazon.com/ses/latest/dg/event-publishing-retrieving-sns-contents.html)). Clicks themselves include scanners ([Customer.io](https://docs.customer.io/messaging/metrics/analytics/)). | Compute click-given-human-open only on the flagged subset. Filter bot clicks. Prefer our own landing-session event over the ESP click. |
| "Clicked but didn't convert → offer or landing problem" | Mostly | Reasonable, but conversions are delayed and censored ([Vernade et al.](https://arxiv.org/abs/1706.09186)). | Evaluate only after the conversion window matures, and treat pending sends as censored. |
| "Log wins and fails as context so the baseline climbs" | **Risky as stated** | Small samples make most "wins" noise. Many arms make TS keep exploring ([Russo §8.2.3](https://arxiv.org/abs/1707.02038)). | Promote lessons only with posterior evidence. Cap active arms. Keep a holdout to prove the baseline climbs *incrementally*. |
| "Timing: 1h / 2d / 5d after draft save" | OK as arms | — | Measure every timing arm over the same window **from the trigger event**, not from the send. Otherwise early sends get credit for organic conversions. |
| "Each segment has a baseline conversion rate" | Needs definition | — | Baseline = **no-email holdout** conversion, not the pre-launch average. |
| (Implicit) "We can email all three segments" | **Not automatically** | Shopify Partner terms require merchant consent before emailing addresses received via Shopify. EU recipients may need consent ([Partner Agreement](https://www.shopify.com/partners/terms), [ePrivacy Art. 13](https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:32002L0058)). | Add in-app opt-in capture before any real send. |

### Proposed architecture (inference)

**Data model (Postgres-style)**
```
users(user_id, shop_id, email, email_source{shopify,user_entered}, marketing_consent bool,
      consent_ts, consent_source, locale, eu_flag, timezone, created_at)
app_events(id, user_id, type{installed,draft_saved,published,trial_started,
      subscription_active,paid_period_started,cancelled,uninstalled,email_optin},
      ts, source{app,shopify_webhook,partner_api}, payload jsonb)
segments_membership(user_id, segment{A,B,C}, entered_at, exited_at, trigger_event_id)
variants(variant_id, slot{subject,body,timing,offer}, segment, content jsonb, fact_ids[],
      parent_ids[], generator{model_id,prompt_version,lessons_version}, status{candidate,
      approved,active,retired,rejected}, validation jsonb, created_at)
sends(send_id, user_id, segment, trigger_event_id, arm{timing_id,subject_id,body_id},
      policy_version, propensity float, is_holdout bool, is_exploration bool,
      scheduled_at, sent_at, esp, esp_message_id)
email_events(provider_event_id PK, send_id, esp_message_id, type, ts, link_id, url,
      user_agent, machine_flag{none,mpp,bot_likely,heuristic}, secs_since_delivery, raw jsonb)
outcomes(send_id PK, delivered, bounced, complaint, unsubscribed, human_open, human_click,
      landing_session, converted, conversion_type, conversion_ts, window_end, matured bool)
posteriors(segment, slot, arm_id, alpha, beta, | or model params blob, updated_at, policy_version)
lessons(lesson_id, segment, slot, statement, evidence{arms,n,effect,ci,p_better},
      status{hypothesis,supported,refuted,expired}, created_at, expires_at)
```

**Pipeline**
1. **Ingest.** ESP webhooks → dedupe on the provider key → `email_events`. App events and Shopify (webhooks or Partner API poll) → `app_events`.
2. **Score.** A nightly job builds `outcomes` and marks sends `matured` after window W.
3. **Policy.** Per segment: holdout draw → exploration-slice draw → Thompson draw over active arms for each slot (or the factorized model). Store the propensity. Enforce frequency caps and consent. One-click unsubscribe headers are set by the sender service.
4. **Lessons.** A weekly job compares arms using the posteriors and writes `lessons` with their evidence. It expires old ones.
5. **Generate.** When a slot has fewer than K active arms, a batch call (Sonnet 5.5) with cached [system + fact sheet + tone rubric] + [versioned lessons] + the request returns JSON variants via structured outputs. Then: deterministic validator (facts, length, banned phrases) → Haiku 5.5 tone/spam check → human approval queue → `active` with a skeptical prior and a capped traffic share.
6. **Guardrails.** Auto-pause any variant whose complaint or unsubscribe rate exceeds the segment mean by X. Global kill switch if the domain spam rate exceeds 0.1%.

**Simulation harness.** The same policy, scorer, lessons and generator code runs against a `SimulatedWorld` (the §7 model) in place of the ESP and app events. The generator can be either a stub or the real LLM; real calls go through the Batch API. Outputs per run: cumulative regret, conversion lift vs fixed baseline with CIs, lessons promoted (and how many were false), and time to beat baseline at a given volume.

### Open questions for the user
1. **ESP:** which one, or are we choosing? SES and Customer.io flag bot clicks. SendGrid flags only MPP opens. Postmark and Resend flag neither.
2. **Billing:** Shopify App Pricing (no billing webhooks, so we poll the Partner API) or the Billing API?
3. **Consent:** do we already capture an email-marketing opt-in? Where did existing addresses come from (Shopify shop email vs user-entered)?
4. **Volume:** how many new users per week enter A, B and C? This decides whether conversion-level learning is feasible (see the sample-size table).
5. **Conversion definitions:**
   - A: first paid charge, or `ACTIVE` past trial end?
   - B: publish within N days?
   - C: first draft?
   - What window W?
6. **"Publish":** an in-app concept, or a Shopify theme publish (`themes/publish` webhook available)?
7. **Holdout:** are we OK permanently not emailing 5–10% of each segment so that we can prove lift?
8. **Offers:** can emails include discounts or trial extensions? (Partner Dashboard trial extensions exist: [shopify.dev](https://shopify.dev/docs/apps/launch/billing/offer-free-trials).) This determines the "offer" slot.
9. **Human approval:** will someone approve each new LLM variant before it goes live, at least initially?
10. **EU share:** what share of merchants are in the EU or UK, and are they sole traders?

---

### Claims we could not verify from a primary source
- **Gmail image *prefetching*** (Gmail opening images before the user reads the message) is stated by Customer.io. Google's own pages say only that images are proxied and that senders "sometimes" know about opens.
- **SES "Q5. Can I tag links with unique identifiers?" (`ses:tags`)** is referenced by the SES event doc, but we did not open the FAQ itself.
- **Apple MPP adoption share** and Apple's proxy user-agent string: we found only vendor blogs (e.g. Bird), so we used neither. In the simulator, `mpp_share_s` should be measured from our own `sg_machine_open` / `isBotEvent` rates.
- **The Partner Program Agreement subsection number** for the consent sentence. It sits under §2.1 "Marketing Activities". The exact sub-clause (likely 2.1.2) was not shown in the fetched text.
