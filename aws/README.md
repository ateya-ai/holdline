# Deploy Holdline on AWS

`cloudformation/stack.json` defines the complete seven-role ECS/Fargate deployment in an existing VPC. It creates an HTTPS load balancer, private task networking, Cloud Map discovery, execution roles, Secrets Manager credentials, CloudWatch logs, RDS PostgreSQL, and encrypted authenticated Redis. The standalone placeholder task definitions from revision 1 have been removed; the stack is the single infrastructure definition.

The template passes `cfn-lint`. It has not been applied to an AWS account as part of preparing this release. A lint pass checks the infrastructure definition, not regional availability, DNS, quotas, permissions, or a successful rollout.

## Prerequisites

Use your deployment account and region. You need an existing VPC, two public subnets and two private subnets across availability zones, working private-subnet egress through NAT or the necessary endpoints, and an issued ACM certificate for the API domain in that region. Tasks need ECR/image access, Secrets Manager, CloudWatch Logs, and DNS resolution; optional live wording also needs provider egress.

Build the application image for `linux/amd64`, publish it to your ECR repository, and use its digest URI as `ImageUri`. The template rejects mutable image tags. The container stack can be used to rehearse the same application before deploying it.

```bash
docker build --platform linux/amd64 -t "$ECR_IMAGE_TAG" .
docker push "$ECR_IMAGE_TAG"
```

Authenticate Docker to your own ECR registry first using AWS's documented login process. Resolve the pushed digest and set `IMAGE_URI` to that full registry URI with `@sha256:`. Do not put credentials into the image or template parameters.

## Review the infrastructure change

Export `VPC_ID`, `PRIVATE_SUBNET_IDS`, `PUBLIC_SUBNET_IDS`, `IMAGE_URI`, `CERTIFICATE_ARN`, and `DOMAIN_NAME` for your environment. Subnet variables are comma-separated IDs. Then create a change set without executing it:

```bash
aws cloudformation deploy \
  --template-file aws/cloudformation/stack.json \
  --stack-name holdline \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    VpcId="$VPC_ID" PrivateSubnetIds="$PRIVATE_SUBNET_IDS" \
    PublicSubnetIds="$PUBLIC_SUBNET_IDS" ImageUri="$IMAGE_URI" \
    CertificateArn="$CERTIFICATE_ARN" DomainName="$DOMAIN_NAME" \
  --no-execute-changeset
```

Inspect the change set in your account before executing it. This stack provisions continuously billable Fargate services, an ALB, a Multi-AZ RDS instance, Redis nodes, logs, backups, and secrets. Existing NAT gateways and data transfer can incur additional charges. Review those resources against your own budget.

The default PostgreSQL minor version is a parameter. Verify that the selected PostgreSQL 17 minor version is available in your region before execution. An optional `HostedZoneId` lets the stack create its DNS alias; otherwise point the domain at the load balancer DNS output yourself. Use a distinct `NamespaceName` if another stack already uses `holdline.local` in this VPC.

## Credentials and live mode

The stack generates its shared service token and Redis AUTH secret. RDS manages the database master password. ECS execution roles retrieve the required secrets. Receiving uses `sslmode=verify-full` and the vendored AWS RDS CA bundle; Redis uses TLS certificate verification. The CA bundle's source is the [AWS RDS trust store](https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem); review the [AWS certificate guidance](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html) when rotating it.

Rehearsal is the default. To enable optional live wording, provide both `ModelName` and `ModelSecretArn`, where the secret JSON contains `OPENAI_API_KEY`. Tracing remains off by default. Retrieve the bearer secret privately for the clerk/client; do not paste it into a shared terminal transcript or a URL.

## Account acceptance

After your change set completes, check all ECS services, container health, `/ready`, all four rehearsal cases, concurrent retry behavior, queued completion, and one dependency recovery. Point the integration script at the HTTPS API with `HOLD_LINE_API_URL` and export that stack's token before running `python scripts/integration.py --external --queue`.

Inspect CloudWatch logs for the same review IDs. Verify the backup policy and perform restoration into a separate database before treating the environment as operated. The provided identity is one trusted desk; user-facing multi-tenant access needs a separate authorization design.

## Updates and cleanup

Update by publishing another digest and reviewing the resulting change set. Rotate application credentials by updating the secret and rolling every affected service. Database secret rotation needs a coordinated receiving rollout.

RDS deletion protection is enabled and deletion/replacement takes a snapshot. Deliberately disable deletion protection before deleting a disposable exercise stack. Review retained snapshots and backups afterwards because they can continue to incur charges. Do not delete an operated environment as part of a code cleanup.
