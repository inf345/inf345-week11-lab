#!/usr/bin/env python3
"""
INF 345 Milestone 6 - the infrastructure-as-code block, checked on its own.

M6 is due Sunday 6 December 2026, 23:59 Almaty time (UTC+5). This file checks
the Terraform half of it: your `infra/` folder. It is the rubric for that half,
and Week 12's M6 marker runs exactly these checks (see "Contract for Week 12"
in the Week 11 CHANGES.md).

    python3 check_iac.py --path .                     # your local checkout (its HEAD)
    python3 check_iac.py --repo https://github.com/<you>/<project>
    python3 check_iac.py --path . --tool terraform    # also init, validate, fmt, plan
    python3 check_iac.py --path . --tool tofu         # the same with OpenTofu
    python3 check_iac.py --path . --json

Nothing to install: Python 3.9 or newer and git. The static checks read only
what is COMMITTED (the marker sees commits, not your disk). With --tool, the
committed infra/ is copied to a temporary folder and the tool runs there, so
your own folder is never touched.

Three gates. Any gate failure scores the whole milestone 0:
  1. infra/ contains Terraform (at least one committed infra/*.tf file)
  2. no Terraform state or provider cache in the tree OR the history:
     *.tfstate, *.tfstate.* (e.g. .tfstate.backup), anything under .terraform/
     (.terraform.lock.hcl is NOT the .terraform/ folder - commit it)
  3. no credentials anywhere in the history (the same scanner as M1-M5)

Then one block of 25, "the infrastructure is code". It scores 25 only if every
check passes; the report lists every problem at once.
  static (always):
    - every infra/*.tf file parses
    - the Docker provider is required with source "kreuzwerker/docker" and a
      version constraint with an upper bound (`~> 4.6`, or `>= 4.6, < 5.0`)
    - only the kreuzwerker/docker provider is used (the marker runs `plan`,
      and some providers run programs during plan)
    - modules, if any, come from local folders (./ or ../), not the internet
    - no backend other than "local", no `cloud` block
    - every variable has a non-empty description
    - every root variable has a default (or a value in a committed
      terraform.tfvars / *.auto.tfvars) - `plan` runs with no -var flags
    - at least one resource block
    - infra/.terraform.lock.hcl is committed, names kreuzwerker/docker with
      a version that meets your constraint, and has checksums
  tool (with --tool; always in the real mark):
    - init, validate, `fmt -check -recursive` and `plan` all succeed
    - the plan creates at least one resource, all from kreuzwerker/docker

Exit code 0 only if every gate and every check that ran passed.
Nothing in this file is hidden from students: it is the rubric.
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

DEADLINE = "2026-12-06T23:59:59+05:00"       # Sunday 6 December, 23:59 Almaty
ALLOWED_PROVIDERS = {"kreuzwerker/docker"}   # namespace/type, any registry host
LOCAL_HOST_SCHEMES = ("unix://", "npipe://")   # provider "docker" host: local sockets only
REGISTRY_HOSTS = ("registry.terraform.io", "registry.opentofu.org")
LOCAL_NAME = "docker"                        # resource types start "docker_"


# ================================================================ helpers

def run(cmd, cwd=None, timeout=300, env=None):
    """Run a command, never raise. Returns (rc, stdout, stderr)."""
    e = dict(os.environ)
    if env:
        e.update(env)
    try:
        p = subprocess.run(cmd, cwd=cwd, env=e, timeout=timeout, capture_output=True,
                           encoding="utf-8", errors="replace")
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except OSError as exc:
        return 127, "", str(exc)


def repo_slug(url):
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else None


# ====================================================== credentials (= M1)

# Same two tiers as M1-M5, so a key is judged the same way in every milestone.
HIGH_CONFIDENCE = [
    (r"AKIA[0-9A-Z]{16}", "AWS access key id"),
    (r"gh[pousr]_[A-Za-z0-9]{36,}", "GitHub token"),
    (r"github_pat_[A-Za-z0-9_]{50,}", "GitHub fine-grained token"),
    (r"-----BEGIN (RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----", "private key"),
    (r"xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
]
DOC_VALUES = re.compile(r"(?i)(EXAMPLE|wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY)")
FUZZY = [
    (r"(?i)\b(api[_-]?key|secret|password|passwd|token)\s*[:=]\s*"
     r"['\"][^'\"\s]{12,}['\"]", "hardcoded credential"),
]
FUZZY_ALLOW = re.compile(
    r"(?i)(example|sample|placeholder|dummy|change[_-]?me|replace[_-]?me"
    r"|your[_\-\w]*|[_\-]here\b|xxx+|<[^>]+>|\$\{[^}]+\}|\bfake\b"
    r"|redacted|todo|test[_-]?token|secret[_-]?key[_-]?here)")


def scan_line(line):
    for pat, label in HIGH_CONFIDENCE:
        m = re.search(pat, line)
        if m and not DOC_VALUES.search(m.group(0)):
            return f"{label}: {m.group(0)[:40]}"
    for pat, label in FUZZY:
        m = re.search(pat, line)
        if m and not FUZZY_ALLOW.search(m.group(0)):
            return f"{label}: {m.group(0)[:60]}"
    return None


# ================================================= HCL (native syntax) parser
#
# A careful structural parser: blocks, attributes, literal values. Anything
# that is not a literal (references, function calls, templates with ${...})
# is kept as an Expr with its source text. That is all the checks need, and it
# means students install nothing. The tests cross-check it against python-hcl2.

class HCLError(Exception):
    def __init__(self, msg, line):
        super().__init__(f"line {line}: {msg}")
        self.line = line


class Str:            # a string with no interpolation - its value is known
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Str({self.value!r})"


class Expr:           # anything else: a reference, a call, a template ...
    def __init__(self, raw):
        self.raw = raw

    def __repr__(self):
        return f"Expr({self.raw!r})"


class Lit:            # number, true, false, null
    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Lit({self.value!r})"


class Tuple:
    def __init__(self, items):
        self.items = items


class Obj:
    def __init__(self, items):
        self.items = items          # list of (key text, value)

    def get(self, key):
        for k, v in self.items:
            if k == key:
                return v
        return None


class Attr:
    def __init__(self, name, value, line):
        self.name, self.value, self.line = name, value, line


class Block:
    def __init__(self, type_, labels, body, line):
        self.type, self.labels, self.body, self.line = type_, labels, body, line


class Body:
    def __init__(self):
        self.attrs = {}             # name -> Attr
        self.blocks = []            # Block, in order

    def blocks_of(self, type_):
        return [b for b in self.blocks if b.type == type_]


class Tok:
    def __init__(self, kind, text, line, value=None):
        self.kind, self.text, self.line, self.value = kind, text, line, value

    def __repr__(self):
        return f"Tok({self.kind},{self.text!r},{self.line})"


PUNCT3 = ("...",)
PUNCT2 = ("==", "!=", "<=", ">=", "&&", "||", "=>", "::")
PUNCT1 = "{}[](),=.:?!*/%+-<>"
IDENT_RE = re.compile(r"[^\W\d][\w-]*", re.UNICODE)
NUMBER_RE = re.compile(r"\d+(\.\d+)?([eE][+-]?\d+)?")
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}


def tokenize(src):
    toks, i, line, n = [], 0, 1, len(src)
    if src.startswith("﻿"):
        i = 1

    def interp_end(j, ln):
        """src[j] is just after '${' or '%{'. Return (index after the matching '}', line)."""
        depth = 1
        while j < n:
            c = src[j]
            if c == "\n":
                ln += 1
            if c == '"':
                _, _, j, ln = quoted(j + 1, ln)
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return j + 1, ln
            j += 1
        raise HCLError("unterminated ${...} in a string", ln)

    def quoted(j, ln):
        """src[j] is just after the opening quote. Returns (value or None, raw, end, line)."""
        start, out, has_interp = j, [], False
        while j < n:
            c = src[j]
            if c == '"':
                raw = src[start:j]
                return (None if has_interp else "".join(out)), raw, j + 1, ln
            if c == "\n":
                raise HCLError("a quoted string cannot contain a line break "
                               "(use a heredoc: <<EOT ... EOT)", ln)
            if c == "\\":
                if j + 1 >= n:
                    break
                e = src[j + 1]
                if e in ESCAPES:
                    out.append(ESCAPES[e])
                    j += 2
                    continue
                if e in "uU":
                    width = 4 if e == "u" else 8
                    hexd = src[j + 2:j + 2 + width]
                    if len(hexd) == width and all(h in "0123456789abcdefABCDEF" for h in hexd):
                        out.append(chr(int(hexd, 16)))
                        j += 2 + width
                        continue
                raise HCLError(f"invalid escape \\{e} in a string", ln)
            if src.startswith("$${", j) or src.startswith("%%{", j):
                out.append(src[j + 1:j + 3])
                j += 3
                continue
            if src.startswith("${", j) or src.startswith("%{", j):
                has_interp = True
                j, ln = interp_end(j + 2, ln)
                continue
            out.append(c)
            j += 1
        raise HCLError("unterminated string", ln)

    while i < n:
        c = src[i]
        if c in " \t\r":
            i += 1
            continue
        if c == "\n":
            toks.append(Tok("NL", "\n", line))
            line += 1
            i += 1
            continue
        if c == "#" or src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            if end < 0:
                raise HCLError("unterminated /* comment", line)
            line += src.count("\n", i, end)
            i = end + 2
            continue
        if c == '"':
            start_line = line
            value, raw, i, line = quoted(i + 1, line)
            toks.append(Tok("STR", raw, start_line, value))
            continue
        if src.startswith("<<", i):
            m = re.match(r"<<(-?)([^\W\d][\w-]*)[ \t]*\r?\n", src[i:])
            if m:
                marker, start_line = m.group(2), line
                j = i + m.end()
                line += 1
                lines, closed = [], False
                while j <= n:
                    k = src.find("\n", j)
                    if k < 0:
                        k = n
                    text = src[j:k].rstrip("\r")
                    if text.strip() == marker:
                        closed = True
                        j = k
                        break
                    lines.append(text)
                    line += 1
                    j = k + 1
                    if k >= n:
                        break
                if not closed:
                    raise HCLError(f"heredoc <<{marker} is never closed", start_line)
                body = "\n".join(lines) + ("\n" if lines else "")
                has_interp = re.search(r"(?<![$%])[$%]\{", body) is not None
                if m.group(1) == "-":
                    ind = min((len(t) - len(t.lstrip()) for t in lines if t.strip()), default=0)
                    body = "\n".join(t[ind:] for t in lines) + ("\n" if lines else "")
                value = None if has_interp else body.replace("$${", "${").replace("%%{", "%{")
                toks.append(Tok("STR", body, start_line, value))
                i = j
                continue
        m = NUMBER_RE.match(src, i)
        if m and c.isdigit():
            toks.append(Tok("NUM", m.group(0), line, float(m.group(0))))
            i = m.end()
            continue
        m = IDENT_RE.match(src, i)
        if m:
            toks.append(Tok("ID", m.group(0), line))
            i = m.end()
            continue
        for p in PUNCT3 + PUNCT2:
            if src.startswith(p, i):
                toks.append(Tok("P", p, line))
                i += len(p)
                break
        else:
            if c in PUNCT1:
                toks.append(Tok("P", c, line))
                i += 1
            else:
                raise HCLError(f"unexpected character {c!r}", line)
    toks.append(Tok("EOF", "", line))
    return toks


OPEN, CLOSE = {"(": ")", "[": "]", "{": "}"}, {")", "]", "}"}


class Parser:
    def __init__(self, toks):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[min(self.i + k, len(self.t) - 1)]

    def body(self, until_brace):
        b = Body()
        while True:
            tok = self.peek()
            if tok.kind == "NL":
                self.i += 1
                continue
            if tok.kind == "EOF":
                if until_brace:
                    raise HCLError("a block is missing its closing '}'", tok.line)
                return b
            if tok.kind == "P" and tok.text == "}":
                if until_brace:
                    return b
                raise HCLError("unexpected '}'", tok.line)
            if tok.kind != "ID":
                raise HCLError(f"expected an argument or block name, found {tok.text!r}", tok.line)
            name, line = tok.text, tok.line
            nxt = self.peek(1)
            if nxt.kind == "P" and nxt.text == "=":
                self.i += 2
                value = self.expr(stop={"NL", "EOF", "}"})
                if name in b.attrs:
                    raise HCLError(f"the argument {name!r} is set twice", line)
                b.attrs[name] = Attr(name, value, line)
                end = self.peek()
                if end.kind == "P" and end.text == "}" and not until_brace:
                    raise HCLError("unexpected '}'", end.line)
                continue
            self.i += 1
            labels = []
            while self.peek().kind in ("STR", "ID"):
                lt = self.peek()
                if lt.kind == "STR" and lt.value is None:
                    raise HCLError("a block label cannot contain ${...}", lt.line)
                labels.append(lt.value if lt.kind == "STR" else lt.text)
                self.i += 1
            ob = self.peek()
            if not (ob.kind == "P" and ob.text == "{"):
                raise HCLError(f"expected '=' or '{{' after {name!r}, found {ob.text!r}", ob.line)
            self.i += 1
            inner = self.body(until_brace=True)
            self.i += 1                                     # the '}'
            b.blocks.append(Block(name, labels, inner, line))

    def expr(self, stop):
        """Parse one expression up to a stop token at depth 0. Returns a value."""
        start, depth = self.i, 0
        while True:
            tok = self.peek()
            if tok.kind == "EOF":
                if depth:
                    raise HCLError("unclosed bracket in an expression", tok.line)
                break
            if depth == 0 and (tok.kind in stop or (tok.kind == "P" and tok.text in stop)):
                break
            if tok.kind == "P" and tok.text in OPEN:
                depth += 1
            elif tok.kind == "P" and tok.text in CLOSE:
                if depth == 0:
                    break
                depth -= 1
            self.i += 1
        toks = [t for t in self.t[start:self.i]]
        if not [t for t in toks if t.kind != "NL"]:
            line = self.peek().line
            raise HCLError("an argument has no value after '='", line)
        return value_of(toks)


def raw_text(toks):
    out = []
    for t in toks:
        if t.kind == "STR":
            out.append('"' + t.text + '"')
        elif t.kind != "NL":
            out.append(t.text)
    return " ".join(out)


def split_top(toks, seps):
    """Split tokens at depth-0 separators (',' and/or newlines)."""
    parts, cur, depth = [], [], 0
    for t in toks:
        if t.kind == "P" and t.text in OPEN:
            depth += 1
        elif t.kind == "P" and t.text in CLOSE:
            depth -= 1
        if depth == 0 and ((t.kind == "P" and t.text in seps) or (t.kind == "NL" and "NL" in seps)):
            parts.append(cur)
            cur = []
            continue
        cur.append(t)
    parts.append(cur)
    return [p for p in parts if [t for t in p if t.kind != "NL"]]


def value_of(toks):
    core = [t for t in toks if t.kind != "NL"]
    if len(core) == 1:
        t = core[0]
        if t.kind == "STR":
            return Str(t.value) if t.value is not None else Expr('"' + t.text + '"')
        if t.kind == "NUM":
            return Lit(t.value)
        if t.kind == "ID" and t.text in ("true", "false", "null"):
            return Lit({"true": True, "false": False, "null": None}[t.text])
    if core and core[0].kind == "P" and core[0].text in ("[", "{") and matching(core) == len(core) - 1:
        inner = toks[toks.index(core[0]) + 1:len(toks) - toks[::-1].index(core[-1]) - 1]
        first = next((t for t in inner if t.kind != "NL"), None)
        if first is not None and first.kind == "ID" and first.text == "for":
            return Expr(raw_text(core))
        if core[0].text == "[":
            return Tuple([value_of(p) for p in split_top(inner, {","})])
        items = []
        for part in split_top(inner, {",", "NL"}):
            pc = [t for t in part if t.kind != "NL"]
            eq = next((k for k, t in enumerate(pc) if t.kind == "P" and t.text in ("=", ":")), None)
            if eq is None or eq == 0:
                return Expr(raw_text(core))
            key_toks = pc[:eq]
            if len(key_toks) == 1 and key_toks[0].kind == "ID":
                key = key_toks[0].text
            elif len(key_toks) == 1 and key_toks[0].kind == "STR" and key_toks[0].value is not None:
                key = key_toks[0].value
            else:
                key = raw_text(key_toks)
            items.append((key, value_of(pc[eq + 1:])))
        return Obj(items)
    return Expr(raw_text(core))


def matching(core):
    """Index of the bracket that closes core[0], or -1."""
    depth = 0
    for k, t in enumerate(core):
        if t.kind == "P" and t.text in OPEN:
            depth += 1
        elif t.kind == "P" and t.text in CLOSE:
            depth -= 1
            if depth == 0:
                return k
    return -1


def parse_hcl(src):
    """Parse HCL native syntax into a Body. Raises HCLError with a line number."""
    return Parser(tokenize(src)).body(until_brace=False)


# ======================================================= version constraints
#
# Terraform reads provider constraints with apparentlymart/go-versions,
# "Ruby style": "~> 4.6" means >= 4.6.0, < 5.0.0 (one or two numbers keep the
# major); "~> 4.6.1" means >= 4.6.1, < 4.7.0 (three numbers keep the minor).

CLAUSE = re.compile(r"^\s*(~>|>=|<=|!=|=|>|<)?\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(-[0-9A-Za-z.-]+)?\s*$")


def parse_constraint(text):
    """Return a list of (op, (major, minor, patch), ndigits, prerelease) or raise ValueError."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty")
    out = []
    for part in text.split(","):
        m = CLAUSE.match(part)
        if not m:
            raise ValueError(f"cannot read {part.strip()!r}")
        op = m.group(1) or "="
        nums = [int(x) if x is not None else 0 for x in m.group(2, 3, 4)]
        digits = sum(1 for x in m.group(2, 3, 4) if x is not None)
        out.append((op, tuple(nums), digits, m.group(5) or ""))
    return out


