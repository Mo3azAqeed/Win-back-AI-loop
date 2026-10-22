# Running on AWS

How the simulation runs on AWS without anyone at a laptop (milestone 1), and how the same engine sends real emails later (milestone 2). Nothing here is built yet. This is the design ticket #17 follows.

## Is the code ready for it?

Mostly yes, because of one choice made early: the engine has a single entry point, `run_simulation(settings, seed)`. It reads no files, calls no network and checks no clock, and it returns the report as text instead of writing it anywhere. Anything that can call a Python function can run it, and it has no third-party dependencies to package.

Only the edges assume a laptop:

| Edge | What it assumes today | On AWS |
|---|---|---|
| `load_settings(path)` | `settings.toml` and `first_drafts.toml` sit side by side on disk | Still fine. Both files are bundled into the Lambda package, which can read its own files. Settings change through git, so every run's settings are versioned. **No change needed.** |
| `winback` command (`cli.py`) | Writes `reports/report.md` to the current folder | Lambda can only write to `/tmp`, so the command is not reused. A new Lambda handler, about 20 lines, calls `run_simulation` and puts the report in S3. The command stays for local runs. |
| Seed | Defaults to 1, so every run is identical | Each scheduled run needs a new seed, otherwise it repeats the same report. The schedule sends `{seed, start}`, and if no seed arrives the handler uses the date. |
| OpenRouter key (#13) | #13 says "read from the environment" | The connector takes the key as an argument and never reads the environment itself. The command passes it from an environment variable; the Lambda handler reads it from Parameter Store. This keeps the key out of the engine and out of the Lambda console. |
| 200 replays (#11) | One process runs every replay | A Lambda run stops after 15 minutes. A full run takes under a second today, but #7 and the LLM calls in #13 will make it slower. #11 should keep each replay's result a plain value and build the report from a list of them. Then, if a run ever outgrows one Lambda, the replays can be split across several without touching the engine. |

In codebase-design terms: the seam is already in the right place. The command and the Lambda handler are two thin adapters around the same deep module. There is no need for a "report storage" abstraction inside the engine, because the engine never stores anything.

## Milestone 1: the simulation runs itself

![Milestone 1 on AWS](diagrams/aws-poc.drawio.svg)

1. You merge to `main`. GitHub Actions runs the tests and mypy, signs in to AWS through an IAM role (OIDC, so no AWS keys are stored in GitHub), and runs `sam deploy`.
2. CloudFormation creates or updates everything inside the AWS box from one SAM template kept in the repo.
3. EventBridge Scheduler starts the Lambda every week. You can also start it from the console at any time.
4. The Lambda runs the simulation and saves `runs/<date>-seed<n>.md` and `latest.md` to S3.
5. SNS emails you a "report ready" message with the link. It also emails you if a run fails or AWS spending passes $5 in a month.

## Milestone 2: real emails to real merchants

![Milestone 2 on AWS](diagrams/aws-production.drawio.svg)

The engine stays the same. What changes is the world around it:

- Our Shopify app sends lifecycle events (signup, draft saved, publish, paid) to API Gateway.
- The lifecycle Lambda keeps each merchant's segment, puts 8% in the holdout for life, picks a timing, and schedules the send. Holdout merchants get a ghost send, with nothing actually sent.
- At send time, the send Lambda picks the subject, body and offer, and Amazon SES sends the email.
- SES reports deliveries, clicks, bounces and complaints. The outcome Lambda scores each send and drops clicks that SES flags as likely bots (`isBotEvent`).
- Once a week, the writer Lambda asks OpenRouter for new variants, checks them, and updates the lessons.

DynamoDB is the proposed store because it costs almost nothing at our volume and needs no server. That choice gets its own decision record when milestone 2 starts.

Before the first real send:

- verify our sending domain in SES (SPF, DKIM, DMARC);
- request production access to leave the SES sandbox;
- capture each merchant's consent in the app. Shopify's Partner terms require it; see the research doc.

## Will the free account be enough?

For milestone 1, yes. The only real limit is how long the Free plan lasts.

| Service | Free allowance (from AWS's pricing pages) | Milestone 1 use |
|---|---|---|
| Lambda | 1 million requests and 400,000 GB-seconds per month | A few runs a week, seconds each |
| EventBridge Scheduler | 14 million invocations per month | A few per week |
| Parameter Store | Standard parameters at no charge | One key |
| S3, CloudWatch, SNS | Small use | Reports of a few KB, a few log lines, a few emails |

- **The catch:** a new account on the Free plan gets up to $200 in credits. The account closes on its own 6 months after it opens, or when the credits run out, whichever comes first. To keep running after that, upgrade to the Paid plan before then; any leftover credits carry over. At this workload the Paid plan should still cost close to nothing.
- **What AWS does not pay for:** OpenRouter is billed separately. Budget for its LLM calls on their own.
- **Milestone 2:** SES charges $0.10 per 1,000 emails. Our volume costs cents a month, and the credits cover it.
