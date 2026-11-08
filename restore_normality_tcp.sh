echo "[+] Restoring TCP kernel to normal state"

ulimit -n 1024

sudo sysctl -w net.ipv4.ip_local_port_range="32768 60999"
sudo sysctl -w net.ipv4.tcp_tw_reuse=2
sudo sysctl -w net.core.somaxconn=4096
sudo sysctl -w net.ipv4.tcp_max_syn_backlog=1024

echo "[+] Done"