def upper_bounded(clauses):
    return any(op in ("~>", "=", "<", "<=") for op, _, _, _ in clauses)


def satisfies(version, clauses):
    """Does version text like '4.6.0' meet every clause?"""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?$", version or "")
    if not m:
        return False
    v, pre = tuple(int(x) for x in m.group(1, 2, 3)), m.group(4) or ""
    for op, c, digits, cpre in clauses:
        if pre and not (op == "=" and cpre == pre and v == c):
            return False                      # pre-releases only match an exact =
        if op == "=":
            ok = v == c and pre == cpre
        elif op == "!=":
            ok = not (v == c and pre == cpre)
        elif op == ">":
            ok = v > c
        elif op == ">=":
            ok = v >= c
        elif op == "<":
            ok = v < c
        elif op == "<=":
            ok = v <= c
        else:                                 # ~>
            upper = (c[0], c[1] + 1, 0) if digits == 3 else (c[0] + 1, 0, 0)
            ok = c <= v < upper
        if not ok:
            return False
    return True


def provider_address(source):
    """'kreuzwerker/docker' or 'registry.terraform.io/kreuzwerker/docker' -> 'kreuzwerker/docker'."""
    parts = [p for p in (source or "").strip().lower().split("/") if p]
    if len(parts) == 3:
        return f"{parts[1]}/{parts[2]}"
    if len(parts) == 2:
        return f"{parts[0]}/{parts[1]}"
    if len(parts) == 1:
        return f"hashicorp/{parts[0]}"        # Terraform's default namespace
    return ""


