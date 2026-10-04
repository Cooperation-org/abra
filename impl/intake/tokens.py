#!/usr/bin/env python3
"""
Manage abra intake tokens. One token per VM, bound to that VM's IP.

    tokens.py add <vm> <ip> [--scope intake]   prints the token once; only its hash is kept
    tokens.py list
    tokens.py revoke <vm>
"""
import argparse
import hashlib
import json
import os
import re
import secrets

HERE = os.path.dirname(os.path.abspath(__file__))
TOKENS_FILE = os.getenv("ABRA_INTAKE_TOKENS", os.path.join(HERE, "tokens.json"))


def load():
    try:
        with open(TOKENS_FILE) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save(tokens):
    fd = os.open(TOKENS_FILE + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(tokens, f, indent=2)
    os.replace(TOKENS_FILE + ".tmp", TOKENS_FILE)


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("vm", help="VM label, e.g. vm-300-platform")
    a.add_argument("ip", help="the VM's internal IP, e.g. 10.0.0.30")
    a.add_argument("--scope", default="intake")
    sub.add_parser("list")
    r = sub.add_parser("revoke")
    r.add_argument("vm")
    args = p.parse_args()

    tokens = load()
    if args.cmd == "add":
        if not re.match(r'^[a-z0-9][a-z0-9-]{0,40}$', args.vm):
            raise SystemExit("vm: lowercase letters, digits, hyphens")
        if any(e["vm"] == args.vm for e in tokens.values()):
            raise SystemExit(f"{args.vm} already has a token; revoke it first")
        token = secrets.token_urlsafe(32)
        tokens[hashlib.sha256(token.encode()).hexdigest()] = {
            "vm": args.vm, "ip": args.ip, "scope": args.scope}
        save(tokens)
        print(token)
    elif args.cmd == "list":
        for e in tokens.values():
            print(f"{e['vm']}\t{e['ip']}\t{e['scope']}")
    elif args.cmd == "revoke":
        kept = {h: e for h, e in tokens.items() if e["vm"] != args.vm}
        if len(kept) == len(tokens):
            raise SystemExit(f"no token for {args.vm}")
        save(kept)
        print(f"revoked {args.vm}")


if __name__ == "__main__":
    main()
