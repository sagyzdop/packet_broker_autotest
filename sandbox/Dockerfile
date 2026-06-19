# sandbox/Dockerfile
# ------------------------------------------------------------------------------
# See CLAUDE.md -> "Sandbox networking" and "Running the project".
#
# Base image: python:3.11-slim (Debian-based, so apt-get works) gives us
# Python + pip without manually installing Python on top of plain Ubuntu.
# We add iproute2 (the `ip` command -- needed for `ip netns`, `ip link`),
# tcpdump (useful for debugging captures by hand inside the container),
# and net-tools (legacy ifconfig/netstat, handy for quick sanity checks).
# ------------------------------------------------------------------------------

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    iproute2 \
    iputils-ping \
    tcpdump \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x sandbox/*.sh

EXPOSE 8000

# entrypoint.sh builds the sandbox topology, starts broker_sim.py, then
# launches the actual FastAPI app -- see sandbox/entrypoint.sh.
ENTRYPOINT ["./sandbox/entrypoint.sh"]