# ================================================================ git helpers

def git(args, cwd, timeout=180):
    rc, out, err = run(["git"] + args, cwd=cwd, timeout=timeout)
    return rc, out, err


def tree_files(path, commit):
    rc, out, _ = git(["ls-tree", "-r", "--name-only", "-z", commit], path)
    return [f for f in out.split("\0") if f] if rc == 0 else None


def read_at(path, commit, name):
    rc, out, _ = git(["show", f"{commit}:{name}"], path)
    return out if rc == 0 else None


def history_names(path):
    rc, out, _ = git(["log", "--all", "--format=", "--name-only", "-z", "--no-renames"], path, 300)
    if rc != 0:
        return None
    return sorted({f.strip("\n") for f in out.split("\0") if f.strip("\n")})


def is_state_path(name):
    parts = name.replace("\\", "/").split("/")
    base = parts[-1]
    if ".terraform" in parts[:-1]:
        return True                            # anything inside a .terraform/ folder
    return fnmatch.fnmatch(base, "*.tfstate") or fnmatch.fnmatch(base, "*.tfstate.*")


# ================================================================ context

def build_ctx(path, commit="HEAD"):
    rc, out, _ = git(["rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}"], path)
    sha = out.strip() if rc == 0 else ""
    files = tree_files(path, sha) if sha else None
    ctx = {"path": path, "commit": commit, "sha": sha, "files": files or [],
           "is_repo": files is not None, "tf": {}, "parse_errors": {}, "notes": [],
           "warnings": []}
    infra = [f for f in ctx["files"] if f.startswith("infra/")]
    ctx["infra_files"] = infra
    ctx["tf_text"] = {}
    for f in infra:
        if f.endswith(".tf"):
            text = read_at(path, sha, f) or ""
            ctx["tf_text"][f] = text
            try:
                ctx["tf"][f] = parse_hcl(text)
            except HCLError as exc:
                ctx["parse_errors"][f] = str(exc)
    ctx["root_tf"] = sorted(f for f in ctx["tf"] if f.count("/") == 1)
    ctx["root_tf_all"] = sorted(f for f in infra if f.count("/") == 1 and f.endswith(".tf"))
    if sha:
        rc, out, _ = git(["status", "--porcelain", "--", "infra", ".gitignore"], path)
        if rc == 0 and out.strip() and commit in ("HEAD", sha):
            ctx["notes"].append("you have uncommitted changes in infra/ or .gitignore - "
                                "the marker only sees what you commit and push")
    return ctx


