Как узнать аптайм процесса, запущенного через systemd

Если ваш Userbot или любой другой сервис запускается через systemd, вы можете узнать аптайм (время работы текущего процесса) следующим образом:

  

## 1. Получить PID процесса, запущенного systemd

  

Выполните команду:

  

```

systemctl show <service_name> -p MainPID

```

  

Пример для сервиса с именем `mybot.service`:

  

```

systemctl show mybot.service -p MainPID

```

  

Ответ будет вида:

```

MainPID=12345

```

  

## 2. Получить аптайм процесса по PID

  

В Linux (Ubuntu и других дистрибутивах) можно узнать аптайм процесса через `/proc/<PID>/stat` и `/proc/uptime`.

  

### Пример однострочника (bash):

  

```bash

PID=$(systemctl show mybot.service -p MainPID | cut -d'=' -f2)

if [ -n "$PID" ] && [ "$PID" -ne 0 ]; then

UPTIME=$(awk -v pid=$PID 'BEGIN { clk_tck=0 } \

NR==1 { sys_uptime=$1 } \

END { \

if (clk_tck==0) clk_tck=system("getconf CLK_TCK"); \

getline < "/proc/"pid"/stat"; \

split($0, a, " "); \

starttime=a[22]; \

proc_uptime=sys_uptime-(starttime/clk_tck); \

printf("%.0f\n", proc_uptime) \

}' /proc/uptime)

echo "Аптайм процесса: $UPTIME секунд"

else

echo "Процесс не запущен"

fi

```

  

### Пример на Python:

  

```python

import os

import subprocess

  

def get_systemd_pid(service_name):

result = subprocess.run([

"systemctl", "show", service_name, "-p", "MainPID"

], capture_output=True, text=True)

pid_line = result.stdout.strip()

pid = int(pid_line.split('=')[1])

return pid

  

def get_process_uptime(pid):

with open(f"/proc/{pid}/stat") as f:

fields = f.read().split()

starttime = int(fields[21]) # 22-е поле, индексация с 0

with open("/proc/uptime") as f:

uptime = float(f.read().split()[0])

ticks_per_second = os.sysconf(os.sysconf_names['SC_CLK_TCK'])

process_uptime = uptime - (starttime / ticks_per_second)

return process_uptime

  

service = "mybot.service" # замените на имя вашего systemd-сервиса

pid = get_systemd_pid(service)

if pid > 0:

print(f"Аптайм процесса: {get_process_uptime(pid):.0f} секунд")

else:

print("Процесс не запущен")

```  



---

  

**Эти инструкции можно использовать для мониторинга, алертов и автоматизации!**