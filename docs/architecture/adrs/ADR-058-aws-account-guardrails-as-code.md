# ADR-058 — AWS Account Guardrails as Code (near-$0 budget, deny on breach)

| Field | Detail |
|---|---|
| **Status** | **PROPOSED 2026-11-11 — awaiting user sign-off.** Nothing implemented. |
| **Phase** | Infrastructure |
| **Related** | ADR-031-A2 (in-code ceiling: the immediate stop; this is the account-side one) |
| **Precedes** | ADR-031-A3 (Bedrock provider), whose first call waits for this stack and its drill |
| **Provenance** | Split from the Bedrock draft on the owner's instruction, 2026-11-11. Owner: monthly AWS budget "as close to $0" as possible; recommendations accepted on review of need and cost. |

---

## 1. Context

The project has never used AWS (no `infra/`, no AWS packages in `uv.lock`).
Any use starts with an account that can bill. A press report describes a
Bedrock bill that ran past credits to ~$30K, and quotes AWS that Cost Anomaly
Detection does not cover Marketplace charges (The Register, 2026-05-14; no
AWS page checked). The owner wants monthly AWS spend as close to $0 as
possible.

## 2. Decision

### 2.1 Stay on the AWS Free plan while it lasts

AWS states the Free plan "incurs no charges as long as no upgrade is made"
(Free Tier announcement, §8): a $0 limit enforced by AWS. It applies to
accounts created on or after 15 July 2025 (OPEN_QUESTIONS #9) and lasts 6
months or until the credits are used, after which the account must move to
the Paid plan to continue (Free Tier FAQ). ADR-031-A3's 60-day exit test runs
inside that window. Moving to the Paid plan is a separate owner decision,
taken only after this stack is deployed and drilled, and only if a needed
service is closed on the Free plan (OPEN_QUESTIONS #8).

### 2.2 One CloudFormation template, `infra/aws/guardrails.yaml`

| Resource | What it does |
|---|---|
| Monthly cost budget, limit **$1.00**, whole account, **credits not netted off** | Email at actual > 1% ($0.01: any usage, even if credits pay it), actual 100%, forecast 100% |
| Budget action on it, actual 100%, automatic | Attaches `DenyBedrock` to `BedrockInvoker` |
| `DenyBedrock` managed policy (not attached) | Denies `bedrock:*`, the Mantle namespace (OPEN_QUESTIONS #12) and `aws-marketplace:Subscribe` |
| `BedrockInvoker` IAM role | The only principal the app uses: invoke one model, one region (template parameters). Assumable only by the owner's IAM user |
| `BudgetsActionExecution` role | Trusted by `budgets.amazonaws.com`; may attach and detach only `DenyBedrock`, only on `BedrockInvoker` |

The budget covers the whole account, not Bedrock alone: at a near-$0
target, spend on anything is the signal. One action-enabled budget is within
the free two. The alert email is a deploy-time parameter with no default;
the template uses `AWS::AccountId` and commits no account id, ARN or email.

### 2.3 Credentials: one IAM user, `aws login`, no access keys

- One IAM user with a console password and MFA, and **no access keys**. Root
  is MFA-protected and unused.
- `aws login` (AWS CLI 2.32+) turns the console sign-in into short-lived SDK
  credentials, refreshed for up to 12 hours (§8). A second profile assumes
  `BedrockInvoker` from it.
- IAM Identity Center was the first choice, but assigning access to an AWS
  account needs AWS Organizations (AWS docs, §8), and whether a Free-plan
  account may use Organizations is unknown. It stays the alternative if
  `aws login` refresh proves unreliable.

### 2.4 Deployed by the owner

`aws cloudformation validate-template`, then `aws cloudformation deploy`,
from the owner's machine; it creates resources in the owner's account, so
Claude Code does not run it. Whether a Free-plan account may create a
budget action is not checked: if `deploy` refuses it, the owner stops there
rather than dropping the action. The owner installs the AWS CLI (outside the
project sandbox) and creates the account and IAM user by hand, once.

### 2.5 Drill before the first real call

The breach trigger cannot be tested without spending. The effect can:

1. Attach `DenyBedrock` to `BedrockInvoker` by hand; an invoke as the role
   returns `AccessDenied`; detach.
2. `aws budgets describe-budget-actions-for-budget` shows the action, its
   threshold and the execution role.

This first drill runs with the AWS CLI, which calls `bedrock-runtime`; the
app will call the Mantle endpoint, whose IAM actions are OPEN_QUESTIONS #12.
So the A3 PR repeats step 1 through the app's own Bedrock client, before any
paid call. Both results go in that PR. What stays untested: AWS firing the
action.

### 2.6 Lifting the deny after a breach

The owner reverses the action (`aws budgets execute-budget-action
--execution-type REVERSE_BUDGET_ACTION`). Per AWS, a reversed action is not
evaluated again for the rest of the period unless reset (§8). Whether an
applied action undoes itself when a new month starts is not checked here, so
the owner reverses it deliberately.

## 3. Options

| Option | Verdict |
|---|---|
| **(a) Plain CloudFormation template** | **Chosen.** No dependencies, no bootstrap, $0, state kept by AWS, `delete-stack` rolls back. |
| (b) AWS CDK | Rejected: a Node CLI, Python packages (SECURITY §5) and a bootstrap stack with an S3 bucket and ECR repository, for five resources. CloudFormation is also what the owner's target certification (SAA-C03) examines — an owner preference, not a technical reason. |
| (c) Terraform / OpenTofu | Rejected: a new binary and a local state file to protect, where CloudFormation keeps state in AWS for free. |
| (d) Set up by hand in the console | Rejected, narrowly: it is deployed once and no gate runs the template, so code buys review, a diff and a one-command rollback, not automation. |

The template is **prose-gated**: no CI check runs it (no AWS credentials in
CI). It is checked by `validate-template` at deploy, the drill, and
CloudFormation drift detection afterwards.

## 4. Cost

| Item | Monthly |
|---|---|
| AWS Budgets, one action-enabled budget | $0 (first two free) |
| IAM user, roles and policy | $0 |
| CloudFormation for `AWS::` resources | $0 |
| **Total for this ADR** | **$0** |

The only spend left is what a service bills, capped by §2.1 on the Free
plan, by ADR-031-A2 in code, and by this budget.

## 5. Inversion (mandatory)

- **The budget is late.** AWS refreshes budget data periodically, not per
  call (frequency not checked here). ADR-031-A2's per-provider ceiling stops
  the app immediately; this budget catches what the app does not see.
- **Budgets cannot see the spend.** Unconfirmed for Bedrock (OPEN_QUESTIONS
  #11). If not, the in-code ceiling is the only stop, and A3 does not ship on
  the Paid plan until it is answered.
- **The app runs as someone else.** The deny lands only on `BedrockInvoker`.
  A3 builds the client only from that profile and tests it; the $0.01 email
  still fires for any other principal.
- **Credits hide spend.** Handled: the budget counts usage before credits.
- **The deny does not cover a namespace.** Mantle's IAM actions are
  OPEN_QUESTIONS #12; the second drill (§2.5) invokes through the app's own
  client, so a gap shows before the first paid call.

## 6. Consequences

- Easier: any AWS spend at all produces an email.
- Harder: past $1 in a month, Bedrock stops until the owner reverses the
  action.
- Forbidden: an app AWS credential other than `BedrockInvoker`; access keys
  on the IAM user; moving to the Paid plan before deploy and drill; an
  account id, ARN or email committed to the repository.
- Rollback: reverse the budget action if it has fired (§2.6), then
  `aws cloudformation delete-stack` removes every resource in §2.2. (A policy
  the action attached is not CloudFormation's, and may block deleting the
  role until detached — unverified.)

## 7. Out of scope

- Any AWS hosting for the ADR-056 demo (its own decision).
- AWS Organizations, IAM Identity Center and service control policies.
- Any always-on resource: nothing here runs or listens.

## 8. References (checked 2026-11-11)

- AWS Free Tier FAQ — https://aws.amazon.com/free/free-tier-faqs/
- AWS Free Tier announcement, July 2025 — https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/
- AWS Budgets pricing — https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/
- Get started with AWS Budgets actions (reversal) — https://aws.amazon.com/blogs/aws-cloud-financial-management/get-started-with-aws-budgets-actions/
- AWS SDK login credentials provider (`aws login`) — https://docs.aws.amazon.com/sdkref/latest/guide/feature-login-credentials.html
- IAM Identity Center and AWS Organizations — https://docs.aws.amazon.com/singlesignon/latest/userguide/identity-center-and-orgs.html
- Classmethod, Identity Center without Organizations — https://dev.classmethod.jp/en/articles/using-aws-iam-identity-center-without-organizations-organization-vs-account-instances-explained/
- The Register, 2026-05-14 — https://www.theregister.com/saas/2026/05/14/bedrock-and-a-hard-place-claude-adventure-leaves-aws-user-staring-down-30k-invoice/5238153
