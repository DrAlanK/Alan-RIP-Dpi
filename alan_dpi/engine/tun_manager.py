import ctypes
import os
import platform
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Callable, List, Optional, Tuple
import requests


TUN_ADAPTER_NAME = "AlanTUN"
TUN_LOCAL_IP = "198.18.0.1"
TUN_SUBNET_MASK = "255.255.0.0"
WINTUN_ZIP_URL = "https://www.wintun.net/builds/wintun-0.14.1.zip"


def is_windows_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin(extra_args: Optional[List[str]] = None) -> bool:
    if os.name != "nt":
        return False
    try:
        passthrough = [a for a in sys.argv[1:] if a not in ("--tun-on", "--resume-connect")]
        if extra_args:
            for flag in extra_args:
                if flag and (flag not in passthrough):
                    passthrough.append(flag)

        if getattr(sys, "frozen", False):
            exe_path = os.path.abspath(sys.executable)
            params = " ".join(f'"{a}"' for a in passthrough).strip()
            work_dir = os.path.dirname(exe_path)
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, params, work_dir, 1)
            return int(rc) > 32

        script = os.path.abspath(sys.argv[0])
        py_exe = os.path.abspath(sys.executable)
        pyw_candidate = os.path.join(os.path.dirname(py_exe), "pythonw.exe")
        runner = pyw_candidate if os.path.exists(pyw_candidate) else py_exe

        arg_str = " ".join(f'"{a}"' for a in passthrough)
        params = f'"{script}" {arg_str}'.strip()
        work_dir = os.path.dirname(script)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", runner, params, work_dir, 1)
        return int(rc) > 32
    except Exception:
        return False


