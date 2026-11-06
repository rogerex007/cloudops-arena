#!/bin/sh
set -eu
mkdir -p /input
mount -o ro,nodev,nosuid,noexec /dev/sr0 /input
# Root-owned operator code on a read-only ISO. No participant files are accepted.
export PYTHONPATH=/opt/arena
exec /opt/judge/bin/python /input/guest.py