def all_blocks(ctx, type_, root_only=False):
    for f, body in sorted(ctx["tf"].items()):
        if root_only and f.count("/") != 1:
            continue
        for b in body.blocks_of(type_):
            yield f, b


# ================================================================ gates

def gate_terraform(ctx):
    if not ctx["is_repo"]:
        return False, "not a git repository (or no commits yet), so nothing is committed"
    if not ctx["root_tf_all"]:
        if [f for f in ctx["infra_files"] if f.endswith(".tf.json")]:
            return False, "infra/ has only .tf.json files - write the configuration as .tf"
        return False, ("no committed .tf file directly in infra/ - "
                       "Terraform for M6 lives in infra/*.tf")
    n_res = sum(1 for _ in all_blocks(ctx, "resource", root_only=True))
    return True, f"{len(ctx['root_tf_all'])} .tf file(s), {n_res} resource block(s)"


def gate_no_state(ctx):
    now = [f for f in ctx["files"] if is_state_path(f)]
    if now:
        return False, (f"Terraform state or cache is committed: {', '.join(now[:3])} - "
                       "state holds IDs and secrets; .terraform/ is a download cache")
    hist = history_names(ctx["path"])
    if hist is None:
        return False, "could not read the git history"
    old = [f for f in hist if is_state_path(f)]
    if old:
        return False, (f"Terraform state or cache is in the history: {', '.join(old[:3])} - "
                       "deleting it later does not remove it; see Common failures in the lab brief")
    return True, "no .tfstate and no .terraform/ in the tree or the history"


