import paramiko

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("172.23.255.8", port=31877, username="root", password="tr88FFAe", timeout=30)

def run(cmd, t=30):
    _, out, err = cli.exec_command(cmd, timeout=t)
    print(f"$ {cmd}\n{out.read().decode(errors='replace')[:3000]}{err.read().decode(errors='replace')[:500]}")

run("ls -la /opt/review/backend/ | head -20")
run("ls /opt/review/backend/*.sh /opt/review/backend/*.env /opt/review/backend/.env 2>/dev/null")
run("grep -rE 'java -jar|spring.datasource|MYSQL' /opt/review/backend/*.sh /opt/review/.env /opt/review/backend/.env 2>/dev/null | head -10")
run("history 2>/dev/null | grep 'java -jar' | tail -3; ps aux | grep -iE 'java' | grep -v grep | head -3")
cli.close()
