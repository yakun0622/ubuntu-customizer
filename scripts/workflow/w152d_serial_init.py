#!/usr/bin/env python3
"""Create the fixed, temporary W152D serial-only PID 1 for USB bring-up.

This gives anyone with physical TTL access a root shell. It is not systemd.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "uc_workspace_w152d_serial_init", HERE / "project_workspace.py")
workspace = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workspace)


SCRIPT = rb"""#!/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH
mount -t devtmpfs devtmpfs /dev || :
mkdir -p /dev/pts /dev/shm || :
mount -t devpts devpts /dev/pts || :
mount -t tmpfs tmpfs /dev/shm || :
mount -t proc proc /proc || :
mount -t sysfs sysfs /sys || :
mount -t tmpfs -o mode=0755 tmpfs /run || :
echo 3 > /proc/sys/kernel/printk 2>/dev/null || :
if [ ! -e /var/lib/.uc-owners-fixed ]; then
    chown 0:0 / /root /etc /var /usr /tmp /var/tmp 2>/dev/null || :
    find /root /etc /var /usr -xdev ! -user 0 -exec chown -h 0:0 {} + 2>/dev/null || :
    chown _apt:root /var/cache/apt/archives/partial /var/lib/apt/lists/partial 2>/dev/null || :
    chown 0:shadow /etc/shadow /etc/gshadow 2>/dev/null || chown 0:42 /etc/shadow /etc/gshadow 2>/dev/null || :
    chmod 0640 /etc/shadow /etc/gshadow 2>/dev/null || :
    sed -i 's/^root:!:/root:*:/' /etc/shadow 2>/dev/null || :
    chmod 1777 /tmp /var/tmp 2>/dev/null || :
    [ -f /usr/bin/su ] && chmod 4755 /usr/bin/su 2>/dev/null || :
    mkdir -p /var/lib && touch /var/lib/.uc-owners-fixed || :
fi
chown 0:0 / /root /etc /var 2>/dev/null || :
chmod 0700 /root 2>/dev/null || :
if [ -d /root/.ssh ]; then
    chown -R 0:0 /root/.ssh 2>/dev/null || :
    chmod 0700 /root/.ssh 2>/dev/null || :
    [ -f /root/.ssh/authorized_keys ] && chmod 0600 /root/.ssh/authorized_keys 2>/dev/null || :
fi
if [ ! -f /etc/apt/apt.conf.d/99-gzip-indexes ] && [ -d /etc/apt/apt.conf.d ]; then
    printf 'Acquire::GzipIndexes "true";\n' > /etc/apt/apt.conf.d/99-gzip-indexes 2>/dev/null || :
fi
if [ -f /usr/lib/firmware/wcnmodem.bin ]; then
    mkdir -p /vendor/firmware /vendor/etc || :
    ln -snf /usr/lib/firmware/wcnmodem.bin /vendor/firmware/wcnmodem.bin || :
    if [ -f /usr/lib/firmware/wifi_board_config.ini ]; then
        ln -snf /usr/lib/firmware/wifi_board_config.ini /vendor/etc/wifi_board_config.ini || :
    fi
fi
if [ ! -x /usr/local/sbin/w152d-wifi-setup ]; then
    mkdir -p /usr/local/sbin || :
    cat > /usr/local/sbin/w152d-wifi-setup <<'EOF_WIFI'
#!/bin/sh
set -eu
if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root" >&2
    exit 1
fi
printf "Wi-Fi SSID: "
IFS= read -r SSID
if [ -z "$SSID" ]; then
    echo "Empty SSID aborted" >&2
    exit 1
