"""Delete EVERYTHING Docker holds for this project, back to zero.

Containers, volumes (database, Qdrant, uploads), networks, images and build
cache all go. The next `run.py` builds and starts a completely fresh copy.

Also removes leftovers from older stacks of this repo that ran under other
Compose project names (pai-c-test2, pai-c-v2, ...): anything whose Compose
project name starts with "pai".

Double-click it, or: python scripts/del.py
Starts Docker Desktop (as administrator) if it is not running.
"""
import time

from _docker import docker, ensure_docker, run_script

PROJECT_PREFIX = "pai"
PROJECT_LABEL = "com.docker.compose.project"
APP_IMAGES = ("pai-c-backend", "pai-c-frontend", "placement-ai-backend", "placement-ai-frontend")
# Pulled base images hold no project data; removing them forces a fresh pull.
# `docker rmi` without -f leaves any that another project's container still uses.
BASE_IMAGES = ("postgres:16-alpine", "redis:7.4-alpine", "qdrant/qdrant:v1.19.1", "caddy:2-alpine")
CANCEL_SECONDS = 5


def lines(*args):
    return [line for line in docker(*args).stdout.splitlines() if line.strip()]


def owned(kind):
    """IDs and names of `kind` (container/volume/network) that belong to this project."""
    if kind == "container":
        cmd, fmt = ["ps", "-a"], "{{.ID}}\t{{.Names}}"
    else:
        cmd, fmt = [kind, "ls"], "{{.Name}}\t{{.Name}}"
    fmt += '\t{{.Label "' + PROJECT_LABEL + '"}}'
    found = []
    for row in lines(*cmd, "--format", fmt):
        ref, name, project = (row.split("\t") + ["", ""])[:3]
        # Volumes from very old runs carry no Compose label, only the name prefix.
        if project.startswith(PROJECT_PREFIX) or (kind == "volume" and name.startswith(PROJECT_PREFIX + "_")):
            found.append((ref, name))
    return found


def images():
    found = []
    for row in lines("images", "--format", "{{.Repository}}:{{.Tag}}"):
        if row.split(":")[0] in APP_IMAGES or row in BASE_IMAGES:
            found.append(row)
    return found


def wipe():
    ensure_docker()
    containers, volumes, networks = owned("container"), owned("volume"), owned("network")
    imgs = images()

    print("Deleting everything for this project:")
    print(f"  containers: {', '.join(n for _, n in containers) or '-'}")
    print(f"  volumes:    {', '.join(n for _, n in volumes) or '-'}  (database, Qdrant, uploads)")
    print(f"  networks:   {', '.join(n for _, n in networks) or '-'}")
    print(f"  images:     {', '.join(imgs) or '-'}")
    print("  build cache: all of it (Docker cannot tell which cache belongs to which project)")
    for left in range(CANCEL_SECONDS, 0, -1):
        print(f"\rStarting in {left}s... press Ctrl+C to cancel ", end="", flush=True)
        time.sleep(1)
    print()

    # Containers first: volumes and networks cannot go while a container uses them.
    if containers:
        print("Removing containers...")
        docker("rm", "-f", "-v", *(ref for ref, _ in containers))
    if volumes:
        print("Removing volumes...")
        docker("volume", "rm", "-f", *(ref for ref, _ in volumes))
    if networks:
        docker("network", "rm", *(ref for ref, _ in networks))
    print("Removing images...")
    for image in imgs:
        if docker("rmi", image, check=False).returncode != 0:
            print(f"  kept {image}: another container still uses it")
    # Untagged layers left behind by earlier rebuilds of the app images.
    docker("image", "prune", "-f")
    print("Removing build cache...")
    docker("builder", "prune", "-a", "-f")
    print("\nDone: zero. The next run.py starts completely fresh.")


if __name__ == "__main__":
    run_script(wipe)
