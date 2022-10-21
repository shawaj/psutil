#!/usr/bin/env python3

# Copyright (c) 2009, Giampaolo Rodola'. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Bot triggered by Github Actions every time a new issue, PR or comment
is created. Assign labels, provide replies, closes issues, etc. depending
on the situation.
"""

import functools
import json
import os
import re
from pprint import pprint as pp

from github import Github


ROOT_DIR = os.path.realpath(
    os.path.join(os.path.dirname(__file__), '..', '..')
)
SCRIPTS_DIR = os.path.join(ROOT_DIR, 'scripts')


# --- constants


LABELS_MAP = {
    # platforms
    "linux": [
        "/proc/disk",
        "/proc/net",
        "/proc/smaps",
        "/proc/vmstat",
        "/sys/class",
        "alpine",
        "apt ",
        "apt-",
        "archlinux",
        "centos",
        "debian",
        "fedora",
        "gentoo",
        "kali",
        "linux",
        "manylinux",
        "mint",
        "opensuse",
        "red hat",
        "redhat",
        "RHEL",
        "rpm",
        "slackware",
        "suse",
        "ubuntu",
        "yum",
    ],
    "windows": [
        ".bat",
        "appveyor",
        "CloseHandle",
        "DLL",
        "GetLastError",
        "make.bat",
        "microsoft",
        "mingw",
        "MSVC",
        "msys",
        "NtQuery",
        "NTSTATUS",
        "NtWow64",
        "OpenProcess",
        "studio",
        "TCHAR",
        "TerminateProcess",
        "Visual Studio",
        "WCHAR",
        "win ",
        "win10",
        "win32",
        "win7",
        "windows error",
        "windows",
        "WindowsError",
        "WinError",
    ],
    "macos": [
        "big sur",
        "capitan",
        "catalina",
        "darwin",
        "dylib",
        "m1",
        "mac ",
        "macos",
        "mojave",
        "mojave",
        "os x",
        "osx",
        "sierra",
        "xcode",
        "yosemite",
    ],
    "aix": ["aix"],
    "cygwin": ["cygwin"],
    "freebsd": ["freebsd"],
    "netbsd": ["netbsd"],
    "openbsd": ["openbsd"],
    "sunos": ["sunos", "solaris"],
    "wsl": ["wsl"],
    "unix": [
        "/dev/pts",
        "/dev/tty",
        "_psutil_posix",
        "psposix",
        "statvfs",
        "waitpid",
    ],
    "pypy": ["pypy"],
    # types
    "enhancement": ["enhancement"],
    "memleak": ["memory leak", "leaks memory", "memleak", "mem leak"],
    "api": ["idea", "proposal", "api", "feature"],
    "performance": ["performance", "speedup", "speed up", "slow", "fast"],
    "wheels": ["wheel", "wheels"],
    "scripts": [
        "example dir",
        "example script",
        "examples script",
        "scripts/",
    ],
    # bug
    "bug": [
        "can't execute",
        "can't install",
        "cannot execute",
        "cannot install",
        "crash",
        "critical",
        "fail",
        "install error",
    ],
    # doc
    "doc": [
        "dev guide",
        "devguide",
        "doc ",
        "docfix",
        "document ",
        "documentation",
        "HISTORY",
        "index.rst",
        "pythonhosted",
        "README",
        "readthedocs",
        "sphinx",
    ],
    # tests
    "tests": [
        " test ",
        "appveyor",
        "cirrus",
        "continuous integration",
        "coverage",
        "pytest",
        "tests",
        "travis",
        "unit test",
        "unittest",
    ],
    # critical errors
    "priority-high": [
        "core dumped",
        "MemoryError",
        "RuntimeError",
        "segfault",
        "segmentation fault",
        "SystemError",
        "WindowsError",
        "WinError",
        "ZeroDivisionError",
    ],
}

LABELS_MAP['scripts'].extend(
    [x for x in os.listdir(SCRIPTS_DIR) if x.endswith('.py')]
)

OS_LABELS = [
    "aix",
    "bsd",
    "cygwin",
    "freebsd",
    "linux",
    "macos",
    "netbsd",
    "openbsd",
    "openbsd",
    "sunos",
    "unix",
    "windows",
    "wsl",
]

ILLOGICAL_PAIRS = [
    ('bug', 'enhancement'),
    ('doc', 'tests'),
    ('scripts', 'doc'),
    ('scripts', 'tests'),
    ('bsd', 'freebsd'),
    ('bsd', 'openbsd'),
    ('bsd', 'netbsd'),
]

# --- replies

REPLY_MISSING_PYTHON_HEADERS = """\
It looks like you're missing `Python.h` headers. This usually means you have \
to install them first, then retry psutil installation.
Please read \
[INSTALL](https://github.com/giampaolo/psutil/blob/master/INSTALL.rst) \
instructions for your platform. \
This is an auto-generated response based on the text you submitted. \
If this was a mistake or you think there's a bug with psutil installation \
process, please add a comment to reopen this issue.
"""

# REPLY_UPDATE_CHANGELOG = """\
# """


# --- github API utils


def is_pr(issue):
    return issue.pull_request is not None


def has_label(issue, label):
    assigned = [x.name for x in issue.labels]
    return label in assigned


def has_os_label(issue):
    labels = set([x.name for x in issue.labels])
    for label in OS_LABELS:
        if label in labels:
            return True
    return False


def get_repo():
    repo = os.environ['GITHUB_REPOSITORY']
    token = os.environ['GITHUB_TOKEN']
    return Github(token).get_repo(repo)


# --- event utils


@functools.lru_cache()
def _get_event_data():
    ret = json.load(open(os.environ["GITHUB_EVENT_PATH"]))
    pp(ret)
    return ret


def is_event_new_issue():
    data = _get_event_data()
    try:
        return data['action'] == 'opened' and 'issue' in data
    except KeyError:
        return False


def is_event_new_pr():
    data = _get_event_data()
    try:
        return data['action'] == 'opened' and 'pull_request' in data
    except KeyError:
        return False


def get_issue():
    data = _get_event_data()
    try:
        num = data['issue']['number']
    except KeyError:
        num = data['pull_request']['number']
    return get_repo().get_issue(number=num)


# --- actions


def log(msg):
    if '\n' in msg or "\r\n" in msg:
        print(">>>\n%s\n<<<" % msg)
    else:
        print(">>> %s <<<" % msg)


def add_label(issue, label):
    def should_add(issue, label):
        if has_label(issue, label):
            log("already has label %r" % (label))
            return False

        for left, right in ILLOGICAL_PAIRS:
            if label == left and has_label(issue, right):
                log("already has label" % (label))
                return False

        return not has_label(issue, label)

    if not should_add(issue, label):
        log("should not add label %r" % label)
        return

    log("add label %r" % label)
    issue.add_to_labels(label)


def _guess_labels_from_text(issue, text):
    for label, keywords in LABELS_MAP.items():
        for keyword in keywords:
            if keyword.lower() in text.lower():
                yield (label, keyword)


def add_labels_from_text(issue, text):
    for label, keyword in _guess_labels_from_text(issue, text):
        add_label(issue, label)


def add_labels_from_new_body(issue, text):
    log("start searching for template lines in new issue/PR body")
    # add os label
    r = re.search(r"\* OS:.*?\n", text)
    log("search for 'OS: ...' line")
    if r:
        log("found")
        add_labels_from_text(issue, r.group(0))
    else:
        log("not found")

    # add bug/enhancement label
    log("search for 'Bug fix: y/n' line")
    r = re.search(r"\* Bug fix:.*?\n", text)
    if (
        is_pr(issue)
        and r is not None
        and not has_label(issue, "bug")
        and not has_label(issue, "enhancement")
    ):
        log("found")
        s = r.group(0).lower()
        if 'yes' in s:
            add_label(issue, 'bug')
        else:
            add_label(issue, 'enhancement')
    else:
        log("not found")

    # add type labels
    log("search for 'Type: ...' line")
    r = re.search(r"\* Type:.*?\n", text)
    if r:
        log("found")
        s = r.group(0).lower()
        if 'doc' in s:
            add_label(issue, 'doc')
        if 'performance' in s:
            add_label(issue, 'performance')
        if 'scripts' in s:
            add_label(issue, 'scripts')
        if 'tests' in s:
            add_label(issue, 'tests')
        if 'wheels' in s:
            add_label(issue, 'wheels')
        if 'new-api' in s:
            add_label(issue, 'new-api')
        if 'new-platform' in s:
            add_label(issue, 'new-platform')
    else:
        log("not found")


# --- events


def on_new_issue(issue):
    def has_text(text):
        return text in issue.title.lower() or text in issue.body.lower()

    log("searching for missing Python.h")
    if (
        has_text("missing python.h")
        or has_text("python.h: no such file or directory")
        or "#include<Python.h>\n^~~~" in issue.body.replace(' ', '')
        or "#include<Python.h>\r\n^~~~" in issue.body.replace(' ', '')
    ):
        log("found")
        issue.create_comment(REPLY_MISSING_PYTHON_HEADERS)
        issue.edit(state='closed')
        return


def on_new_pr(issue):
    pass
    # pr = get_repo().get_pull(issue.number)
    # files = [x.filename for x in list(pr.get_files())]
    # if "HISTORY.rst" not in files:
    #     issue.create_comment(REPLY_UPDATE_CHANGELOG)


def main():
    issue = get_issue()
    stype = "PR" if is_pr(issue) else "issue"
    log("running issue bot for %s %r" % (stype, issue))

    if is_event_new_issue():
        log("created new issue %s" % issue)
        add_labels_from_text(issue, issue.title)
        add_labels_from_new_body(issue, issue.body)
        on_new_issue(issue)
    elif is_event_new_pr():
        log("created new PR %s" % issue)
        add_labels_from_text(issue, issue.title)
        add_labels_from_new_body(issue, issue.body)
        on_new_pr(issue)
    else:
        log("unhandled event")


if __name__ == '__main__':
    main()
