"""Upload files to the deployment server via paramiko SFTP."""
import os
import sys
import paramiko

HOST, PORT, USER, PWD = "172.23.255.8", 31877, "root", "tr88FFAe"

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect(HOST, port=PORT, username=USER, password=PWD, timeout=20)
sftp = cli.open_sftp()

pairs = []
for i in range(1, len(sys.argv), 2):
    local = sys.argv[i]
    remote = sys.argv[i + 1]
    pairs.append((local, remote))

for local, remote in pairs:
    sftp.put(local, remote)
    print(f"uploaded {local} -> {remote}", flush=True)

sftp.close()
cli.close()
