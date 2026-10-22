# AWS setup (one time)

Do this once. After that, every merge to `main` deploys the simulation to AWS by itself. It takes about 15 minutes. You need your AWS account and admin rights on this GitHub repository.

## 1. Pick a region

Choose one AWS region and use it for every step, for example `eu-west-1` (Ireland) or `us-east-1` (N. Virginia). Set it in the region menu at the top right of the AWS console.

## 2. Let GitHub deploy without keys

1. In the AWS console, open **CloudShell** (the `>_` icon in the top bar).
2. Run:

   ```bash
   git clone https://github.com/Mo3azAqeed/Win-back-AI-loop.git
   cd Win-back-AI-loop
   aws cloudformation deploy \
     --stack-name winback-github-deploy \
     --template-file infra/github-deploy-role.yaml \
     --capabilities CAPABILITY_NAMED_IAM
   aws cloudformation describe-stacks --stack-name winback-github-deploy \
     --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text
   ```

3. Copy the role ARN the last command prints. It looks like `arn:aws:iam::123456789012:role/github-deploy-winback`.

If the deploy fails because the GitHub OIDC provider already exists, run it again with `--parameter-overrides CreateOidcProvider=false`.

The role works only for this repository's `main` branch. It can only manage the win-back stack, so a pull request or another branch cannot touch your AWS account.

## 3. Tell GitHub where to deploy

In the GitHub repository, go to **Settings → Secrets and variables → Actions → Variables**. Add three repository variables:

| Name | Value |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | the role ARN from step 2 |
| `AWS_REGION` | your region from step 1, e.g. `eu-west-1` |
| `ALERT_EMAIL` | where report, failure and budget emails should go |

These are variables, not secrets: none of them gives access on its own.

## 4. Deploy

Merge anything to `main`, or open **Actions → CI → the latest run on main → Re-run all jobs**. The `deploy` job builds and deploys the stack named `winback`.

AWS then emails `ALERT_EMAIL` asking you to confirm the SNS subscription. **Click the link**, or no emails will arrive.

## 5. Run it now

1. Open the Lambda console and find the function whose name starts with `winback-SimulationFunction`.
2. On the **Test** tab, use an event like:
   - `{}`: today's date is the seed, as in the weekly run;
   - `{"seed": 7}`: a run you can repeat exactly;
   - `{"seed": 7, "start": 1000}`: only the 1,000-merchant start.
3. Click **Test**. A few seconds later the report is in S3, and the "report ready" email links to it.

Otherwise it runs by itself every Monday at 06:00 UTC.

## 6. Read the reports

Open the S3 console and find the bucket whose name starts with `winback-reportsbucket`:

- `latest.md` is always the newest report;
- `runs/` keeps every run, named `<date>-seed<n>.md`.

Running the same seed locally with `uv run winback --seed <n>` gives the same report.

## 7. Add the OpenRouter key (only once #13 lands)

CloudFormation cannot create encrypted parameters, so add this one by hand:

1. Open **Systems Manager → Parameter Store → Create parameter**.
2. Name: `/winback/openrouter-api-key`. Tier: Standard. Type: **SecureString**. Value: your key.

The Lambda can already read this parameter, and no other. Never put the key in GitHub.

## Turning it off

Pause the weekly runs by disabling the schedule in **EventBridge → Schedules**. The next deploy turns it back on. To remove everything, run `aws cloudformation delete-stack --stack-name winback` in CloudShell. The reports bucket is kept on purpose, so you don't lose old reports; delete it by hand if you want it gone.

## What it costs

Weekly runs fit in the AWS free allowances; see [`aws.md`](aws.md#will-the-free-account-be-enough). You get an email if a month's AWS spending goes over $5. Remember that the Free plan closes after 6 months unless you upgrade to the Paid plan.