fi
printf "Wi-Fi Passphrase (hidden): "
stty -echo
IFS= read -r PSK || { stty echo; exit 1; }
stty echo
printf "\n"
mkdir -p -m 0700 /etc/wpa_supplicant /var/lib/dhcp
umask 0077
{
    printf "ctrl_interface=DIR=/run/wpa_supplicant GROUP=root\nupdate_config=0\n"
    printf "%s\n" "$PSK" | /usr/bin/wpa_passphrase "$SSID" | grep -v '^[[:space:]]*#psk='
} > /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
unset PSK
chmod 0600 /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
pkill -f 'wpa_supplicant.*wlan0' 2>/dev/null || :
sleep 1
/usr/sbin/ip link set wlan0 up
/usr/sbin/wpa_supplicant -B -D nl80211 -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant-wlan0.conf -f /run/wpa_supplicant-wlan0.log
echo "wpa_supplicant started on wlan0; acquiring DHCP lease..."
timeout 20 /usr/sbin/dhclient -1 -lf /var/lib/dhcp/dhclient.wlan0.leases -pf /run/dhclient.wlan0.pid wlan0 || :
/usr/sbin/iw dev wlan0 link || :
/usr/sbin/ip -4 addr show dev wlan0 || :
EOF_WIFI
    chmod 0755 /usr/local/sbin/w152d-wifi-setup 2>/dev/null || :
