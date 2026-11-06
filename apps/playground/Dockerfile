# Independent pilot image. Never mount the host Docker socket in this container.
FROM cloudops-arena-judge-guest:base AS guest
RUN apt-get update && apt-get install -y --no-install-recommends docker.io skopeo && rm -rf /var/lib/apt/lists/* && systemctl disable arena-evaluate.service && systemctl enable docker.service
# Preload all runtime layers; the VM has no external network adapter.
RUN skopeo copy --override-arch amd64 docker://public.ecr.aws/lambda/python@sha256:238f6bfd2c1c188aff3955c2f7ceb767fe9da1b3597d84264426a11690fcf2d7 docker-archive:/opt/arena/python-runtime.tar:public.ecr.aws/lambda/python:3.12
COPY apps/playground/boot.sh /opt/arena/start-playground.sh
COPY apps/playground/playground.service /etc/systemd/system/playground.service
COPY game-packs/aws-event-driven/terraform /opt/arena/template/terraform
COPY game-packs/aws-event-driven/functions /opt/arena/template/functions
RUN systemctl enable playground.service && mkdir -p /etc/docker && printf '{"log-driver":"local","log-opts":{"max-size":"5m","max-file":"2"}}\n' > /etc/docker/daemon.json

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852 AS disk
RUN apt-get update && apt-get install -y --no-install-recommends e2fsprogs qemu-utils && rm -rf /var/lib/apt/lists/*
COPY --from=guest / /guest/
RUN mkdir /image && truncate -s 8G /tmp/guest.raw && mkfs.ext4 -q -F -d /guest /tmp/guest.raw && qemu-img convert -O qcow2 -c /tmp/guest.raw /image/base.qcow2 && cp /guest/boot/vmlinuz-* /image/kernel && cp /guest/boot/initrd.img-* /image/initrd && rm /tmp/guest.raw

FROM ubuntu:24.04@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852
RUN apt-get update && apt-get install -y --no-install-recommends python3 qemu-system-x86 qemu-utils genisoimage && rm -rf /var/lib/apt/lists/* && mkdir /work && chown 65532:65532 /work
COPY --from=disk /image /opt/arena/image
COPY apps/playground/pilot.py /opt/arena/pilot.py
COPY apps/playground/guest.py /opt/arena/guest.py
COPY apps/playground/manager.py /opt/arena/manager.py
COPY apps/runner/shared_slots.py /opt/arena/shared_slots.py
COPY apps/runner/policy.py /opt/arena/policy.py
RUN chmod 644 /opt/arena/image/*
RUN mkdir /slots && chown 65532:65532 /slots
USER 65532:65532
ENTRYPOINT ["python3", "/opt/arena/pilot.py"]