class WindowsXrayTunManager:
    def __init__(self, core_dir: str, log_fn: Optional[Callable[[str], None]] = None):
        self.core_dir = core_dir
        self._log_fn = log_fn
        self.active = False
        self._tun2socks_proc: Optional[subprocess.Popen] = None
        self._physical_gateway: str = ""
        self._physical_alias: str = ""
        self._pinned_endpoint_ip: str = ""

    def _log(self, msg: str):
        if self._log_fn is not None:
            self._log_fn(msg)

    @staticmethod
    def _run_cmd(args: list, timeout: float = 4.0) -> Tuple[int, str]:
        if os.name != "nt":
            return 1, ""
        try:
            res = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return res.returncode, (res.stdout or "").strip()
        except Exception as exc:
            return 1, str(exc)

    def detect_physical_egress(self) -> Tuple[str, str]:
        if os.name != "nt":
            return "", ""
        ps_cmd = (
            "Get-NetRoute -DestinationPrefix '0.0.0.0/0' | "
            "Where-Object { $_.NextHop -ne '0.0.0.0' -and $_.NextHop -notlike '198.18.*' } | "
            "Sort-Object RouteMetric | Select-Object -First 1 | "
            "ForEach-Object { $a = (Get-NetIPInterface -InterfaceIndex $_.InterfaceIndex -AddressFamily IPv4).InterfaceAlias; "
            "Write-Output ($_.NextHop + '|' + $a) }"
        )
        rc, out = self._run_cmd(["powershell", "-NoProfile", "-Command", ps_cmd], timeout=4.0)
        if (rc == 0) and ("|" in out):
            line = out.splitlines()[0].strip()
            gw, alias = line.split("|", 1)
            self._physical_gateway = gw.strip()
            self._physical_alias = alias.strip()
            return self._physical_gateway, self._physical_alias
        return self._physical_gateway, self._physical_alias

    @property
    def physical_alias(self) -> str:
        if not self._physical_alias:
            self.detect_physical_egress()
        return self._physical_alias

    @property
    def wintun_dll_path(self) -> str:
        return os.path.join(self.core_dir, "wintun.dll")

    def has_wintun_dll(self) -> bool:
        return os.path.exists(self.wintun_dll_path)

    def ensure_wintun_dll(self) -> Tuple[bool, str]:
        if self.has_wintun_dll():
            return True, "Ready"
        os.makedirs(self.core_dir, exist_ok=True)
        arch_raw = (platform.machine() or "").lower()
        if "arm" in arch_raw:
            wintun_arch = "arm64"
        elif "64" in arch_raw:
            wintun_arch = "amd64"
        else:
            wintun_arch = "x86"

        tmp_zip = os.path.join(tempfile.gettempdir(), "alan_wintun_drv.zip")
        sess = requests.Session()
        sess.trust_env = False
        try:
            self._log(f"[TUN] Provisioning Wintun driver ({wintun_arch})...")
            resp = sess.get(WINTUN_ZIP_URL, timeout=12.0)
            if resp.status_code != 200:
                return False, f"خطا در دریافت درایور Wintun (HTTP {resp.status_code})"
            with open(tmp_zip, "wb") as fh:
                fh.write(resp.content)
            member_name = f"wintun/bin/{wintun_arch}/wintun.dll"
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                with zf.open(member_name) as src_f, open(self.wintun_dll_path, "wb") as dst_f:
                    dst_f.write(src_f.read())
            self._log("[TUN] wintun.dll provisioned successfully.")
            return True, "Ready"
        except Exception as exc:
            return False, f"فایل wintun.dll یافت نشد ({exc})"
        finally:
            sess.close()
            try:
                if os.path.exists(tmp_zip):
                    os.remove(tmp_zip)
            except Exception:
                pass

    def pin_endpoint_direct_route(self, ip_or_host: str):
        if (os.name != "nt") or (not self._physical_gateway):
            return
        clean = (ip_or_host or "").strip()
        if (not clean) or clean.startswith("127.") or (not clean[0].isdigit()):
            return
        if self._pinned_endpoint_ip and (self._pinned_endpoint_ip != clean):
            self._run_cmd(["route", "delete", self._pinned_endpoint_ip])
        self._pinned_endpoint_ip = clean
        self._run_cmd(["route", "add", clean, "mask", "255.255.255.255", self._physical_gateway, "metric", "1"])

    def _wait_for_adapter(self, timeout: float = 5.0) -> bool:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            rc, _ = self._run_cmd(["netsh", "interface", "ip", "show", "config", f"name={TUN_ADAPTER_NAME}"], timeout=2.0)
            if rc == 0:
                return True
            time.sleep(0.18)
        return False

    def activate_routes_for_xray_tun(
        self,
        socks_port: int,
        native_xray_tun_active: bool,
        tun_dns: str = "1.1.1.1",
        endpoint_ip: str = "",
    ) -> Tuple[bool, str]:
        if os.name != "nt":
            return False, "حالت TUN مختص ویندوز است."

        if not is_windows_admin():
            return False, "نیاز به دسترسی Administrator است."

        ok_dll, dll_msg = self.ensure_wintun_dll()
        if not ok_dll:
            return False, dll_msg

        gw, _ = self.detect_physical_egress()
        if not gw:
            return False, "درگاه شبکه فیزیکی شناسایی نشد."

        if not native_xray_tun_active:
            helper_exe = os.path.join(self.core_dir, "tun2socks.exe")
            if not os.path.exists(helper_exe):
                return False, "هسته xray.exe را به نسخه ۲۵.۸ به بالا بروزرسانی کنید تا TUN بومی فعال شود."
            self._tun2socks_proc = subprocess.Popen(
                [helper_exe, "-device", f"wintun://{TUN_ADAPTER_NAME}", "-proxy", f"socks5://127.0.0.1:{socks_port}"],
                cwd=self.core_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )

        if not self._wait_for_adapter(timeout=5.5):
            self.stop()
            return False, "کارت مجازی AlanTUN ساخته نشد."

        if endpoint_ip:
            self.pin_endpoint_direct_route(endpoint_ip)

        self._run_cmd([
            "netsh", "interface", "ip", "set", "address",
            f"name={TUN_ADAPTER_NAME}", "static", TUN_LOCAL_IP, TUN_SUBNET_MASK, "none"
        ])
        self._run_cmd([
            "netsh", "interface", "ip", "set", "dns",
            f"name={TUN_ADAPTER_NAME}", "static", tun_dns or "1.1.1.1", "primary"
        ])
        self._run_cmd(["route", "add", "0.0.0.0", "mask", "128.0.0.0", TUN_LOCAL_IP, "metric", "5"])
        self._run_cmd(["route", "add", "128.0.0.0", "mask", "128.0.0.0", TUN_LOCAL_IP, "metric", "5"])

        self.active = True
        self._log(f"[TUN] Xray Wintun active via {TUN_ADAPTER_NAME} (GW bypass: {gw})")
        return True, "ON"

    def stop(self):
        if os.name == "nt":
            self._run_cmd(["route", "delete", "0.0.0.0", "mask", "128.0.0.0", TUN_LOCAL_IP])
            self._run_cmd(["route", "delete", "128.0.0.0", "mask", "128.0.0.0", TUN_LOCAL_IP])
            if self._pinned_endpoint_ip:
                self._run_cmd(["route", "delete", self._pinned_endpoint_ip])
                self._pinned_endpoint_ip = ""

        if self._tun2socks_proc is not None:
            try:
                self._tun2socks_proc.terminate()
                self._tun2socks_proc.wait(timeout=1.5)
            except Exception:
                try:
                    self._tun2socks_proc.kill()
                except Exception:
                    pass
            self._tun2socks_proc = None

        if self.active:
            self._log("[TUN] Xray Wintun routes cleaned up.")
        self.active = False
