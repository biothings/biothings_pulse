#!/usr/bin/env bash
# Launch a minimal all-in-one BioThings Pulse instance (Amazon Linux 2023, arm64).
#
# Provisions a single EC2 box + security group with a public IP. This is the
# lightweight counterpart to deploy/terraform (ECS Fargate + ALB + DynamoDB):
# no load balancer, no container registry, SQLite state on the instance.
#
# After it prints the public IP, run deploy.sh to build + start the app:
#   HOST=<public-ip> SSH_KEY=~/.ssh/<key>.pem ./deploy/ec2/deploy.sh
#
# Prerequisites: awscli v2, configured credentials, an existing EC2 key pair.
#
#   KEY_NAME=my-keypair ./deploy/ec2/launch.sh
#
# Tunables (env vars, with defaults):
#   AWS_REGION=us-west-2  INSTANCE_TYPE=t4g.small  VOLUME_SIZE=20  NAME=biothings-pulse
#   VPC_NAME=biothings_vpc   (or set VPC_ID directly; this account has no default VPC)
#   SUBNET_ID=<subnet>       (optional; default: a public subnet in the VPC)
#   SSH_CIDR=<your-ip>/32    (default: 0.0.0.0/0 — restrict this!)
set -euo pipefail

: "${KEY_NAME:?Set KEY_NAME to an existing EC2 key pair name}"
AWS_REGION="${AWS_REGION:-us-west-2}"
INSTANCE_TYPE="${INSTANCE_TYPE:-t4g.small}"   # arm64/Graviton, 2 vCPU / 2 GB
VOLUME_SIZE="${VOLUME_SIZE:-20}"
NAME="${NAME:-biothings-pulse}"
VPC_NAME="${VPC_NAME:-biothings_vpc}"
SSH_CIDR="${SSH_CIDR:-0.0.0.0/0}"
HERE="$(cd "$(dirname "$0")" && pwd)"

aws() { command aws --region "$AWS_REGION" "$@"; }

echo "==> Resolving latest Amazon Linux 2023 arm64 AMI..."
AMI_ID="$(aws ssm get-parameter \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
  --query 'Parameter.Value' --output text)"
echo "    AMI: $AMI_ID"

# --- Network: resolve the VPC (no default VPC in this account) ---------------
VPC_ID="${VPC_ID:-$(aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=${VPC_NAME}" \
  --query 'Vpcs[0].VpcId' --output text)}"
if [ -z "$VPC_ID" ] || [ "$VPC_ID" = "None" ]; then
  echo "!! Could not find a VPC named '${VPC_NAME}'. Set VPC_ID or VPC_NAME." >&2
  exit 1
fi
echo "    VPC: $VPC_ID (${VPC_NAME})"

# Pick a public subnet (MapPublicIpOnLaunch=true) unless one is given.
SUBNET_ID="${SUBNET_ID:-$(aws ec2 describe-subnets \
  --filters "Name=vpc-id,Values=${VPC_ID}" "Name=map-public-ip-on-launch,Values=true" \
  --query 'Subnets[0].SubnetId' --output text)}"
if [ -z "$SUBNET_ID" ] || [ "$SUBNET_ID" = "None" ]; then
  echo "!! No public subnet found in ${VPC_ID}. Set SUBNET_ID explicitly." >&2
  exit 1
fi
echo "    Subnet: $SUBNET_ID"

# --- Security group: 22 (ssh), 80 (http), 443 (https) ------------------------
SG_ID="$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=${NAME}-sg" "Name=vpc-id,Values=${VPC_ID}" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"

if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  echo "==> Creating security group ${NAME}-sg in ${VPC_ID}..."
  SG_ID="$(aws ec2 create-security-group --group-name "${NAME}-sg" \
    --description "BioThings Pulse minimal box" --vpc-id "$VPC_ID" \
    --query 'GroupId' --output text)"
  aws ec2 authorize-security-group-ingress --group-id "$SG_ID" \
    --ip-permissions \
      "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${SSH_CIDR}}]" \
      "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]" \
      "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" >/dev/null
else
  echo "==> Reusing security group $SG_ID"
fi

echo "==> Launching $INSTANCE_TYPE ..."
INSTANCE_ID="$(aws ec2 run-instances \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --key-name "$KEY_NAME" \
  --security-group-ids "$SG_ID" \
  --subnet-id "$SUBNET_ID" \
  --block-device-mappings \
    "DeviceName=/dev/xvda,Ebs={VolumeSize=${VOLUME_SIZE},VolumeType=gp3,DeleteOnTermination=true}" \
  --user-data "file://${HERE}/user-data.sh" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME}}]" \
  --query 'Instances[0].InstanceId' --output text)"
echo "    Instance: $INSTANCE_ID"

echo "==> Waiting for it to be running..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
PUBLIC_IP="$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"

cat <<EOF

==> Instance is up.
    Instance ID : $INSTANCE_ID
    Public IP   : $PUBLIC_IP
    Region      : $AWS_REGION

Give cloud-init ~1-2 min to finish installing Docker, then deploy the app:

    HOST=$PUBLIC_IP SSH_KEY=~/.ssh/${KEY_NAME}.pem ./deploy/ec2/deploy.sh
    # with HTTPS once DNS points at this box:
    #   HOST=$PUBLIC_IP SSH_KEY=~/.ssh/${KEY_NAME}.pem \\
    #     DOMAIN=pulse.biothings.io ADMIN_TOKEN=... ./deploy/ec2/deploy.sh

To tear this box down later:

    aws --region $AWS_REGION ec2 terminate-instances --instance-ids $INSTANCE_ID
EOF
