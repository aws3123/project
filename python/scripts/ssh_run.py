#!/usr/bin/env python
"""SSH 工具：在远程服务器执行命令 / 传输文件。

用法：
    python scripts/ssh_run.py run            "cmd..."          # 执行命令
    python scripts/ssh_run.py run-bg         "cmd..."          # 后台执行并返回
    python scripts/ssh_run.py put  <local> <remote>            # 上传
    python scripts/ssh_run.py get  <remote> <local>            # 下载
    python scripts/ssh_run.py py   <rel_py_file> [py_args]     # 在服务器 python 项目内运行脚本
"""
from __future__ import annotations

import getpass
import os
import stat
import sys

import paramiko

HOST = os.environ.get("SSH_HOST", "172.23.255.8")
PORT = int(os.environ.get("SSH_PORT", "31877"))
USER = os.environ.get("SSH_USER", "root")
PASS = os.environ.get("SSH_PASS", "tr88FFAe")
PY_PROJECT = os.environ.get("PY_PROJECT", "/opt/python-ai")

_intro = "ssh_run>"


def connect() -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, port=PORT, username=USER, password=PASS, timeout=30)
    return c


def run(c, cmd: str, timeout=1200) -> tuple[int, str, str]:
    """执行命令，同时开启 PTY 以便获取 exit code。返回 (code, stdout, stderr)。"""
    code = -1
    out = []
    err = []
    try:
        chan = c.get_transport().open_session()
        chan.get_pty()
        chan.settimeout(None)
        chan.exec_command(cmd)
        while True:
            if chan.recv_ready():
                out.append(chan.recv(65535).decode("utf-8", "replace"))
            if chan.recv_stderr_ready():
                err.append(chan.recv_stderr(65535).decode("utf-8", "replace"))
            if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
                # drain remaining
                while chan.recv_ready():
                    out.append(chan.recv(65535).decode("utf-8", "replace"))
                while chan.recv_stderr_ready():
                    err.append(chan.recv_stderr(65535).decode("utf-8", "replace"))
                code = chan.recv_exit_status()
                break
            chan.get_pty()
            import time
            time.sleep(0.2)
    except Exception as exc:
        err.append(f"<ssh error: {exc}>")
    return code, "".join(out), "".join(err)


def simple(c, cmd: str, timeout=1200):
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def put(c, local, remote):
    sftp = c.open_sftp()
    sftp.put(local, remote)
    sftp.close()
    print(f"{_intro} uploaded {local} -> {remote}")


def put_script_via_stdin(c, name, content, remote_dir):
    """以 BASE64 方式写入脚本，避免引号转义问题。"""
    import base64
    b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
    remote = f"{remote_dir}/{name}"
    cmd = f"echo '{b64}' | base64 -d > '{remote}' && echo WROTE {remote}"
    code, out, err = simple(c, cmd)
    print(out)
    if err.strip():
        print("ERR:", err)
    return remote


def py_run(c, cmd: str):
    """在 python 项目虚拟环境中执行。优先找 venv。"""
    chain = (
        "cd " + PY_PROJECT
        + " && (source .venv/bin/activate 2>/dev/null || source venv/bin/activate 2>/dev/null || true)"
        + " && " + cmd
    )
    return run(c, chain)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    op = sys.argv[1]
    c = connect()
    print(f"{_intro} connected {USER}@{HOST}:{PORT}")

    if op == "run":
        code, out, err = simple(c, sys.argv[2])
        print(out, end="")
        if err:
            print("STDERR:\n" + err, end="")
        print(f"\n{_intro} exit={code}")
    elif op == "run-pde" and False:
        pass
    elif op == "put":
        put(c, sys.argv[2], sys.argv[3])
    elif op == "get":
        sftp = c.open_sftp()
        sftp.get(sys.argv[2], sys.argv[3])
        sftp.close()
        print(f"{_intro} downloaded {sys.argv[2]} -> {sys.argv[3]}")
    elif op == "py":
        # python scripts.xxx args
        code, out, err = py_run(c, sys.argv[2])
        print(out, end="")
        if err:
            print("STDERR:\n" + err, end="")
        print(f"\n{_intro} exit={code}")
    elif op == "py-run-bg":
        pass
    else:
        print(f"unknown op: {op}")
    c.close()


if __name__ == "__main__":
    main()