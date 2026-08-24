import subprocess, sys, time, os, socket
PY = r"C:\msys64\home\aksha\projects\TechRadar\.venv\Scripts\python.exe"
# 1) kill anything listening on 8766
try:
    out = subprocess.run(["netstat","-ano"], capture_output=True, text=True).stdout
    pids = set()
    for line in out.splitlines():
        if ":8766" in line and "LISTENING" in line:
            pids.add(line.split()[-1])
    for p in pids:
        subprocess.run(["taskkill","/F","/PID",p], capture_output=True)
    print("killed:", pids or "none")
except Exception as e:
    print("kill step:", e)
time.sleep(2)
# 2) start detached
log = open(r"C:\msys64\home\aksha\projects\TechRadar\_srv.log","w")
flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
proc = subprocess.Popen([PY, "-m", "techradar.cli", "web", "--host", "127.0.0.1", "--port", "8766"],
                        stdout=log, stderr=log, cwd=r"C:\msys64\home\aksha\projects\TechRadar",
                        creationflags=flags)
print("spawned pid:", proc.pid)
# 3) wait for the port
for i in range(30):
    try:
        s = socket.create_connection(("127.0.0.1", 8766), timeout=1)
        s.close()
        print("port 8766 UP after", i+1, "s")
        break
    except OSError:
        time.sleep(1)
else:
    print("port never came up; log tail:")
    try: print(open(r"C:\msys64\home\aksha\projects\TechRadar\_srv.log").read()[-500:])
    except Exception as e: print(e)
print("DONE")
