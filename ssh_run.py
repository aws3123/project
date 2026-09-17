"""Execute a remote command on the deployment server via paramiko."""
import sys
import paramiko

HOST, PORT, USER, PWD = "172.23.255.8", 31877, "root", "tr88FFAe"

cmd = sys.argv[1] if len(sys.argv) > 1 else "hostname"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, port=PORT, username=USER, password=PWD, timeout=20)
_stdin, stdout, stderr = cli.exec_command(cmd, timeout=120)
out = stdout.read().decode("utf-8", "replace")
err = stderr.read().decode("utf-8", "replace")
rc = stdout.channel.recv_exit_status()
if out:
    print(out, end="")
if err:
    print("STDERR:", err, end="", file=sys.stderr)
print(f"[exit={rc}]", file=sys.stderr)
cli.close()
