# DoS_todo
A script written in Python 3 that automates a DoS attack against Cloudflare-protected servers, as well as specific IP addresses or hosts.

# Installation method

First, we will clone the repository:
```console
git clone https://github.com/spid3rtto/DoS_todo
```
Grant execution permissions and run setup_tcp.sh:
```console
chmod +x setup_tcp.sh && ./setup_tcp.sh
```
Finally, run the DoS script:
```console
python3 dos_script.py
```
""If you are attacking a Cloudflare, use --mode waf""

When handling threads, use 1,000 threads—or whatever number you prefer, provided it is less than 2,500—as exceeding this could cause an OOM (Out of Memory) error.
The `setup_tcp.sh` script serves to optimize the Linux kernel for handling a massive volume of concurrent TCP connections.

When you finish running the script, execute:

```console
chmod +x restore_normality_tcp.sh && ./restore_normality_tcp.sh
```
This allows for restoring the system's standard values ​​while the system is running.