def gate_no_secrets(ctx):
    rc, out, _ = git(["log", "-p", "--all", "--no-color"], ctx["path"], 300)
    if rc != 0:
        return False, "could not read the git history"
    hits = [h for h in (scan_line(l) for l in out.splitlines() if l.startswith("+")) if h]
    if hits:
        return False, "credential found in git history - " + "; ".join(sorted(set(hits))[:3])
    return True, "no credentials in the history"


GATES = [("Terraform in infra/", gate_terraform),
         ("no state in Git", gate_no_state),
         ("no credentials", gate_no_secrets)]


# ================================================================ block: static

def blanks_left(text):
    """Lines where a lab blank (____) is still in the code (comments do not count)."""
    try:
        toks = tokenize(text)
    except HCLError:
        return []
    return sorted({t.line for t in toks if t.kind in ("ID", "STR") and "____" in t.text})


def static_problems(ctx):
    problems = []
    for f in sorted(ctx.get("tf_text", {})):
        for line in blanks_left(ctx["tf_text"][f]):
            problems.append(f"{f}:{line}: a blank (____) is still here - fill it in")
    for f, err in sorted(ctx["parse_errors"].items()):
        problems.append(f"{f} does not parse: {err}")
    for f in ctx["infra_files"]:
        if f.endswith(".tf.json"):
            problems.append(f"{f}: JSON configuration is not used in this course - write .tf files")

    # --- the provider requirement
    reqs = []
    for f, tb in all_blocks(ctx, "terraform", root_only=True):
        for rp in tb.body.blocks_of("required_providers"):
            for name, attr in rp.body.attrs.items():
                reqs.append((f, name, attr))
    docker = [r for r in reqs if r[1] == LOCAL_NAME]
    if not docker:
        problems.append('no required_providers entry for "docker" - the terraform block must say '
                        'docker = { source = "kreuzwerker/docker", version = "~> 4.6" }')
    for f, name, attr in reqs:
        v = attr.value
        source = v.get("source") if isinstance(v, Obj) else None
        version = v.get("version") if isinstance(v, Obj) else None
        if isinstance(v, Str):
            problems.append(f'{f}:{attr.line}: {name} = "..." is the old short form - use '
                            f'{name} = {{ source = "...", version = "..." }}')
            continue
        if not isinstance(v, Obj):
            problems.append(f"{f}:{attr.line}: {name} must be an object with source and version")
            continue
        addr = provider_address(source.value) if isinstance(source, Str) else ""
        if not isinstance(source, Str) or not addr:
            problems.append(f'{f}:{attr.line}: {name} has no source - write source = "kreuzwerker/docker"')
        elif addr not in ALLOWED_PROVIDERS:
            problems.append(f"{f}:{attr.line}: provider {source.value!r} is not allowed here - "
                            "M6 uses only kreuzwerker/docker (the marker runs plan, and some "
                            "providers run programs during plan)")
            continue
        if not isinstance(version, Str) or not version.value.strip():
            problems.append(f"{f}:{attr.line}: {name} has no version constraint - pin what you "
                            'borrow: version = "~> 4.6"')
            continue
        try:
            clauses = parse_constraint(version.value)
        except ValueError as exc:
            problems.append(f"{f}:{attr.line}: cannot read the version constraint "
                            f"{version.value!r} ({exc})")
            continue
        if not upper_bounded(clauses):
            problems.append(f"{f}:{attr.line}: version {version.value!r} has no upper bound - the next "
                            'major version could break you. Use "~> 4.6" (or add "< 5.0")')
        if name == LOCAL_NAME:
            ctx["docker_constraint"] = clauses
            ctx["docker_constraint_text"] = version.value

    # --- nothing but the Docker provider
    for f, body in sorted(ctx["tf"].items()):
        for b in body.blocks_of("provider"):
            if b.labels and b.labels[0] != LOCAL_NAME:
                problems.append(f'{f}:{b.line}: provider "{b.labels[0]}" is not allowed - M6 uses only '
                                "kreuzwerker/docker")
                continue
            # The marker runs plan on a shared runner. An ssh:// host (or ssh_opts) makes the
            # provider start ssh, and SSH options can run any program - so only a local Docker
            # socket is accepted: no host at all, or a literal unix:// or npipe:// address.
            if "context" in b.body.attrs:
                problems.append(f'{f}:{b.body.attrs["context"].line}: provider "docker" sets '
                                "context - not allowed: M6 uses your local Docker only "
                                "(a Docker context can point at another machine over SSH)")
            if "ssh_opts" in b.body.attrs:
                problems.append(f'{f}:{b.body.attrs["ssh_opts"].line}: provider "docker" sets '
                                "ssh_opts - not allowed: M6 uses your local Docker only "
                                "(SSH options can run programs during plan)")
            host = b.body.attrs.get("host")
            if host is not None:
                hv = host.value.value if isinstance(host.value, Str) else None
                if hv is None or not hv.strip().lower().startswith(LOCAL_HOST_SCHEMES):
                    shown = repr(hv) if hv is not None else "an expression"
                    problems.append(f'{f}:{host.line}: provider "docker" sets host = {shown} - '
                                    "M6 uses your local Docker only: delete host, or write a "
                                    'literal "unix://..." or "npipe://..." address')
        for kind in ("resource", "data", "ephemeral"):
            for b in body.blocks_of(kind):
                t = b.labels[0] if b.labels else ""
                if not (t == LOCAL_NAME or t.startswith(LOCAL_NAME + "_")):
                    what = "data source" if kind == "data" else kind
                    problems.append(f'{f}:{b.line}: {what} "{t}" is not from the Docker provider - '
                                    "M6 uses only kreuzwerker/docker")
        for b in body.blocks_of("module"):
            src = b.body.attrs.get("source")
            s = src.value.value if src and isinstance(src.value, Str) else None
            if not s or not (s.startswith("./") or s.startswith("../")):
                label = b.labels[0] if b.labels else "?"
                problems.append(f'{f}:{b.line}: module "{label}" must come from a local folder '
                                '(source = "./modules/..."), not the internet')

    # --- state stays local: no backend, no cloud
    for f, tb in all_blocks(ctx, "terraform"):
        for bb in tb.body.blocks_of("backend"):
            kind = bb.labels[0] if bb.labels else "?"
            if kind != "local":
                problems.append(f'{f}:{bb.line}: backend "{kind}" - the marker plans with no '
                                "credentials, so M6 keeps state local (delete the backend block)")
        for cb in tb.body.blocks_of("cloud"):
            problems.append(f"{f}:{cb.line}: a cloud block (HCP Terraform) - M6 keeps state local")

    # --- variables: described, and resolvable with no -var flags
    tfvars = committed_tfvars(ctx)
    for f, b in all_blocks(ctx, "variable"):
        name = b.labels[0] if b.labels else "?"
        d = b.body.attrs.get("description")
        if d is None:
            problems.append(f'{f}:{b.line}: variable "{name}" has no description')
        elif not isinstance(d.value, Str):
            problems.append(f'{f}:{b.line}: variable "{name}": the description must be plain text '
                            "in quotes")
        elif not d.value.value.strip():
            problems.append(f'{f}:{b.line}: variable "{name}" has an empty description')
        if f.count("/") == 1 and "default" not in b.body.attrs and name not in tfvars:
            problems.append(f'{f}:{b.line}: variable "{name}" has no default - the marker runs '
                            "plan with no -var flags, so give it a default")

    # --- at least one resource
    if not any(True for _ in all_blocks(ctx, "resource", root_only=True)) and \
            not any(True for _ in all_blocks(ctx, "module", root_only=True)):
        problems.append("infra/ has no resource block - plan would propose nothing")

    # --- the lock file
    lock_name = "infra/.terraform.lock.hcl"
    if lock_name not in ctx["files"]:
        problems.append("infra/.terraform.lock.hcl is not committed - it pins the provider version "
                        "and its checksums. `terraform init` writes it; git add it")
    else:
        text = read_at(ctx["path"], ctx["sha"], lock_name) or ""
        try:
            lock = parse_hcl(text)
        except HCLError as exc:
            problems.append(f"{lock_name} does not parse: {exc}")
            lock = Body()
        found = [b for b in lock.blocks_of("provider")
                 if b.labels and provider_address(b.labels[0]) in ALLOWED_PROVIDERS]
        if not found:
            problems.append(f"{lock_name} does not list kreuzwerker/docker - run `terraform init` "
                            "again and commit the new lock file")
        for b in found:
            ver = b.body.attrs.get("version")
            hashes = b.body.attrs.get("hashes")
            v = ver.value.value if ver and isinstance(ver.value, Str) else ""
            if not v:
                problems.append(f"{lock_name}: the kreuzwerker/docker entry has no version")
            elif ctx.get("docker_constraint") and not satisfies(v, ctx["docker_constraint"]):
                problems.append(f"{lock_name}: locked version {v} does not meet your constraint "
                                f"{ctx['docker_constraint_text']!r} - run `terraform init -upgrade` "
                                "and commit the lock file")
            if not (hashes and isinstance(hashes.value, Tuple) and hashes.value.items):
                problems.append(f"{lock_name}: the kreuzwerker/docker entry has no checksums")
    return problems


