FROM floci/floci@sha256:5ee85db604c4aa74ac76e07ea5cc83086f37bb472bf3dbb97e34019e48efae9c AS floci
FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS guest
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends linux-image-virtual initramfs-tools systemd-sysv udev python3 python3-venv curl ca-certificates unzip util-linux && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/judge && /opt/judge/bin/pip install --no-cache-dir python-hcl2==7.3.1
ARG TERRAFORM_VERSION=1.10.5
RUN cd /tmp && curl -fsSLO https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip && curl -fsSLO https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS && grep " terraform_${TERRAFORM_VERSION}_linux_amd64.zip$" terraform_${TERRAFORM_VERSION}_SHA256SUMS | sha256sum -c - && unzip terraform_${TERRAFORM_VERSION}_linux_amd64.zip terraform -d /usr/local/bin && rm /tmp/terraform_*
RUN set -eu; for spec in aws:6.0.0 archive:2.7.0; do name=${spec%:*}; version=${spec#*:}; package=terraform-provider-${name}_${version}_linux_amd64.zip; cd /tmp; curl --retry 3 --continue-at - --connect-timeout 30 --max-time 1200 -fsSLO https://releases.hashicorp.com/terraform-provider-${name}/${version}/${package}; curl --retry 3 --connect-timeout 10 --max-time 120 -fsSLO https://releases.hashicorp.com/terraform-provider-${name}/${version}/terraform-provider-${name}_${version}_SHA256SUMS; grep " ${package}$" terraform-provider-${name}_${version}_SHA256SUMS | sha256sum -c -; destination=/opt/arena/providers/registry.terraform.io/hashicorp/${name}/${version}/linux_amd64; mkdir -p "$destination"; unzip "$package" -d "$destination"; rm terraform-provider-${name}*; done
COPY --from=floci /app/application /opt/arena/floci
RUN /opt/judge/bin/pip install --no-cache-dir boto3==1.38.18
COPY apps/runner/resilience.py /opt/arena/resilience.py
COPY apps/runner/runtime.py /opt/arena/runtime.py
COPY apps/runner/invoke.py /opt/arena/invoke.py
RUN chmod 600 /opt/arena/runtime.py /opt/arena/resilience.py
COPY apps/runner/guest.py /opt/arena/guest.py
COPY apps/runner/policy.py /opt/arena/policy.py
COPY apps/api/app/evaluation_progress.py /opt/arena/progress.py
COPY apps/runner/arena-evaluate.service /etc/systemd/system/arena-evaluate.service
RUN useradd --uid 2000 --create-home --shell /usr/sbin/nologin learner && systemctl enable arena-evaluate.service && systemctl mask systemd-networkd.service systemd-resolved.service && mkdir -p /input /work && printf '/dev/vda / ext4 defaults 0 1\n' > /etc/fstab && rm -f /etc/machine-id && touch /etc/machine-id

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS disk
RUN apt-get update && apt-get install -y --no-install-recommends e2fsprogs qemu-utils && rm -rf /var/lib/apt/lists/*
COPY --from=guest / /guest/
RUN mkdir /image && truncate -s 4G /tmp/guest.raw && mkfs.ext4 -q -F -d /guest /tmp/guest.raw && qemu-img convert -O qcow2 -c /tmp/guest.raw /image/base.qcow2 && cp /guest/boot/vmlinuz-* /image/kernel && cp /guest/boot/initrd.img-* /image/initrd && rm /tmp/guest.raw

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
ENV DEBIAN_FRONTEND=noninteractive PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 qemu-system-x86 qemu-utils genisoimage && rm -rf /var/lib/apt/lists/* && mkdir -p /work && chown 65532:65532 /work
COPY --from=disk /image /opt/arena/image
COPY apps/runner/server.py /opt/arena/server.py
COPY apps/runner/capacity.py /opt/arena/capacity.py
COPY apps/runner/shared_slots.py /opt/arena/shared_slots.py
COPY apps/runner/policy.py /opt/arena/policy.py
COPY apps/api/app/evaluation_progress.py /opt/arena/progress.py
RUN chmod 644 /opt/arena/image/kernel /opt/arena/image/initrd /opt/arena/image/base.qcow2
RUN mkdir /slots && chown 65532:65532 /slots
USER 65532:65532
EXPOSE 9000
CMD ["python3", "/opt/arena/server.py"]