fi
hostname w152d-ubuntu
if [ ! -e /var/lib/.uc-debs-installed ] && ls /var/cache/uc-debs/*.deb >/dev/null 2>&1; then
    echo 'w152d-init: installing offline Ubuntu Ports .deb bundle (first boot)...'
    mkdir -p -m 0755 /run/sshd /var/lib/dpkg/updates /var/lib/dhcp || :
    if DEBIAN_FRONTEND=noninteractive /usr/bin/dpkg --force-confdef --force-confold -i /var/cache/uc-debs/*.deb >/run/uc-debs-install.log 2>&1 || DEBIAN_FRONTEND=noninteractive /usr/bin/dpkg --force-confdef --force-confold --configure -a >>/run/uc-debs-install.log 2>&1; then
        /usr/sbin/depmod -a "$(uname -r)" 2>/dev/null || :
        rm -f /var/cache/uc-debs/*.deb 2>/dev/null || :
        touch /var/lib/.uc-debs-installed || :
        sync || :
        echo 'w152d-init: offline .deb bundle installed cleanly'
    else
        echo 'w152d-init: offline .deb install reported errors (see /run/uc-debs-install.log)'
    fi
fi
if [ "$(uname -r 2>/dev/null)" = "5.4.210" ] && [ -x /usr/bin/perl ] && [ -r /usr/lib/modules/5.4.210/w152d-eth0.load ]; then
    /usr/bin/perl -e '
        use strict;
        use warnings;
        use Errno qw(EEXIST);
        use Socket qw(AF_INET SOCK_DGRAM);
        my $dir = "/usr/lib/modules/5.4.210";
        open(my $list, "<", "$dir/w152d-eth0.load") or exit 0;
        my ($ok, $fail) = (0, 0);
        while (my $ko = <$list>) {
            chomp $ko;
            next if $ko !~ /\A[a-zA-Z0-9_.-]+\.ko\z/;
            if (open(my $fh, "<", "$dir/$ko")) {
                my $params = "\0";
                my $rc = syscall(273, fileno($fh) + 0, $params, 0);
                if ($rc == 0 || $! == EEXIST) {
                    $ok++;
                } else {
                    $fail++;
                    warn "w152d-init: finit_module $ko failed: $!\n";
                }
                close($fh);
            } else {
                $fail++;
            }
        }
        close($list);
        select(undef, undef, undef, 0.2) if !-e "/sys/class/net/eth0";
        if (socket(my $s, AF_INET, SOCK_DGRAM, 0)) {
            for my $ifname ("lo", "eth0") {
                next unless -e "/sys/class/net/$ifname";
                my $ifr = pack("Z16s<x238", $ifname, 0);
                if (ioctl($s, 0x8913, $ifr)) {
                    my ($n, $flags) = unpack("Z16s<", $ifr);
                    $ifr = pack("Z16s<x238", $ifname, $flags | 1);
                    ioctl($s, 0x8914, $ifr);
                }
            }
            close($s);
        }
        print "w152d-init: eth0 bring-up ok=$ok fail=$fail\n";
    ' || :
fi
if [ -x /usr/sbin/dhclient ] && [ -e /sys/class/net/eth0 ]; then
    mkdir -p /var/lib/dhcp || :
    timeout 15 /usr/sbin/dhclient -1 eth0 >/run/dhclient-eth0.log 2>&1 &
fi
if [ "$(uname -r 2>/dev/null)" = "5.4.210" ] && [ -r /usr/lib/modules/5.4.210/sprdwl_ng.ko ]; then
    (
        /usr/sbin/rfkill unblock all 2>/dev/null || :
        if [ -x /usr/sbin/modprobe ]; then
            /usr/sbin/modprobe wifi_comm && sleep 1
            /usr/sbin/modprobe uwe5621_bsp_sdio && sleep 2
            /usr/sbin/modprobe sprdbt_tty || :
            /usr/sbin/modprobe sprdwl_ng && sleep 1
        elif [ -x /usr/bin/perl ] && [ -r /usr/lib/modules/5.4.210/w152d-wifi.load ]; then
            /usr/bin/perl -e '
                use Errno qw(EEXIST);
                my $dir = "/usr/lib/modules/5.4.210";
                open(my $f, "<", "$dir/w152d-wifi.load") or exit 0;
                while (my $ko = <$f>) {
                    chomp $ko;
                    next if $ko !~ /\A[a-zA-Z0-9_.-]+\.ko\z/;
                    if (open(my $fh, "<", "$dir/$ko")) {
                        my $p = "\0";
                        syscall(273, fileno($fh) + 0, $p, 0);
                        close($fh);
                        select(undef, undef, undef, 1.2);
                    }
                }
            ' || :
        fi
        if [ -x /usr/sbin/ip ] && [ -e /sys/class/net/wlan0 ]; then
            /usr/sbin/ip link set wlan0 up || :
        fi
        if [ -x /usr/sbin/wpa_supplicant ] && [ -s /etc/wpa_supplicant/wpa_supplicant-wlan0.conf ] && [ -e /sys/class/net/wlan0 ]; then
            /usr/sbin/sysctl -qw net.ipv4.conf.all.arp_ignore=1 net.ipv4.conf.all.arp_announce=2 net.ipv4.conf.wlan0.rp_filter=2 net.ipv4.conf.eth0.rp_filter=2 2>/dev/null || :
            mkdir -p /var/lib/dhcp || :
            /usr/sbin/wpa_supplicant -B -D nl80211 -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant-wlan0.conf -f /run/wpa_supplicant-wlan0.log || :
            i=0
            while [ "$i" -lt 20 ]; do
                /usr/sbin/iw dev wlan0 link 2>/dev/null | grep -q 'Connected to' && break
                i=$((i + 1))
                sleep 1
            done
            if [ -x /usr/sbin/dhclient ] && /usr/sbin/iw dev wlan0 link 2>/dev/null | grep -q 'Connected to'; then
                timeout 20 /usr/sbin/dhclient -1 -lf /var/lib/dhcp/dhclient.wlan0.leases -pf /run/dhclient.wlan0.pid wlan0 || :
                if [ "$(cat /sys/class/net/eth0/carrier 2>/dev/null || echo 0)" = "1" ]; then
                    /usr/sbin/ip route replace default via 192.168.2.1 dev eth0 metric 100 2>/dev/null || :
                fi
            fi
        fi
    ) >/run/uwe5621-wifi.log 2>&1 &
fi
if [ -x /usr/sbin/sshd ]; then
    mkdir -p -m 0755 /run/sshd || :
    if [ ! -s /etc/ssh/ssh_host_ed25519_key ] && [ -x /usr/bin/ssh-keygen ]; then
        /usr/bin/ssh-keygen -A >/dev/null 2>&1 || :
    fi
    /usr/sbin/sshd >/run/sshd-start.log 2>&1 || :
fi
echo 'W152D Ubuntu USB serial bring-up (temporary root autologin)'
while :; do
    /usr/sbin/agetty --autologin root -L 921600 ttyS0 vt100
    sleep 1
done
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="New outputs/... regular file")
    args = parser.parse_args()
    path = workspace.checked_output(args.output)
    with path.open("xb") as stream:
        stream.write(SCRIPT)
    path.chmod(0o700)
    print(json.dumps({"file": str(path), "sha256": hashlib.sha256(SCRIPT).hexdigest(),
                      "bytes": len(SCRIPT), "temporary_root_autologin": True}))


if __name__ == "__main__":
    main()