def committed_tfvars(ctx):
    names = set()
    for f in ctx["files"]:
        if f.count("/") != 1 or not f.startswith("infra/"):
            continue
        base = f.split("/")[1]
        if base in ("terraform.tfvars",) or fnmatch.fnmatch(base, "*.auto.tfvars"):
            try:
                names.update(parse_hcl(read_at(ctx["path"], ctx["sha"], f) or "").attrs)
            except HCLError:
                pass
        elif base in ("terraform.tfvars.json",) or fnmatch.fnmatch(base, "*.auto.tfvars.json"):
            try:
                names.update(json.loads(read_at(ctx["path"], ctx["sha"], f) or "{}"))
            except ValueError:
                pass
    return names


def ignore_warnings(ctx):
    """Prevention, not points: would `git add .` pick up state? Working tree only."""
    if ctx["commit"] not in ("HEAD",) or not os.path.isdir(os.path.join(ctx["path"], ".git")):
        return []
    warns = []
    for probe in ("infra/terraform.tfstate", "infra/terraform.tfstate.backup",
                  "infra/.terraform/providers/x"):
        rc, _, _ = git(["check-ignore", "-q", "--no-index", probe], ctx["path"])
        if rc == 1:
            warns.append(f"{probe.split('/providers')[0]} is not ignored by .gitignore - one "
                         "`git add .` away from a zero (add *.tfstate, *.tfstate.* and .terraform/)")
    rc, _, _ = git(["check-ignore", "-q", "--no-index", "infra/.terraform.lock.hcl"], ctx["path"])
    if rc == 0:
        warns.append("infra/.terraform.lock.hcl is ignored by .gitignore - remove that line; "
                     "the lock file must be committed")
    return warns


# ================================================================ block: tool

def export_infra(ctx, dest):
    """Copy the committed infra/ (at the marked commit) into dest, without tar or a shell."""
    for name in ctx["infra_files"]:
        p = subprocess.run(["git", "show", f"{ctx['sha']}:{name}"], cwd=ctx["path"],
                           capture_output=True)
        if p.returncode != 0:
            return False, p.stderr.decode("utf-8", "replace")[:200]
        target = os.path.join(dest, *name.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(p.stdout)
    return True, ""


def first_lines(text, n=6):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    pick = []
    for i, l in enumerate(lines):
        if "Error" in l or "error" in l:
            # Terraform puts the detail (e.g. the registry or network message) on the
            # line after "Error: ...", so keep that line too.
            for j in (i, i + 1):
                if j < len(lines) and lines[j] not in pick:
                    pick.append(lines[j])
        if len(pick) >= n:
            break
    pick = pick[:n] if pick else lines[:n]
    return " | ".join(l.strip() for l in pick)[:600]


def tool_problems(ctx, tool):
    """Run init, validate, fmt -check and plan on a copy of the committed infra/."""
    exe = shutil.which(tool) if not os.path.sep in tool else (tool if os.path.exists(tool) else None)
    if not exe:
        return None, [f"{tool!r} was not found on PATH"]
    tmp = tempfile.mkdtemp(prefix="m6-iac-")
    problems, facts = [], []
    tool = os.path.basename(tool)
    try:
        ok, err = export_infra(ctx, tmp)
        if not ok:
            return None, [f"could not copy infra/ out of the commit: {err}"]
        work = os.path.join(tmp, "infra")
        cache = os.environ.get("TF_PLUGIN_CACHE_DIR") or os.path.join(
            tempfile.gettempdir(), "inf345-tf-plugin-cache")
        os.makedirs(cache, exist_ok=True)
        env = {"TF_IN_AUTOMATION": "1", "TF_INPUT": "0", "TF_PLUGIN_CACHE_DIR": cache,
               "CHECKPOINT_DISABLE": "1"}
        steps = [("init", [exe, "init", "-input=false", "-no-color"]),
                 ("validate", [exe, "validate", "-no-color"]),
                 ("fmt -check", [exe, "fmt", "-check", "-recursive", "-no-color"]),
                 ("plan", [exe, "plan", "-input=false", "-no-color", "-lock=false",
                           "-out=m6.tfplan"])]
        for name, cmd in steps:
            rc, out, err = run(cmd, cwd=work, env=env, timeout=600)
            if rc != 0:
                if name == "fmt -check":
                    files = ", ".join(l.strip() for l in out.splitlines() if l.strip())[:300]
                    problems.append(f"`{tool} fmt -check` failed - not formatted: {files or first_lines(err)}"
                                    f" (run `{tool} fmt` in infra/ and commit)")
                else:
                    problems.append(f"`{tool} {name}` failed: {first_lines(err or out)}")
                if name in ("init", "validate"):
                    return False, problems            # later steps cannot run
                continue
            facts.append(name)
        if "plan" in facts:
            rc, out, err = run([exe, "show", "-json", "m6.tfplan"], cwd=work, env=env, timeout=300)
            try:
                plan = json.loads(out)
            except ValueError:
                problems.append(f"`{tool} show -json` did not print JSON: {first_lines(err)}")
                return False, problems
            creates, foreign = plan_summary(plan)
            if creates == 0:
                problems.append("the plan creates no resource - M6 needs at least one")
            for f in foreign:
                problems.append(f"the plan uses provider {f} - M6 uses only kreuzwerker/docker")
            ctx["plan_creates"] = creates
        return not problems, problems
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def plan_summary(plan):
    creates, foreign = 0, set()
    for rc in plan.get("resource_changes") or []:
        if rc.get("mode") != "managed":
            continue
        if "create" in (rc.get("change") or {}).get("actions", []):
            creates += 1
        addr = provider_address(rc.get("provider_name", ""))
        if addr and addr not in ALLOWED_PROVIDERS:
            foreign.add(rc.get("provider_name"))
    return creates, sorted(foreign)


# ================================================================ report

def mark(ctx, tool=None, as_json=False):
    rep = {"repo": ctx.get("slug") or ctx["path"], "commit": ctx["sha"], "gates": [],
           "block": {"name": "infrastructure is code", "points": None, "problems": [],
                     "static_ok": None, "tool": tool, "tool_ok": None},
           "warnings": [], "notes": ctx["notes"], "capped": False}
    for name, fn in GATES:
        ok, detail = fn(ctx)
        rep["gates"].append({"name": name, "ok": ok, "detail": detail})
        rep["capped"] = rep["capped"] or not ok
    code = 1
    if not rep["capped"]:
        probs = static_problems(ctx)
        rep["block"]["static_ok"] = not probs
        rep["block"]["problems"] = list(probs)
        if tool and not probs:
            ok, tprobs = tool_problems(ctx, tool)
            if ok is None:          # the tool could not run at all: not the student's fault
                rep["block"]["tool_ok"] = None
                rep["block"]["not_checked"] = "; ".join(tprobs)
            else:
                rep["block"]["tool_ok"] = ok
                rep["block"]["problems"] += tprobs
        elif tool and probs:
            rep["block"]["problems"].append(f"{tool} was not run: fix the problems above first "
                                            "(the marker never runs plan on a configuration "
                                            "that fails the static checks)")
            rep["block"]["tool_ok"] = False
        if rep["block"]["problems"]:
            rep["block"]["points"] = 0
        elif rep["block"]["tool_ok"]:
            rep["block"]["points"] = 25
        rep["warnings"] = ignore_warnings(ctx)
        code = 0 if not rep["block"]["problems"] and (tool is None or rep["block"]["tool_ok"]) else 1
    if as_json:
        print(json.dumps(rep, indent=2))
        return code

    print(f"\n  M6 - infrastructure as code, for {rep['repo']}")
    if ctx["sha"]:
        print(f"  commit {ctx['sha'][:7]}")
    print()
    for g in rep["gates"]:
        print(f"  [gate {'ok ' if g['ok'] else 'FAIL'}] {g['name']}: {g['detail']}")
    if rep["capped"]:
        print("\n  A gate failed, so M6 scores 0.\n\nRESULT: 0/25 (gates)")
        return 1
    b = rep["block"]
    print()
    if b["problems"]:
        print(f"  [  0/25 ] {b['name']}")
        for p in b["problems"]:
            print(f"            - {p}")
    elif b["points"] == 25:
        print(f"  [ 25/25 ] {b['name']}")
        print(f"            static checks pass; {os.path.basename(tool)} init, validate, fmt -check and plan pass"
              f" (plan creates {ctx.get('plan_creates', '?')} resource(s))")
    elif b.get("not_checked"):
        print(f"  [ --/25 ] {b['name']}")
        print("            static checks pass. The tool checks were NOT CHECKED:")
        print(f"            {b['not_checked']}")
    else:
        print(f"  [ --/25 ] {b['name']}")
        print("            static checks pass. init, validate, fmt -check and plan were NOT run -")
        print("            add --tool terraform (or --tool tofu). The real mark runs them.")
    for w in rep["warnings"]:
        print(f"  warning: {w}")
    for n in rep["notes"]:
        print(f"  note: {n}")
    if b["points"] == 25:
        print("\nRESULT: 25/25")
    elif b["points"] == 0:
        print("\nRESULT: 0/25")
    elif b.get("not_checked"):
        print("\nRESULT: static checks pass (tool checks NOT CHECKED - see above)")
    else:
        print("\nRESULT: static checks pass (tool checks not run)")
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the INF 345 M6 infrastructure-as-code block.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo", help="https://github.com/<user>/<project> - cloned fresh")
    src.add_argument("--path", help="a local checkout")
    ap.add_argument("--commit", default="HEAD", help="the commit to check (default HEAD)")
    ap.add_argument("--tool", help="terraform or tofu (or a path): also run init, validate, "
                                   "fmt -check and plan on a copy of the committed infra/")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    def go(path, slug):
        ctx = build_ctx(path, a.commit)
        ctx["slug"] = slug
        return mark(ctx, a.tool, a.json)

    if a.path:
        path = os.path.abspath(a.path)
        rc, out, _ = run(["git", "remote", "get-url", "origin"], cwd=path)
        return go(path, repo_slug(out.strip()) if rc == 0 else None)
    tmp = tempfile.mkdtemp(prefix="m6-")
    try:
        rc, _, err = run(["git", "clone", "--quiet", a.repo, tmp], timeout=300)
        if rc != 0:
            print(f"::error::could not clone {a.repo}: {err.strip()[:200]}")
            return 1
        return go(tmp, repo_slug(a.repo))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
